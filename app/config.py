"""Runtime configuration, read once from the environment.

Every knob has a working default so the app runs with zero configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- storage ---------------------------------------------------------
    data_dir: Path = field(default_factory=lambda: Path(_env_str("DOCQA_DATA_DIR", "./data")))
    max_upload_mb: int = field(default_factory=lambda: _env_int("DOCQA_MAX_UPLOAD_MB", 25))

    # --- chunking --------------------------------------------------------
    chunk_words: int = field(default_factory=lambda: _env_int("DOCQA_CHUNK_WORDS", 180))
    chunk_overlap_words: int = field(default_factory=lambda: _env_int("DOCQA_CHUNK_OVERLAP", 45))

    # --- retrieval -------------------------------------------------------
    candidate_k: int = field(default_factory=lambda: _env_int("DOCQA_CANDIDATE_K", 40))
    top_k: int = field(default_factory=lambda: _env_int("DOCQA_TOP_K", 6))
    mmr_lambda: float = 0.7
    neighbour_window: int = field(default_factory=lambda: _env_int("DOCQA_NEIGHBOUR_WINDOW", 1))
    embeddings_enabled: bool = field(default_factory=lambda: _env_bool("DOCQA_EMBEDDINGS", False))
    embedding_model: str = field(
        default_factory=lambda: _env_str(
            "DOCQA_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )

    # --- generation ------------------------------------------------------
    model: str = field(default_factory=lambda: _env_str("DOCQA_MODEL", "claude-opus-5"))
    answer_effort: str = field(default_factory=lambda: _env_str("DOCQA_EFFORT", "medium"))
    max_tokens: int = field(default_factory=lambda: _env_int("DOCQA_MAX_TOKENS", 4000))
    server_side_fallback: bool = field(
        default_factory=lambda: _env_bool("DOCQA_SERVER_FALLBACK", True)
    )

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "docqa.sqlite3"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
