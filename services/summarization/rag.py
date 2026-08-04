"""RAG: embeddings, ChromaDB vector store, and the grounded Q&A chain.

Merged from the old core/rag_engine.py + core/vector_store.py.

Collections are PER JOB (name "job_{job_id}"): retrieval from one video can
never bleed into another — this fixes the old shared-collection bug where
every job appended into a single "video_transcript" collection.
"""

from dotenv import load_dotenv
import os

load_dotenv()

import chromadb
from langchain_chroma import Chroma
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

CHROMA_DIR = os.getenv("CHROMA_DIR", "vector_db")
EMBEDDING_MODEL = "mistral-embed"


def collection_name_for(job_id: str) -> str:
    return f"job_{job_id}"


def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=CHROMA_DIR)


def reset_collection(collection_name: str) -> None:
    """Drop a collection if it exists (idempotent).

    Called before indexing a job so re-processing (or a cold-pod rebuild)
    never duplicates chunks inside the same collection.
    """
    try:
        _client().delete_collection(collection_name)
    except Exception:
        pass  # collection doesn't exist yet


def delete_collection(collection_name: str) -> None:
    """Drop a job's collection (called when the job is deleted)."""
    reset_collection(collection_name)


def get_llm():
    return ChatMistralAI(
        model="mistral-small-2603",
        temperature=0.3
    )


def get_embeddings():
    return MistralAIEmbeddings(
        model=EMBEDDING_MODEL,
    )


def build_vector_store(transcript: str, collection_name: str):
    """Chunk a transcript, embed it, and store it in ChromaDB.

    Uses a dedicated collection per call (callers pass a per-job name) so
    retrieval from one video can never bleed into another. The collection
    is reset first so re-indexing never duplicates chunks.
    """
    print(f"Building vector store ({collection_name})")

    reset_collection(collection_name)

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


def build_rag_chain(transcript: str, collection_name: str):
    """Chunk → embed → retrieve chain, all in one (per-job collection)."""
    vector_store = build_vector_store(transcript, collection_name=collection_name)
    return create_rag_chain(vector_store)


def ask_question(rag_chain, question: str) -> str:
    answer = rag_chain.invoke(question)
    return answer
