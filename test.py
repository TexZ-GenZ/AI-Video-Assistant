from utils.audio_processor import process_input
from core.transcriber import transcribe_all
import time 

source = "https://youtu.be/vFP1mgZ_LEY?si=0RVaxUISJBbT7_WQ"

start_time = time.time()

chunks = process_input(source)

transcript = transcribe_all(chunks, backend="sarvam")

print(f"Time taken: {time.time() - start_time}")
print(transcript)

