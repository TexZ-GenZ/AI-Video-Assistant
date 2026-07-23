from dotenv import load_dotenv
import os

load_dotenv()
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda , RunnablePassthrough
from core.vector_store import build_vector_store, load_vector_store , get_retriever

def get_llm():
    return ChatMistralAI(
        model="mistral-small-2603",
        temperature=0.3
    )

def format_docs(docs):
    return "\n\n".join([doc.page_content for doc in docs])

def create_rag_chain(vector_store):
    retriever = get_retriever(vector_store)
    llm = get_llm()

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are an expert video analyst. "
            "Answer the user's question using the provided context. "
            "If the answer is not in the given context, say that the information is not available in the video.\n\n"
            "Context:\n{context}"
        ),
        ("human", "{question}")
    ])

    return (
        {
            "context": retriever | RunnableLambda(format_docs),
            "question": RunnablePassthrough(),
        }
        | prompt
        | llm
        | StrOutputParser()
    )

def build_rag_chain(transcript):
    vector_store = build_vector_store(transcript)
    return create_rag_chain(vector_store)

def load_rag_chain():
    vector_store = load_vector_store()
    return create_rag_chain(vector_store)

def ask_question(rag_chain , question : str) -> str:
    answer = rag_chain.invoke(question)
    return answer