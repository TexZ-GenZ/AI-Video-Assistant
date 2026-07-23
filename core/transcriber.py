from faster_whisper import WhisperModel, BatchedInferencePipeline
from sarvamai import SarvamAI
from dotenv import load_dotenv
import os
from pydub import AudioSegment

load_dotenv()

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "turbo")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_PIECE_SECONDS = 25

_whisper_pipeline = None
_sarvam_client = None


# ---------- Whisper ----------

def load_model_whisper():
    global _whisper_pipeline

    if _whisper_pipeline is None:
        print("Loading Whisper model...")

        model = WhisperModel(
            WHISPER_MODEL,
            device="cuda",
            compute_type="float16",
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
        print("Loading Sarvam client...")

        _sarvam_client = SarvamAI(
            api_subscription_key=SARVAM_API_KEY,
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
                    mode="transcribe",
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