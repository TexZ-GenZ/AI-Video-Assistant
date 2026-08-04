"""RAG: embeddings, ChromaDB vector store, and the grounded Q&A chain.

Merged from the old core/rag_engine.py + core/vector_store.py.
"""

from dotenv import load_dotenv
import os

load_dotenv()

from langchain_chroma import Chroma
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

CHROMA_DIR = os.getenv("CHROMA_DIR", "vector_db")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "video_transcript")
EMBEDDING_MODEL = "mistral-embed"


def get_llm():
    return ChatMistralAI(
        model="mistral-small-2603",
        temperature=0.3
    )


def get_embeddings():
    return MistralAIEmbeddings(
        model=EMBEDDING_MODEL,
    )


def build_vector_store(transcript: str, collection_name: str = COLLECTION_NAME):
    """Chunk a transcript, embed it, and store it in ChromaDB.

    Uses a dedicated collection per call (callers pass a per-job name) so
    retrieval from one video can never bleed into another.
    """
    print("Building vector store")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )

    chunks = splitter.split_text(transcript)

    docs = [
        Document(page_content=chunk, metadata={"chunk": i})
        for i, chunk in enumerate(chunks)
    ]

    embeddings = get_embeddings()

    vector_store = Chroma.from_documents(
        documents=docs,
        collection_name=collection_name,
        embedding=embeddings,
        persist_directory=CHROMA_DIR,
    )

    return vector_store


def get_retriever(vector_store: Chroma, k: int = 4):
    return vector_store.as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": 4,
            "fetch_k": 10,
            "lambda_mult": 0.5,
        },
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


def build_rag_chain(transcript: str, collection_name: str = COLLECTION_NAME):
    """Chunk → embed → retrieve chain, all in one."""
    vector_store = build_vector_store(transcript, collection_name=collection_name)
    return create_rag_chain(vector_store)


def ask_question(rag_chain, question: str) -> str:
    answer = rag_chain.invoke(question)
    return answer
