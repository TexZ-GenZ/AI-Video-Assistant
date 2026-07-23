from dotenv import load_dotenv
import os

load_dotenv()
from langchain_chroma import Chroma
from langchain_mistralai import MistralAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

CHROMA_DIR = "vector_db"
COLLECTION_NAME = "video_transcript"
EMBEDDING_MODEL = "mistral-embed"

def get_embeddings():
    return MistralAIEmbeddings(
        model=EMBEDDING_MODEL,
    )

def build_vector_store(transcript : str) -> str :
    print("Building vector Store")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, 
        chunk_overlap=50
    )

    chunks = splitter.split_text(transcript)

    docs = [
        Document(page_content=chunk, metadata={"chunk": i}) for i, chunk in enumerate(chunks)
    ]

    embeddings = get_embeddings()

    vector_store = Chroma.from_documents(
        documents=docs,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
        persist_directory=CHROMA_DIR, 
    )

    return vector_store

def load_vector_store() -> Chroma :
    embeddings = get_embeddings()

    vector_store = Chroma(
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
        persist_directory=CHROMA_DIR, 
    )

    return vector_store

def get_retriever(vector_store : Chroma , k:int = 4) :
    return vector_store.as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": 4,
            "fetch_k": 10, 
            "lambda_mult": 0.5
        },
    )

