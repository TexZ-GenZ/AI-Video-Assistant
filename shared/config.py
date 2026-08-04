"""Shared app configuration helpers."""

import os


def cors_origins() -> list[str]:
    """CORS allow-list from CORS_ORIGINS (comma-separated).

    Defaults to "*" (dev). Production sets it to the Vercel origin, e.g.
    CORS_ORIGINS=https://videosense.vercel.app
    """
    raw = os.getenv("CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
