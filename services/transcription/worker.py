"""Transcription worker: speech-to-text for job audio chunks.

Consumes the transcribe queue:  {job_id, language}
  1. download chunks from s3://{JOBS_BUCKET}/jobs/{job_id}/chunks/
  2. transcribe each chunk in order (faster-whisper for english,
     Sarvam AI for hindi) and join the results
  3. upload the transcript to s3://{JOBS_BUCKET}/jobs/{job_id}/transcript.txt
  4. publish {job_id, language} to the summarize queue

Environment:
  WHISPER_MODEL      model size (default "small" — CPU-friendly; "turbo" for GPU)
  WHISPER_DEVICE     "cpu" (default — Fargate has no GPU) | "cuda"
  WHISPER_CACHE_DIR  model cache dir; mount EFS here in prod so every pod
                     doesn't re-download the weights
  SARVAM_API_KEY     required only for hindi jobs

Run as a standalone process:  python -m services.transcription.worker
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import traceback

from dotenv import load_dotenv
from faster_whisper import WhisperModel, BatchedInferencePipeline
from sarvamai import SarvamAI
from pydub import AudioSegment

from shared import queue, s3
from shared.dynamo import update_progress, set_error

load_dotenv()

SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_PIECE_SECONDS = 25

_whisper_pipeline = None
_sarvam_client = None


# ---------- Whisper ----------

def _whisper_config() -> tuple[str, str]:
    """Map WHISPER_DEVICE to (device, compute_type).

    CUDA → float16 (fast path, original local setup).
    CPU  → int8 (CTranslate2's recommended CPU compute type; float16 on CPU
           is slower and int8 is a fraction of the size).
    """
    device = os.getenv("WHISPER_DEVICE", "cpu").lower()
    compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def load_model_whisper():
    global _whisper_pipeline

    if _whisper_pipeline is None:
        model_name = os.getenv("WHISPER_MODEL", "small")
        device, compute_type = _whisper_config()
        cache_dir = os.getenv("WHISPER_CACHE_DIR") or None
        print(f"Loading Whisper model ({model_name}, {device}/{compute_type})...")

        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=cache_dir,
        )

        _whisper_pipeline = BatchedInferencePipeline(model)

    return _whisper_pipeline


def transcribe_chunk_whisper(chunk_path: str, translate: bool = False) -> str:
    model = load_model_whisper()

    task = "translate" if translate else "transcribe"

    segments, info = model.transcribe(
        chunk_path,
        batch_size=16,
        task=task,
        vad_filter=True,
    )

    return " ".join(segment.text for segment in segments)


# ---------- Sarvam ----------

def load_model_sarvam():
    global _sarvam_client

    if _sarvam_client is None:
        api_key = os.getenv("SARVAM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "SARVAM_API_KEY is not set (required for hindi jobs)"
            )
        print("Loading Sarvam client...")

        _sarvam_client = SarvamAI(
            api_subscription_key=api_key,
        )

    return _sarvam_client


def transcribe_chunk_sarvam(
    chunk_path: str,
    language_code: str = "hi-IN",
) -> str:
    """
    Sarvam sync API accepts a maximum of 30 seconds.
    Split the chunk into 25-second pieces, transcribe each,
    and join the results.
    """

    client = load_model_sarvam()

    audio = AudioSegment.from_wav(chunk_path)

    piece_ms = SARVAM_PIECE_SECONDS * 1000

    transcripts = []

    total_pieces = (len(audio) + piece_ms - 1) // piece_ms

    for i, start in enumerate(range(0, len(audio), piece_ms)):
        end = min(start + piece_ms, len(audio))

        piece = (
            audio[start:end]
            .set_frame_rate(16000)
            .set_channels(1)
        )

        piece_path = f"{chunk_path}.sarvam_{i}.wav"

        piece.export(
            piece_path,
            format="wav",
        )

        try:
            print(
                f"  → Sarvam piece {i+1}/{total_pieces}"
            )

            with open(piece_path, "rb") as f:

                response = client.speech_to_text.transcribe(
                    file=f,
                    model=SARVAM_STT_MODEL,
                    language_code=language_code,
                    mode="translate",
                    input_audio_codec="wav",
                )

            transcripts.append(response.transcript)

        finally:
            if os.path.exists(piece_path):
                os.remove(piece_path)

    return " ".join(transcripts)


# ---------- Unified Interface ----------

def transcribe_chunk(
    chunk_path: str,
    backend: str = "whisper",
    **kwargs,
) -> str:

    backend = backend.lower()

    if backend == "whisper":
        return transcribe_chunk_whisper(chunk_path, **kwargs)

    if backend == "sarvam":
        return transcribe_chunk_sarvam(chunk_path, **kwargs)

    raise ValueError(f"Unsupported backend: {backend}")


def transcribe_all(
    chunks: list[str],
    backend: str = "whisper",
    **kwargs,
) -> str:

    print(f"Using {backend.title()} for transcription.")

    texts = []

    for i, chunk in enumerate(chunks):
        print(f"Transcribing chunk {i+1}/{len(chunks)}...")
        texts.append(
            transcribe_chunk(
                chunk,
                backend=backend,
                **kwargs,
            )
        )

    print("Transcription complete.")

    return " ".join(texts)


# ---------- job processing ----------

_CHUNK_RE = re.compile(r"chunk_(\d+)\.")


def _chunk_sort_key(key: str) -> int:
    """Natural sort key: chunk_2.wav must come before chunk_10.wav
    (plain lexicographic order would flip them)."""
    match = _CHUNK_RE.search(key)
    return int(match.group(1)) if match else 0


def _download_chunks(job_id: str, workdir: str) -> list[str]:
    """Fetch all audio chunks for a job into workdir, in order."""
    keys = sorted(s3.list_keys(s3.chunk_prefix(job_id)), key=_chunk_sort_key)
    if not keys:
        raise FileNotFoundError(f"no audio chunks found for job {job_id}")

    paths = []
    for key in keys:
        dest = os.path.join(workdir, os.path.basename(key))
        s3.download_to_path(key, dest)
        paths.append(dest)
    return paths


def process_job_message(msg: dict) -> None:
    """Process one transcribe-queue message end to end (never raises)."""
    job_id = msg["job_id"]
    language = msg.get("language", "english")
    backend = "whisper" if language != "hindi" else "sarvam"

    workdir = tempfile.mkdtemp(prefix="videosense-transcribe-")
    try:
        update_progress(job_id, "Downloading audio chunks...")
        chunks = _download_chunks(job_id, workdir)

        update_progress(job_id, f"Transcribing ({backend})...")
        transcript = transcribe_all(chunks, backend=backend)

        if not transcript.strip():
            raise RuntimeError("transcription produced no text")

        update_progress(job_id, "Saving transcript...")
        s3.upload_text(s3.transcript_key(job_id), transcript)

        queue.publish(queue.QUEUE_SUMMARIZE, {"job_id": job_id, "language": language})
        update_progress(job_id, "Queued for analysis")

    except Exception as exc:
        set_error(job_id, str(exc))
        traceback.print_exc()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_worker(poll_seconds: int = 20, visibility: int = 3600) -> None:
    """Long-poll the transcribe queue forever.

    Visibility is 1h: a CPU transcription of a long video can take tens of
    minutes, and an in-flight message must not be redelivered mid-work.
    """
    print(f"Transcription worker polling {queue.QUEUE_TRANSCRIBE} ...")
    while True:
        try:
            messages = queue.receive(
                queue.QUEUE_TRANSCRIBE, wait=poll_seconds, visibility=visibility
            )
        except Exception:
            traceback.print_exc()
            continue

        for msg in messages:
            try:
                process_job_message(msg["body"])
            finally:
                # Always ack: business errors are recorded on the job. If the
                # process crashes mid-message, no ack → redrive → DLQ.
                try:
                    queue.ack(msg["receipt_handle"], queue.QUEUE_TRANSCRIBE)
                except Exception:
                    traceback.print_exc()


if __name__ == "__main__":
    run_worker()
