"""SQLite persistence for documents and their chunks.

The only durable state; the retrieval index is rebuilt from these tables at
startup.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    extension     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    pages         INTEGER,
    n_chunks      INTEGER NOT NULL DEFAULT 0,
    n_words       INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,
    error         TEXT,
    uploaded_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id        TEXT PRIMARY KEY,
    doc_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal   INTEGER NOT NULL,
    page      INTEGER,
    text      TEXT NOT NULL,
    n_words   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);
"""


@dataclass(frozen=True)
class Document:
    id: str
    filename: str
    extension: str
    size_bytes: int
    sha256: str
    stored_path: str
    pages: int | None
    n_chunks: int
    n_words: int
    status: str
    error: str | None
    uploaded_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "pages": self.pages,
            "n_chunks": self.n_chunks,
            "n_words": self.n_words,
            "status": self.status,
            "error": self.error,
            "uploaded_at": self.uploaded_at,
        }


@dataclass(frozen=True)
class StoredChunk:
    id: str
    doc_id: str
    ordinal: int
    page: int | None
    text: str
    n_words: int


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connect() as conn:
            conn.executescript(_SCHEMA)

    def _connection(self) -> sqlite3.Connection:
        """One cached connection per thread.

        Connections can't be shared across threads, and reconnecting per query
        is expensive - the PRAGMAs alone dominated retrieval latency, since one
        question reads several chunk ranges.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")  # readers do not block on a writer
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close this thread's connection (tests and shutdown)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- documents --------------------------------------------------------

    def create_document(
        self,
        *,
        doc_id: str,
        filename: str,
        extension: str,
        size_bytes: int,
        sha256: str,
        stored_path: str,
    ) -> Document:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents
                    (id, filename, extension, size_bytes, sha256, stored_path,
                     pages, n_chunks, n_words, status, error, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 0, 'processing', NULL, ?)
                """,
                (doc_id, filename, extension, size_bytes, sha256, stored_path, utcnow()),
            )
        document = self.get_document(doc_id)
        assert document is not None
        return document

    def mark_indexed(self, doc_id: str, *, pages: int | None, n_chunks: int, n_words: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE documents
                   SET status='indexed', error=NULL, pages=?, n_chunks=?, n_words=?
                 WHERE id=?
                """,
                (pages, n_chunks, n_words, doc_id),
            )

    def mark_failed(self, doc_id: str, error: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE documents SET status='failed', error=? WHERE id=?",
                (error[:2000], doc_id),
            )

    def get_document(self, doc_id: str) -> Document | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return _document_from_row(row) if row else None

    def find_by_sha256(self, sha256: str) -> Document | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE sha256=? AND status='indexed' LIMIT 1",
                (sha256,),
            ).fetchone()
        return _document_from_row(row) if row else None

    def list_documents(self) -> list[Document]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY uploaded_at DESC, filename"
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def delete_document(self, doc_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            return cursor.rowcount > 0

    # -- chunks -----------------------------------------------------------

    def insert_chunks(self, doc_id: str, chunks: list[StoredChunk]) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO chunks (id, doc_id, ordinal, page, text, n_words) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(c.id, doc_id, c.ordinal, c.page, c.text, c.n_words) for c in chunks],
            )

    def iter_chunks(self, batch_size: int = 500) -> Iterator[StoredChunk]:
        """Stream every indexed chunk, for building the in-memory index."""
        with self.connect() as conn:
            cursor = conn.execute(
                """
                SELECT c.* FROM chunks c
                  JOIN documents d ON d.id = c.doc_id
                 WHERE d.status='indexed'
                 ORDER BY c.doc_id, c.ordinal
                """
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    return
                for row in rows:
                    yield _chunk_from_row(row)

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, StoredChunk]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE id IN ({placeholders})", chunk_ids
            ).fetchall()
        return {row["id"]: _chunk_from_row(row) for row in rows}

    def chunks_in_range(self, doc_id: str, start: int, end: int) -> list[StoredChunk]:
        """Fetch a contiguous ordinal range in one query (context expansion)."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chunks
                 WHERE doc_id=? AND ordinal BETWEEN ? AND ?
                 ORDER BY ordinal
                """,
                (doc_id, start, end),
            ).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def document_chunks(self, doc_id: str, limit: int | None = None) -> list[StoredChunk]:
        sql = "SELECT * FROM chunks WHERE doc_id=? ORDER BY ordinal"
        params: list = [doc_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def stats(self) -> dict:
        with self.connect() as conn:
            docs = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(n_words), 0) AS w "
                "FROM documents WHERE status='indexed'"
            ).fetchone()
            chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return {"documents": docs["n"], "words": docs["w"], "chunks": chunks["n"]}


def _document_from_row(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        filename=row["filename"],
        extension=row["extension"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        stored_path=row["stored_path"],
        pages=row["pages"],
        n_chunks=row["n_chunks"],
        n_words=row["n_words"],
        status=row["status"],
        error=row["error"],
        uploaded_at=row["uploaded_at"],
    )


def _chunk_from_row(row: sqlite3.Row) -> StoredChunk:
    return StoredChunk(
        id=row["id"],
        doc_id=row["doc_id"],
        ordinal=row["ordinal"],
        page=row["page"],
        text=row["text"],
        n_words=row["n_words"],
    )
