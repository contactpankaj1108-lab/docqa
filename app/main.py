"""FastAPI application: document management and question answering."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .llm import GenerationError
from .service import DocQAService, IngestError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("docqa")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_service: DocQAService | None = None


def get_service() -> DocQAService:
    if _service is None:  # pragma: no cover - only before startup
        raise HTTPException(status_code=503, detail="Service is still starting.")
    return _service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service
    _service = DocQAService(settings)
    stats = _service.stats()
    logger.info(
        "Ready | %s documents, %s chunks | answers: %s",
        stats["documents"],
        stats["chunks"],
        stats["generation"],
    )
    if not _service.generator.available:
        logger.warning(
            "No Anthropic credentials found - answers will be extractive. "
            "Set ANTHROPIC_API_KEY for generated answers."
        )
    yield
    _service = None


app = FastAPI(
    title="DocQA",
    version="1.0.0",
    description="Upload documents, ask questions, get cited answers.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] | None = Field(
        default=None, description="Restrict the search to these documents."
    )
    history: list[Turn] | None = Field(default=None, description="Prior turns, oldest first.")
    top_k: int | None = Field(default=None, ge=1, le=20)


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


@app.post("/api/documents", status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(..., description="One or more PDF, TXT or DOCX files"),
    service: DocQAService = Depends(get_service),
) -> dict:
    """Upload and index one or more documents.

    Each file is reported independently: one bad file does not fail the batch.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files were provided.")

    uploaded: list[dict] = []
    failed: list[dict] = []

    for upload in files:
        try:
            data = await upload.read()
            # Parsing and indexing are CPU-bound; keep the event loop free.
            document, duplicate = await run_in_threadpool(
                service.ingest, upload.filename or "untitled", data
            )
        except IngestError as exc:
            failed.append({"filename": upload.filename, "error": str(exc)})
            continue
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected failure ingesting %s", upload.filename)
            failed.append({"filename": upload.filename, "error": f"Unexpected error: {exc}"})
            continue
        finally:
            await upload.close()

        uploaded.append({**document.to_dict(), "duplicate": duplicate})

    if not uploaded and failed:
        raise HTTPException(status_code=400, detail={"uploaded": [], "failed": failed})
    return {"uploaded": uploaded, "failed": failed}


@app.get("/api/documents")
def list_documents(service: DocQAService = Depends(get_service)) -> dict:
    documents = [document.to_dict() for document in service.list_documents()]
    return {"documents": documents, "count": len(documents)}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, service: DocQAService = Depends(get_service)) -> dict:
    document = service.get_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {**document.to_dict(), "preview": service.document_preview(doc_id)}


@app.get("/api/documents/{doc_id}/file")
def download_document(doc_id: str, service: DocQAService = Depends(get_service)) -> FileResponse:
    document = service.get_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    path = Path(document.stored_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="The stored file is no longer available.")
    return FileResponse(path, filename=document.filename)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, service: DocQAService = Depends(get_service)) -> dict:
    if not service.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"deleted": doc_id}


# --------------------------------------------------------------------------
# Question answering
# --------------------------------------------------------------------------


@app.post("/api/ask")
def ask(payload: AskRequest, service: DocQAService = Depends(get_service)) -> dict:
    """Answer a question over the indexed documents."""
    try:
        return service.ask(
            payload.question,
            doc_ids=payload.document_ids,
            history=[turn.model_dump() for turn in payload.history] if payload.history else None,
            top_k=payload.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/ask/stream")
def ask_stream(
    payload: AskRequest, service: DocQAService = Depends(get_service)
) -> StreamingResponse:
    """Same as /api/ask, streamed as server-sent events."""

    def events() -> Iterator[str]:
        for event in service.ask_stream(
            payload.question,
            doc_ids=payload.document_ids,
            history=[turn.model_dump() for turn in payload.history] if payload.history else None,
            top_k=payload.top_k,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------


@app.get("/api/stats")
def stats(service: DocQAService = Depends(get_service)) -> dict:
    return service.stats()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "indexed": _service is not None}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request) -> HTMLResponse:
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():  # pragma: no cover - only if web assets are missing
        return HTMLResponse("<h1>DocQA</h1><p>API is running. See <a href='/docs'>/docs</a>.</p>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
