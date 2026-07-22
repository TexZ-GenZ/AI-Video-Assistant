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

data = download_youtube_url('https://youtu.be/bC3mIQWHZMQ?si=4Ynisi_PqcThgihI')

def convert_to_wav(input_path: str) -> str :
    """Converts any audio/video file to wav using pydub."""
    audio = AudioSegment.from_file(input_path)
    output_path = os.path.splitext(input_path)[0] + '_converted.wav'
    audio = audio.set_channels(1).set_frame_rate(16000)
    audio.export(output_path, format='wav')
    return output_path

print(convert_to_wav(data))

