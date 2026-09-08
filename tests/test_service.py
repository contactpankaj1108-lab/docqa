"""End-to-end pipeline tests over the sample corpus.

These run without API credentials: answering degrades to the extractive path,
but retrieval - the part that decides whether the right document is found - is
exercised in full.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.service import DocQAService, IngestError

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

# A small retrieval eval: question -> the document that should be cited first.
RETRIEVAL_CASES = [
    (
        "What are the responsibilities of a data science intern?",
        "data-science-intern-handbook.docx",
    ),
    ("Who does an intern report to?", "data-science-intern-handbook.docx"),
    ("How quickly must a security incident be reported?", "information-security-policy.pdf"),
    ("What are the password requirements?", "information-security-policy.pdf"),
    ("How many days of annual leave do employees get?", "employee-leave-policy.txt"),
    ("Can I carry unused leave into next year?", "employee-leave-policy.txt"),
    ("When am I eligible for a replacement laptop?", "it-helpdesk-faq.txt"),
    ("What PPE is mandatory on the operational floor?", "warehouse-safety-manual.txt"),
    ("What is the site speed limit for forklifts?", "warehouse-safety-manual.txt"),
]


def test_ingests_every_sample_format(service: DocQAService) -> None:
    for path in sorted(SAMPLES.iterdir()):
        document, duplicate = service.ingest(path.name, path.read_bytes())
        assert document.status == "indexed", document.error
        assert document.n_chunks > 0
        assert duplicate is False

    stats = service.stats()
    assert stats["documents"] == 5
    assert stats["chunks"] > 15


def test_identical_uploads_are_deduplicated(service: DocQAService) -> None:
    path = SAMPLES / "employee-leave-policy.txt"
    first, was_duplicate = service.ingest(path.name, path.read_bytes())
    second, is_duplicate = service.ingest(path.name, path.read_bytes())

    assert was_duplicate is False
    assert is_duplicate is True
    assert second.id == first.id
    assert service.stats()["documents"] == 1


@pytest.mark.parametrize("question,expected", RETRIEVAL_CASES)
def test_expected_document_is_retrieved(seeded: DocQAService, question: str, expected: str) -> None:
    """The document holding the answer must reach the model's context."""
    blocks = seeded.retrieve(question, doc_ids=None, top_k=6)
    assert blocks, "no passages retrieved"
    assert expected in [block.filename for block in blocks[:3]]


def test_top1_retrieval_accuracy(seeded: DocQAService) -> None:
    """Rank-1 accuracy over the eval set.

    Not every case is winnable by lexical ranking alone - "What are the
    password requirements?" legitimately matches the helpdesk FAQ's password
    section as well as the security policy - so this asserts a rate, and the
    per-case test above guarantees the right document is still in context.
    """
    correct = [
        seeded.retrieve(question, doc_ids=None, top_k=6)[0].filename == expected
        for question, expected in RETRIEVAL_CASES
    ]
    accuracy = sum(correct) / len(correct)
    assert accuracy >= 0.85, "top-1 accuracy dropped to %.0f%%" % (accuracy * 100)


def test_answer_carries_grounded_sources(seeded: DocQAService) -> None:
    result = seeded.ask("What are the responsibilities of a data science intern?")

    assert result["sources"], "an answer must carry its sources"
    assert result["sources"][0]["filename"] == "data-science-intern-handbook.docx"
    assert result["answer"].strip()
    assert result["mode"] in {"generated", "extractive"}
    assert result["timing_ms"]["retrieval"] >= 0


def test_scoping_restricts_the_search(seeded: DocQAService) -> None:
    leave = next(d for d in seeded.list_documents() if d.filename.startswith("employee-leave"))
    result = seeded.ask(
        "What are the responsibilities of a data science intern?", doc_ids=[leave.id]
    )

    assert all(source["document_id"] == leave.id for source in result["sources"])


def test_unanswerable_question_is_reported_as_such(seeded: DocQAService) -> None:
    result = seeded.ask("How do I bake a sourdough loaf?")
    assert result["mode"] == "no_match"
    assert result["sources"] == []


def test_empty_question_is_rejected(seeded: DocQAService) -> None:
    with pytest.raises(ValueError):
        seeded.ask("   ")


def test_deleting_a_document_removes_it_from_answers(seeded: DocQAService) -> None:
    handbook = next(d for d in seeded.list_documents() if d.filename.startswith("data-science"))
    stored = Path(handbook.stored_path)

    assert seeded.delete_document(handbook.id) is True
    assert seeded.get_document(handbook.id) is None
    assert stored.exists() is False

    blocks = seeded.retrieve("responsibilities of a data science intern", doc_ids=None, top_k=6)
    assert all(block.doc_id != handbook.id for block in blocks)


def test_index_survives_a_restart(seeded: DocQAService) -> None:
    """A new service instance must rebuild the index from SQLite alone."""
    before = seeded.stats()
    restarted = DocQAService(seeded.settings)

    assert restarted.stats()["chunks"] == before["chunks"]
    blocks = restarted.retrieve(
        "how quickly must a security incident be reported", doc_ids=None, top_k=4
    )
    assert blocks[0].filename == "information-security-policy.pdf"


def test_rejects_unsupported_and_empty_uploads(service: DocQAService) -> None:
    with pytest.raises(IngestError, match="Unsupported file type"):
        service.ingest("photo.png", b"\x89PNG\r\n")
    with pytest.raises(IngestError, match="empty"):
        service.ingest("blank.txt", b"")


def test_rejects_oversized_uploads(service: DocQAService) -> None:
    oversized = b"x" * (service.settings.max_upload_bytes + 1)
    with pytest.raises(IngestError, match="limit is"):
        service.ingest("huge.txt", oversized)


def test_path_traversal_in_a_filename_is_neutralised(service: DocQAService) -> None:
    document, _ = service.ingest(
        "../../etc/passwd.txt", b"root:x:0:0 some content here for indexing"
    )
    assert document.filename == "passwd.txt"
    assert ".." not in document.stored_path


def test_context_blocks_do_not_duplicate_overlapping_text(seeded: DocQAService) -> None:
    blocks = seeded.retrieve("annual leave carry over", doc_ids=None, top_k=6)
    for block in blocks:
        sentences = [s.strip() for s in block.text.split(".") if len(s.strip()) > 40]
        assert len(sentences) == len(set(sentences)), "overlap was not de-duplicated"


def test_streaming_emits_sources_then_text(seeded: DocQAService) -> None:
    events = list(seeded.ask_stream("How many days of annual leave do employees get?"))
    kinds = [event["type"] for event in events]

    assert kinds[0] == "sources"
    assert "delta" in kinds
    assert kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "delta").strip()
