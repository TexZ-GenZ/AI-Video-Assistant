from dotenv import load_dotenv
load_dotenv()
from shared.pipeline import run_pipeline
from services.summarization.rag import ask_question

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
