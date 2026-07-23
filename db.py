"""
SQLite job store for the AI Video Assistant.

All reads/writes are serialized through a module-level lock so the background
worker thread and the FastAPI event loop can safely share the same connection.
"""

import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = "jobs.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create the jobs table if it doesn't exist. Call once at startup."""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id      TEXT PRIMARY KEY,
                    source      TEXT NOT NULL,
                    language    TEXT NOT NULL DEFAULT 'english',
                    status      TEXT NOT NULL DEFAULT 'processing',
                    progress    TEXT,
                    error       TEXT,
                    title       TEXT,
                    summary     TEXT,
                    actionables TEXT,
                    questions   TEXT,
                    information TEXT,
                    transcript  TEXT,
                    created_at  TEXT NOT NULL
                )
                """
            )
            # Add transcript column to existing databases that don't have it yet
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN transcript TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
            conn.commit()
        finally:
            conn.close()


# ── write helpers ──────────────────────────────────────────────────────────


def create_job(job_id: str, source: str, language: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO jobs (job_id, source, language, status, created_at)
                VALUES (?, ?, ?, 'processing', ?)
                """,
                (job_id, source, language, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()


def update_progress(job_id: str, progress: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE jobs SET progress = ? WHERE job_id = ?",
                (progress, job_id),
            )
            conn.commit()
        finally:
            conn.close()


def set_done(
    job_id: str,
    title: str,
    summary: str,
    actionables: str,
    questions: str,
    information: str,
    transcript: str = "",
) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE jobs SET
                    status      = 'done',
                    progress    = NULL,
                    error       = NULL,
                    title       = ?,
                    summary     = ?,
                    actionables = ?,
                    questions   = ?,
                    information = ?,
                    transcript  = ?
                WHERE job_id = ?
                """,
                (title, summary, actionables, questions, information, transcript, job_id),
            )
            conn.commit()
        finally:
            conn.close()


def set_error(job_id: str, error: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE jobs SET status = 'error', error = ?, progress = NULL WHERE job_id = ?",
                (error, job_id),
            )
            conn.commit()
        finally:
            conn.close()


# ── read helpers ───────────────────────────────────────────────────────────


def get_job(job_id: str) -> dict | None:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_jobs() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT job_id, title, source, status, created_at FROM jobs ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_transcript(job_id: str) -> str | None:
    """Return the raw transcript for a job, or None if not found."""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT transcript FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return row["transcript"] if row else None
        finally:
            conn.close()


def delete_job(job_id: str) -> bool:
    """Delete a job and return True if it existed."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
