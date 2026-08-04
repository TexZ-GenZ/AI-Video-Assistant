from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnableLambda  , RunnablePassthrough
import os 
from dotenv import load_dotenv

load_dotenv()

def get_llm():
    return ChatMistralAI(
        model="mistral-small-2603",
        temperature=0.3
    )

def split_transcipt(transcript : str) -> list :
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=3000, 
        chunk_overlap=200
    )

    return splitter.split_text(transcript)

def summarize(transcript : str) -> str :
    llm = get_llm()

    map_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "Write a summary of the following transcript"),
            ("human", "{text}")
        ]
    )

    map_chain = map_prompt | llm | StrOutputParser()

    chunks = split_transcipt(transcript)

    chunk_summaries = [map_chain.invoke({"text" : chunk}) for chunk in chunks]

    combined =  "\n\n".join(chunk_summaries)

    combined_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are an expert summarizer. Combine these partial summaries into a single summary in bullt points."),
            ("human", "{text}")
        ]
    )

    combined_chain = (
        combined_prompt | llm | StrOutputParser()
    )

    return combined_chain.invoke({"text" : combined})

def generate_title(transcript : str) -> str :
    llm = get_llm()

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "Write a title for the following transcript , max 8 words"),
            ("human", "{text}")
        ]
    )

    chain = prompt | llm | StrOutputParser()

    return chain.invoke({"text" : transcript[:2000]})

