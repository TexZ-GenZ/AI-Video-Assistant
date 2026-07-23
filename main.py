from dotenv import load_dotenv
load_dotenv()
from utils.audio_processor import process_input
from core.transcriber import transcribe_all
from core.summarize import summarize, generate_title
from core.extractor import extract_action_items, extract_key_information, extract_questions
from core.rag_engine import build_rag_chain , ask_question

def run_pipeline(source:str , language:str = "english") -> dict:
    print("Running Ai video assistant ...")

    chunks = process_input(source)
    backend = "whisper"
    if language == "hindi" :
        backend = "sarvam"
    transcript = transcribe_all(chunks, backend=backend)

    print(f"\n\nRaw Transcript:\n{transcript[:300]}...")

    title = generate_title(transcript)
    summary = summarize(transcript)
    actionables = extract_action_items(transcript)
    questions = extract_questions(transcript)
    information = extract_key_information(transcript)
    rag_chain = build_rag_chain(transcript)

    return {
        "title" : title,
        "summary" : summary,
        "actionables" : actionables,
        "questions" : questions,
        "information" : information,
        "rag_chain" : rag_chain
    }

if __name__ == "__main__" :
    source = input("Enter Youtube URL or local file path:").strip()
    language = input("Enter language (english/hindi):").strip()
    pipeline_result = run_pipeline(source, language)

    print("\n"+"-"*50+"\n")

    print(f"Title: {pipeline_result['title']}\n")
    print(f"Summary: {pipeline_result['summary']}\n")
    print(f"Actionables: {pipeline_result['actionables']}\n")
    print(f"Questions: {pipeline_result['questions']}\n")
    print(f"Information: {pipeline_result['information']}\n")

    print("\n Chat with the video: \n")
    rag_chain = pipeline_result["rag_chain"]
    while True:
        question = input("Enter your question: ").strip()
        if question.lower() in ["exit", "quit","q"]:
            print("Goodbye!")
            break
        if not question :
            continue
        answer = ask_question(rag_chain , question)
        print(f"Assistant: {answer}\n")