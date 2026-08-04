"""Summarization worker: LLM analysis passes + RAG chain assembly.

Owns the in-memory RAG chain registry (chains are keyed by job_id). In the
interim (pre-SQS) this is used by shared/pipeline.py; once the queue lands,
the SQS worker loop calls the same functions.
"""

from __future__ import annotations

import re
import threading

from services.summarization.summarize import summarize, generate_title
from services.summarization.extractor import (
    extract_action_items,
    extract_key_information,
    extract_questions,
)
from services.summarization.rag import build_rag_chain as _build_rag_chain

# ── RAG chain registry ─────────────────────────────────────────────────────
# Chroma + LCEL chains aren't pickleable, so chains live in-process per pod.
# On a cold pod the ask endpoint rebuilds from the stored transcript.

_rag_chains: dict[str, object] = {}
_rag_lock = threading.Lock()


def register_rag_chain(job_id: str, chain: object) -> None:
    with _rag_lock:
        _rag_chains[job_id] = chain


def get_rag_chain(job_id: str) -> object | None:
    with _rag_lock:
        return _rag_chains.get(job_id)


def drop_rag_chain(job_id: str) -> None:
    with _rag_lock:
        _rag_chains.pop(job_id, None)


# ── Title cleaning ─────────────────────────────────────────────────────────

def clean_title(raw: str) -> str:
    """Strip markdown formatting and quotes the LLM sometimes wraps titles in."""
    cleaned = re.sub(r"\*\*|__", "", raw)          # remove **bold** / __bold__
    cleaned = re.sub(r"^[\"'«‹„]+", "", cleaned)   # leading quotes
    cleaned = re.sub(r"[\"'»›‟]+$", "", cleaned)   # trailing quotes
    cleaned = re.sub(r"^#+\s*", "", cleaned)        # markdown headings
    return cleaned.strip()


# ── Analysis ───────────────────────────────────────────────────────────────

def run_analysis(transcript: str) -> dict:
    """Run the four LLM passes and return the structured results dict."""
    raw_title = generate_title(transcript)
    title = clean_title(raw_title)

    summary = summarize(transcript)
    actionables = extract_action_items(transcript)
    information = extract_key_information(transcript)
    questions = extract_questions(transcript)

    return {
        "title": title,
        "summary": summary,
        "actionables": actionables,
        "questions": questions,
        "information": information,
    }


def build_job_rag(transcript: str):
    """Build the RAG chain for a transcript (interim: shared collection)."""
    return _build_rag_chain(transcript)
