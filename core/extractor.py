# Actionablesitems , decision , questions

from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda , RunnablePassthrough
from dotenv import load_dotenv
import os

load_dotenv()

def get_llm():
    return ChatMistralAI(
        model="mistral-small-2603",
        temperature=0.3
    )

def build_chain(system_prompt : str):
    llm = get_llm()

    return (
        RunnablePassthrough() |
        RunnableLambda(
            lambda x : {"text" : x}
        ) |
        ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{text}")
            ]
        ) |
        llm |
        StrOutputParser()
    )

def extract_action_items(transcript:str) -> str:
    chain = build_chain(
        "You are an expert video analyst . From the provided transcript extract all action items . "
        "For each provide - Task Description , format as a numbered list "
        " If no action items found say no action items found"
    )

    return chain.invoke(transcript)

def extract_key_information(transcript: str) -> str:
    chain = build_chain(
        "You are an expert video analyst. From the provided transcript extract the key information. "
        "Include the main topics, important facts, names, dates, numbers, decisions, and conclusions. "
        "Format the output as a concise numbered list."
    )

    return chain.invoke(transcript)

def extract_questions(transcript: str) -> str:
    chain = build_chain(
        "You are an expert video analyst. From the provided transcript extract all questions that are asked, "
        "whether they are explicit or rhetorical. Preserve the original wording as much as possible. "
        "Format the output as a numbered list. If no questions are found, say 'No questions found'."
    )

    return chain.invoke(transcript)