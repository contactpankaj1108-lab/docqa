"""HTTP-level tests against the real FastAPI app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def client(settings, monkeypatch):
    """A TestClient whose app starts against an isolated, empty index."""
    # Patch before the lifespan runs so the app builds its service in the
    # temp data directory instead of ./data.
    monkeypatch.setattr(main, "settings", settings)
    with TestClient(main.app) as test_client:
        yield test_client


def upload(client: TestClient, *names: str):
    files = [("files", (name, (SAMPLES / name).read_bytes())) for name in names]
    return client.post("/api/documents", files=files)


def test_health_and_index_page(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200
    assert "DocQA" in page.text


def test_upload_then_list_then_delete(client: TestClient) -> None:
    response = upload(client, "employee-leave-policy.txt", "it-helpdesk-faq.txt")
    assert response.status_code == 201, response.text

    body = response.json()
    assert len(body["uploaded"]) == 2
    assert body["failed"] == []
    assert all(doc["status"] == "indexed" for doc in body["uploaded"])

    listing = client.get("/api/documents").json()
    assert listing["count"] == 2

    doc_id = body["uploaded"][0]["id"]
    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["preview"], "a document should expose a text preview"

    download = client.get(f"/api/documents/{doc_id}/file")
    assert download.status_code == 200
    assert len(download.content) > 0

    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get("/api/documents").json()["count"] == 1
    assert client.get(f"/api/documents/{doc_id}").status_code == 404


def test_multiple_formats_upload_together(client: TestClient) -> None:
    response = upload(
        client,
        "information-security-policy.pdf",
        "data-science-intern-handbook.docx",
        "warehouse-safety-manual.txt",
    )
    assert response.status_code == 201
    assert len(response.json()["uploaded"]) == 3


def test_bad_file_is_reported_without_failing_the_batch(client: TestClient) -> None:
    files = [
        (
            "files",
            ("employee-leave-policy.txt", (SAMPLES / "employee-leave-policy.txt").read_bytes()),
        ),
        ("files", ("virus.exe", b"MZ\x90\x00")),
    ]
    body = client.post("/api/documents", files=files).json()

    assert len(body["uploaded"]) == 1
    assert len(body["failed"]) == 1
    assert "Unsupported file type" in body["failed"][0]["error"]


def test_ask_returns_answer_and_sources(client: TestClient) -> None:
    upload(client, "employee-leave-policy.txt")
    response = client.post(
        "/api/ask", json={"question": "How many days of annual leave are there?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"].strip()
    assert body["sources"][0]["filename"] == "employee-leave-policy.txt"
    assert body["timing_ms"]["retrieval"] >= 0


def test_ask_validates_input(client: TestClient) -> None:
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={}).status_code == 422


def test_ask_scoped_to_a_document(client: TestClient) -> None:
    body = upload(client, "employee-leave-policy.txt", "warehouse-safety-manual.txt").json()
    leave_id = next(d["id"] for d in body["uploaded"] if d["filename"].startswith("employee"))

    answer = client.post(
        "/api/ask",
        json={"question": "What PPE is mandatory?", "document_ids": [leave_id]},
    ).json()
    assert all(source["document_id"] == leave_id for source in answer["sources"])


def test_streaming_endpoint_emits_events(client: TestClient) -> None:
    upload(client, "warehouse-safety-manual.txt")
    with client.stream(
        "POST", "/api/ask/stream", json={"question": "What PPE is mandatory on the floor?"}
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[5:])
            for chunk in response.iter_lines()
            for line in [chunk]
            if line.startswith("data:")
        ]

    kinds = [event["type"] for event in events]
    assert kinds[0] == "sources"
    assert kinds[-1] == "done"


def test_stats_describe_the_index(client: TestClient) -> None:
    upload(client, "it-helpdesk-faq.txt")
    stats = client.get("/api/stats").json()

    assert stats["documents"] == 1
    assert stats["chunks"] > 0
    assert stats["generation"] in {"claude", "extractive"}


def test_unknown_document_returns_404(client: TestClient) -> None:
    assert client.get("/api/documents/does-not-exist").status_code == 404
    assert client.delete("/api/documents/does-not-exist").status_code == 404
