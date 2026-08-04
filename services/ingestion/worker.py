import yt_dlp 
from pydub import AudioSegment
import os

DOWNLOAD_DIR = '../downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def download_youtube_url(url : str) -> str :
    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info_dict).replace('.webm', '.wav').replace('.m4a', '.wav')

    return filename


def convert_to_wav(input_path: str) -> str :
    """Converts any audio/video file to wav using pydub."""
    audio = AudioSegment.from_file(input_path)
    output_path = os.path.splitext(input_path)[0] + '_converted.wav'
    audio = audio.set_channels(1).set_frame_rate(16000)
    audio.export(output_path, format='wav')
    return output_path

def chunk_audio(wav_path : str , chunk_minutes : int = 10) -> list :
    audio = AudioSegment.from_wav(wav_path)
    chunk_ms = chunk_minutes * 60 * 1000

    chunks = []

    for i , start in enumerate(range(0, len(audio), chunk_ms)) :
        end = start + chunk_ms
        chunk = audio[start:end]
        chunk_path = os.path.splitext(wav_path)[0] + f'_chunk{i}.wav'
        chunk.export(chunk_path, format='wav')
        chunks.append(chunk_path)

    return chunks

def process_input(source : str) -> list :
    if source.startswith('https://') or source.startswith('http://') :
        print("Downloading audio from YouTube...")
        wav_path = download_youtube_url(source)
    else :
        print("Converting local audio file to wav...")
        wav_path = convert_to_wav(source)

    print("Chunking audio...")
    chunks = chunk_audio(wav_path = wav_path)
    print(f"Audio ready - {len(chunks)} chunk(s) created.")
    return chunks

