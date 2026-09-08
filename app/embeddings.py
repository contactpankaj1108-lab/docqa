"""Optional dense-embedding provider.

Off by default to keep the install small. Set DOCQA_EMBEDDINGS=true with
sentence-transformers installed and retrieval fuses it with BM25.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SentenceTransformerEmbedder:
    """Thin wrapper that returns L2-normalised vectors as plain lists."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # imported lazily

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]


def build_embedder(*, enabled: bool, model_name: str):
    """Return an embedder, or ``None`` when dense retrieval is unavailable."""
    if not enabled:
        return None
    try:
        embedder = SentenceTransformerEmbedder(model_name)
    except ImportError:
        logger.warning(
            "DOCQA_EMBEDDINGS is on but sentence-transformers is not installed; "
            "falling back to lexical retrieval."
        )
        return None
    except Exception as exc:
        logger.warning(
            "Could not load embedding model %s (%s); using lexical retrieval.", model_name, exc
        )
        return None
    logger.info("Dense retrieval enabled with %s", model_name)
    return embedder
