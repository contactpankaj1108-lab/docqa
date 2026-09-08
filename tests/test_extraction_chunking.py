from __future__ import annotations

from pathlib import Path

import pytest

from app.chunking import chunk_blocks
from app.extraction import Block, ExtractionError, extract

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.mark.parametrize(
    "filename,expect_pages",
    [
        ("information-security-policy.pdf", True),
        ("data-science-intern-handbook.docx", False),
        ("employee-leave-policy.txt", False),
    ],
)
def test_extracts_every_supported_format(filename: str, expect_pages: bool) -> None:
    blocks = extract(SAMPLES / filename)
    assert blocks, "expected at least one block"
    assert all(block.text.strip() for block in blocks)
    if expect_pages:
        assert all(block.page and block.page >= 1 for block in blocks)


def test_pdf_page_numbers_are_sequential() -> None:
    blocks = extract(SAMPLES / "information-security-policy.pdf")
    pages = sorted({block.page for block in blocks})
    assert pages == list(range(1, len(pages) + 1))


def test_rejects_unsupported_extensions(tmp_path: Path) -> None:
    path = tmp_path / "notes.rtf"
    path.write_bytes(b"hello")
    with pytest.raises(ExtractionError, match="Unsupported file type"):
        extract(path)


def test_legacy_doc_gets_an_actionable_message(tmp_path: Path) -> None:
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(ExtractionError, match="save as .docx"):
        extract(path)


def test_hyphenated_line_breaks_are_repaired(tmp_path: Path) -> None:
    path = tmp_path / "wrapped.txt"
    path.write_text("The recovery time objec-\ntive is four hours.", encoding="utf-8")
    assert "objective" in extract(path)[0].text


def test_chunks_respect_target_size_and_overlap() -> None:
    # Capitalised sentences, because the splitter deliberately only breaks
    # where a real sentence starts.
    text = " ".join(f"Sentence {i} covers word{i} through word{i + 11}." for i in range(100))
    chunks = chunk_blocks([Block(page=1, text=text)], target_words=100, overlap_words=25)

    assert len(chunks) > 5
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    # Sentence-aligned packing overshoots slightly; it must not run away.
    assert all(chunk.n_words <= 120 for chunk in chunks)

    first_words = set(chunks[0].text.split())
    second_words = set(chunks[1].text.split())
    assert first_words & second_words, "consecutive chunks should overlap"


def test_pages_are_carried_onto_chunks() -> None:
    blocks = [
        Block(page=3, text="Alpha beta gamma delta."),
        Block(page=4, text="Epsilon zeta eta."),
    ]
    chunks = chunk_blocks(blocks, target_words=100, overlap_words=10)
    assert chunks[0].page == 3


def test_oversized_sentence_is_split() -> None:
    monster = " ".join(f"token{i}" for i in range(600))
    chunks = chunk_blocks([Block(page=None, text=monster)], target_words=100, overlap_words=20)
    assert len(chunks) > 1
    assert all(chunk.n_words <= 160 for chunk in chunks)


def test_empty_input_produces_no_chunks() -> None:
    assert chunk_blocks([], target_words=100, overlap_words=20) == []
