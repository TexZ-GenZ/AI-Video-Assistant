"""Ingestion worker: acquire audio (YouTube URL / staged S3 upload) and ship
chunks to S3.

Consumes the jobs queue:      {job_id, source, language}
  1. download (yt-dlp) or fetch the staged upload, convert to 16kHz mono WAV
  2. split into 10-minute chunks (local temp workdir)
  3. upload chunks to s3://{JOBS_BUCKET}/jobs/{job_id}/chunks/
  4. publish {job_id, language} to the transcribe queue

Failure semantics: business failures are recorded on the job (set_error) and
the message is acked so it doesn't loop; only worker crashes rely on the DLQ
(visibility-timeout → redrive → DLQ after 3 attempts).

Run as a standalone process:  python -m services.ingestion.worker
"""

from __future__ import annotations

import os
import shutil
import tempfile
import traceback
from pathlib import Path

import yt_dlp
from pydub import AudioSegment

from shared import queue, s3
from shared.dynamo import update_progress, set_error

# Optional root for workdirs (e.g. an emptyDir/EFS mount in prod). All audio
# processing happens here so we never touch the source tree.
WORKDIR_ROOT = os.getenv("INGESTION_WORKDIR") or None


def _make_workdir() -> str:
    base = WORKDIR_ROOT or tempfile.gettempdir()
    return tempfile.mkdtemp(prefix="videosense-ingest-", dir=base)


# ── audio acquisition ──────────────────────────────────────────────────────

def download_youtube_url(url: str, workdir: str) -> str:
    ydl_opts = {
        'outtmpl': os.path.join(workdir, '%(title)s.%(ext)s'),
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': True,
    }

    # YouTube bot-checks cloud/datacenter IPs — a session cookie file
    # (COOKIES_FILE, mounted as a k8s secret in prod) gets past the
    # "Sign in to confirm you're not a bot" wall. kubelet mounts secret
    # volumes read-only, but yt-dlp wants to update the cookie jar — so
    # copy it into the writable workdir first.
    cookies_file = os.getenv("COOKIES_FILE")
    if cookies_file and os.path.exists(cookies_file):
        writable_cookies = os.path.join(workdir, "cookies.txt")
        shutil.copyfile(cookies_file, writable_cookies)
        ydl_opts['cookiefile'] = writable_cookies

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info_dict).replace('.webm', '.wav').replace('.m4a', '.wav')

    return filename


def convert_to_wav(input_path: str, workdir: str) -> str:
    """Convert any audio/video file to 16kHz mono wav using pydub."""
    audio = AudioSegment.from_file(input_path)
    output_path = os.path.join(workdir, Path(input_path).stem + "_converted.wav")
    audio = audio.set_channels(1).set_frame_rate(16000)
    audio.export(output_path, format='wav')
    return output_path


def chunk_audio(wav_path: str, chunk_minutes: int = 10) -> list:
    audio = AudioSegment.from_wav(wav_path)
    chunk_ms = chunk_minutes * 60 * 1000

    chunks = []

    for i, start in enumerate(range(0, len(audio), chunk_ms)):
        end = start + chunk_ms
        chunk = audio[start:end]
        chunk_path = os.path.splitext(wav_path)[0] + f'_chunk{i}.wav'
        chunk.export(chunk_path, format='wav')
        chunks.append(chunk_path)

    return chunks


def _is_file_id(source: str) -> bool:
    return not (
        source.startswith("http://") or source.startswith("https://")
    ) and "/" not in source and "\\" not in source


def _download_staged_file(file_id: str, workdir: str) -> str:
    """Fetch an uploaded file from the S3 staging area (uploads/{file_id}.*)."""
    keys = s3.list_keys(f"uploads/{file_id}")
    if not keys:
        raise FileNotFoundError(f"uploaded file {file_id} not found in S3")
    key = sorted(keys)[0]
    dest = os.path.join(workdir, os.path.basename(key))
    s3.download_to_path(key, dest)
    return dest


def process_input(source: str, workdir: str | None = None) -> list:
    """Acquire audio from a YouTube URL or a local/staged file, chunk it.

    Returns chunk paths (created inside `workdir`; caller cleans up). If
    `workdir` is None, a fresh temp dir is created for the call.
    """
    if workdir is None:
        workdir = _make_workdir()
    Path(workdir).mkdir(parents=True, exist_ok=True)

    if source.startswith("https://") or source.startswith("http://"):
        print("Downloading audio from YouTube...")
        wav_path = download_youtube_url(source, workdir)
    else:
        print("Converting local audio file to wav...")
        local = _download_staged_file(source, workdir) if _is_file_id(source) else source
        wav_path = convert_to_wav(local, workdir)

    print("Chunking audio...")
    chunks = chunk_audio(wav_path)
    print(f"Audio ready - {len(chunks)} chunk(s) created.")
    return chunks


# ── job processing ─────────────────────────────────────────────────────────

def process_job_message(msg: dict) -> None:
    """Process one jobs-queue message end to end (never raises)."""
    job_id = msg["job_id"]
    source = msg.get("source", "")
    language = msg.get("language", "english")

    workdir = _make_workdir()
    try:
        update_progress(job_id, "Downloading audio...")
        chunks = process_input(source, workdir=workdir)

        update_progress(job_id, "Uploading audio chunks...")
        for i, chunk in enumerate(chunks):
            s3.upload_bytes(
                s3.chunk_key(job_id, f"chunk_{i}.wav"),
                Path(chunk).read_bytes(),
                "audio/wav",
            )

        queue.publish(queue.QUEUE_TRANSCRIBE, {"job_id": job_id, "language": language})
        update_progress(job_id, "Queued for transcription")

    except Exception as exc:
        set_error(job_id, str(exc))
        traceback.print_exc()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_worker(poll_seconds: int = 20, visibility: int = 1800) -> None:
    """Long-poll the jobs queue forever."""
    print(f"Ingestion worker polling {queue.QUEUE_JOBS} ...")
    while True:
        try:
            messages = queue.receive(
                queue.QUEUE_JOBS, wait=poll_seconds, visibility=visibility
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
                    queue.ack(msg["receipt_handle"], queue.QUEUE_JOBS)
                except Exception:
                    traceback.print_exc()


if __name__ == "__main__":
    run_worker()
