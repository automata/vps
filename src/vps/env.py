from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv, load_dotenv


def load_env() -> bool:
    """Load a local .env file without overriding existing environment variables."""
    path = find_dotenv(usecwd=True)
    if not path:
        return False
    return load_dotenv(Path(path), override=False)
