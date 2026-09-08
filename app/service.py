"""Ingestion and question answering.

Kept free of FastAPI types so the pipeline can be driven from a script or a
test without a running server.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .chunking import chunk_blocks
from .config import Settings
from .embeddings import build_embedder
from .extraction import SUPPORTED_EXTENSIONS, ExtractionError, extract
from .llm import AnswerGenerator, GenerationError
from .retrieval import ScoredChunk, SearchIndex
from .store import Document, Store, StoredChunk

logger = logging.getLogger(__name__)

MAX_BLOCK_CHARS = 6000
SNIPPET_CHARS = 260
NO_MATCH_ANSWER = (
    "I could not find anything about that in the uploaded documents. "
    "Try rephrasing the question, or upload a document that covers the topic."
)


class IngestError(RuntimeError):
    """Raised when an upload cannot be accepted or indexed."""


@dataclass
class ContextBlock:
    doc_id: str
    filename: str
    page: int | None
    text: str
    score: float
    chunk_ids: list[str]

    def to_source(self, number: int, cited: bool) -> dict:
        snippet = self.text.strip()
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "..."
        return {
            "n": number,
            "document_id": self.doc_id,
            "filename": self.filename,
            "page": self.page,
            "snippet": snippet,
            "score": round(self.score, 4),
            "cited": cited,
        }


class DocQAService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.store = Store(settings.db_path)
        self.embedder = build_embedder(
            enabled=settings.embeddings_enabled, model_name=settings.embedding_model
        )
        self.index = SearchIndex(embedder=self.embedder)
        self.generator = AnswerGenerator(
            model=settings.model,
            max_tokens=settings.max_tokens,
            effort=settings.answer_effort,
            server_fallback=settings.server_side_fallback,
        )
        self._load_index()

    def _load_index(self) -> None:
        """Rebuild the in-memory index from SQLite on boot."""
        started = time.perf_counter()
        pending: dict[str, list[tuple[str, str]]] = {}
        for chunk in self.store.iter_chunks():
            pending.setdefault(chunk.doc_id, []).append((chunk.id, chunk.text))
        for doc_id, chunks in pending.items():
            self.index.add_chunks(doc_id, chunks)
        stats = self.index.stats()
        if stats.chunks:
            logger.info(
                "Loaded %d chunks from %d documents in %.2fs",
                stats.chunks,
                stats.documents,
                time.perf_counter() - started,
            )

    # -- ingestion --------------------------------------------------------

    def ingest(self, filename: str, data: bytes) -> tuple[Document, bool]:
        """Store, parse, chunk and index one uploaded file.

        Returns the document and whether it was a duplicate of one already
        indexed (same bytes), in which case nothing is re-processed.
        """
        safe_name = _sanitise_filename(filename)
        extension = Path(safe_name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise IngestError(
                "Unsupported file type '{}'. Supported: {}.".format(
                    extension or "(none)", ", ".join(sorted(SUPPORTED_EXTENSIONS))
                )
            )
        if not data:
            raise IngestError("The file is empty.")
        if len(data) > self.settings.max_upload_bytes:
            size_mb = len(data) / 1024 / 1024
            raise IngestError(
                f"File is {size_mb:.1f} MB; the limit is {self.settings.max_upload_mb} MB."
            )

        digest = hashlib.sha256(data).hexdigest()
        existing = self.store.find_by_sha256(digest)
        if existing is not None and self.index.has_document(existing.id):
            return existing, True

        doc_id = uuid.uuid4().hex
        # Short on-disk name: the original filename is kept in the database, and
        # a long random one can push the path past Windows' MAX_PATH limit.
        stored_path = self.settings.upload_dir / (f"{doc_id[:12]}{extension}")
        stored_path.write_bytes(data)

        self.store.create_document(
            doc_id=doc_id,
            filename=safe_name,
            extension=extension,
            size_bytes=len(data),
            sha256=digest,
            stored_path=str(stored_path),
        )

        try:
            blocks = extract(stored_path, extension=extension)
            chunks = chunk_blocks(
                blocks,
                target_words=self.settings.chunk_words,
                overlap_words=self.settings.chunk_overlap_words,
            )
            if not chunks:
                raise ExtractionError("No text could be extracted from the document.")

            stored_chunks = [
                StoredChunk(
                    id=f"{doc_id}:{chunk.ordinal}",
                    doc_id=doc_id,
                    ordinal=chunk.ordinal,
                    page=chunk.page,
                    text=chunk.text,
                    n_words=chunk.n_words,
                )
                for chunk in chunks
            ]
            self.store.insert_chunks(doc_id, stored_chunks)

            pages = max((b.page or 0 for b in blocks), default=0) or None
            self.store.mark_indexed(
                doc_id,
                pages=pages,
                n_chunks=len(stored_chunks),
                n_words=sum(c.n_words for c in stored_chunks),
            )
            self.index.add_chunks(doc_id, [(c.id, c.text) for c in stored_chunks])
        except ExtractionError as exc:
            self.store.mark_failed(doc_id, str(exc))
            raise IngestError(str(exc)) from exc
        except Exception as exc:
            logger.exception("Indexing failed for %s", safe_name)
            self.store.mark_failed(doc_id, str(exc))
            raise IngestError(f"Indexing failed: {exc}") from exc

        updated = self.store.get_document(doc_id)
        assert updated is not None
        return updated, False

    def delete_document(self, doc_id: str) -> bool:
        document = self.store.get_document(doc_id)
        if document is None:
            return False
        self.index.remove_document(doc_id)
        self.store.delete_document(doc_id)
        try:
            Path(document.stored_path).unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - filesystem edge case
            logger.warning("Could not delete %s: %s", document.stored_path, exc)
        return True

    def list_documents(self) -> list[Document]:
        return self.store.list_documents()

    def get_document(self, doc_id: str) -> Document | None:
        return self.store.get_document(doc_id)

    def document_preview(self, doc_id: str, max_chunks: int = 12) -> list[dict]:
        return [
            {"ordinal": chunk.ordinal, "page": chunk.page, "text": chunk.text}
            for chunk in self.store.document_chunks(doc_id, limit=max_chunks)
        ]

    def stats(self) -> dict:
        index_stats = self.index.stats()
        return {
            **self.store.stats(),
            "vocabulary": index_stats.vocabulary,
            "dense_retrieval": index_stats.dense,
            "generation": "claude" if self.generator.available else "extractive",
            "model": self.settings.model if self.generator.available else None,
        }

    # -- retrieval --------------------------------------------------------

    def retrieve(self, query: str, *, doc_ids: list[str] | None, top_k: int) -> list[ContextBlock]:
        candidates = self.index.search(query, limit=self.settings.candidate_k, doc_ids=doc_ids)
        if not candidates:
            return []
        selected = self.index.diversify(candidates, top_k=top_k, lambda_=self.settings.mmr_lambda)
        return self._build_blocks(selected)

    def _build_blocks(self, selected: list[ScoredChunk]) -> list[ContextBlock]:
        """Widen each hit with its neighbours, merging overlapping ranges.

        A 180-word chunk often clips the sentence that qualifies the answer.
        Merging first stops adjacent hits from sending the same text twice.
        """
        window = self.settings.neighbour_window
        by_doc: dict[str, list[ScoredChunk]] = {}
        for hit in selected:
            by_doc.setdefault(hit.doc_id, []).append(hit)

        documents = {doc_id: self.store.get_document(doc_id) for doc_id in by_doc}
        blocks: list[ContextBlock] = []

        for doc_id, hits in by_doc.items():
            document = documents.get(doc_id)
            if document is None:
                continue
            ranges: list[tuple[int, int, float, list[str]]] = []
            for hit in sorted(hits, key=lambda h: _ordinal_of(h.chunk_id)):
                ordinal = _ordinal_of(hit.chunk_id)
                start, end = max(0, ordinal - window), ordinal + window
                if ranges and start <= ranges[-1][1] + 1:
                    previous = ranges[-1]
                    ranges[-1] = (
                        previous[0],
                        max(previous[1], end),
                        max(previous[2], hit.score),
                        previous[3] + [hit.chunk_id],
                    )
                else:
                    ranges.append((start, end, hit.score, [hit.chunk_id]))

            for start, end, score, chunk_ids in ranges:
                pieces: list[StoredChunk] = self.store.chunks_in_range(doc_id, start, end)
                if not pieces:
                    continue
                text = _join_without_overlap([piece.text for piece in pieces])[:MAX_BLOCK_CHARS]
                blocks.append(
                    ContextBlock(
                        doc_id=doc_id,
                        filename=document.filename,
                        page=pieces[0].page,
                        text=text,
                        score=score,
                        chunk_ids=chunk_ids,
                    )
                )

        blocks.sort(key=lambda block: block.score, reverse=True)
        return blocks

    # -- question answering ------------------------------------------------

    def ask(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        history: list[dict] | None = None,
        top_k: int | None = None,
    ) -> dict:
        question = (question or "").strip()
        if not question:
            raise ValueError("Question must not be empty.")

        top_k = top_k or self.settings.top_k
        started = time.perf_counter()
        search_query = self.generator.condense(question, history or [])
        blocks = self.retrieve(search_query, doc_ids=doc_ids, top_k=top_k)
        retrieval_ms = (time.perf_counter() - started) * 1000

        if not blocks:
            return {
                "answer": NO_MATCH_ANSWER,
                "sources": [],
                "mode": "no_match",
                "model": None,
                "query_used": search_query,
                "timing_ms": {"retrieval": round(retrieval_ms, 1), "generation": 0.0},
            }

        payload = [_block_payload(block) for block in blocks]
        generation_started = time.perf_counter()
        result = self.generator.answer(question, payload, history)
        generation_ms = (time.perf_counter() - generation_started) * 1000

        return {
            "answer": result.text,
            "sources": _sources(blocks, result.cited),
            "mode": result.mode,
            "model": result.model,
            "warning": result.warning,
            "usage": result.usage,
            "query_used": search_query,
            "timing_ms": {
                "retrieval": round(retrieval_ms, 1),
                "generation": round(generation_ms, 1),
            },
        }

    def ask_stream(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        history: list[dict] | None = None,
        top_k: int | None = None,
    ) -> Iterator[dict]:
        """Yield events for the streaming endpoint: sources, then text deltas."""
        question = (question or "").strip()
        if not question:
            yield {"type": "error", "message": "Question must not be empty."}
            return

        top_k = top_k or self.settings.top_k
        started = time.perf_counter()
        try:
            search_query = self.generator.condense(question, history or [])
            blocks = self.retrieve(search_query, doc_ids=doc_ids, top_k=top_k)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Retrieval failed")
            yield {"type": "error", "message": f"Retrieval failed: {exc}"}
            return
        retrieval_ms = (time.perf_counter() - started) * 1000

        if not blocks:
            yield {"type": "sources", "sources": [], "query_used": search_query}
            yield {"type": "delta", "text": NO_MATCH_ANSWER}
            yield {
                "type": "done",
                "mode": "no_match",
                "timing_ms": {"retrieval": round(retrieval_ms, 1)},
            }
            return

        yield {
            "type": "sources",
            "sources": _sources(blocks, cited=[]),
            "query_used": search_query,
        }

        payload = [_block_payload(block) for block in blocks]
        collected: list[str] = []
        try:
            for delta in self.generator.answer_stream(question, payload, history):
                collected.append(delta)
                yield {"type": "delta", "text": delta}
        except GenerationError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        answer_text = "".join(collected)
        from .llm import parse_citations

        yield {
            "type": "done",
            "mode": "generated" if self.generator.available else "extractive",
            "model": self.settings.model if self.generator.available else None,
            "sources": _sources(blocks, parse_citations(answer_text, len(blocks))),
            "timing_ms": {
                "retrieval": round(retrieval_ms, 1),
                "total": round((time.perf_counter() - started) * 1000, 1),
            },
        }


def _block_payload(block: ContextBlock) -> dict:
    return {"filename": block.filename, "page": block.page, "text": block.text}


def _sources(blocks: list[ContextBlock], cited: list[int]) -> list[dict]:
    cited_set = set(cited)
    return [
        block.to_source(index, index in cited_set) for index, block in enumerate(blocks, start=1)
    ]


def _ordinal_of(chunk_id: str) -> int:
    try:
        return int(chunk_id.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def _join_without_overlap(pieces: list[str]) -> str:
    """Concatenate neighbouring chunks, dropping the text they share at the seam."""
    if not pieces:
        return ""
    merged = pieces[0]
    for piece in pieces[1:]:
        words = piece.split()
        overlap = 0
        for size in range(min(len(words), 60), 4, -1):
            if merged.endswith(" ".join(words[:size])):
                overlap = size
                break
        merged = merged + " " + " ".join(words[overlap:]) if overlap < len(words) else merged
    return merged.strip()


def _sanitise_filename(filename: str) -> str:
    """Keep the display name readable while refusing path traversal."""
    name = Path(filename or "").name
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(". ")
    return name[:200] or "untitled"
