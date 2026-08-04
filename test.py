from dotenv import load_dotenv
import os

load_dotenv()
from services.ingestion.worker import process_input
from services.transcription.worker import transcribe_all
from services.summarization.summarize import summarize, generate_title
from services.summarization.extractor import extract_action_items, extract_key_information, extract_questions

source = "https://youtu.be/fQ4hkAdihNI?si=vZwHcTndzOgXef88"

chunks = process_input(source)
transcript = transcribe_all(chunks)
print("\n\nTranscript:")
print(transcript)

summary = summarize(transcript)
title = generate_title(transcript)

print("\n\nTitle: ", title)
print("\n\nSummary: ", summary)
actionables = extract_action_items(transcript)
print("\n\nActionables: ", actionables)
questions = extract_questions(transcript)
print("\n\nQuestions: ", questions)
decisions = extract_key_information(transcript)
print("\n\nDecisions: ", decisions)
