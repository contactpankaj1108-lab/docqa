"""Split extracted blocks into overlapping, retrieval-sized chunks.

Boundaries follow sentences: splitting mid-clause reads badly as a citation
and splits the answer across two candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

from .extraction import Block
from .textutils import sentences


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    page: int | None
    text: str
    n_words: int


@dataclass(frozen=True)
class _Unit:
    page: int | None
    text: str
    n_words: int


def _split_units(blocks: list[Block], hard_limit: int) -> list[_Unit]:
    """Flatten blocks into sentence-sized units, breaking up runaway sentences."""
    units: list[_Unit] = []
    for block in blocks:
        for sentence in sentences(block.text):
            words = sentence.split()
            if len(words) <= hard_limit:
                units.append(_Unit(block.page, sentence, len(words)))
                continue
            # A "sentence" this long is really a table row or an unpunctuated
            # list; slice it so it can never monopolise a chunk.
            for start in range(0, len(words), hard_limit):
                piece = words[start : start + hard_limit]
                units.append(_Unit(block.page, " ".join(piece), len(piece)))
    return units


def chunk_blocks(
    blocks: list[Block],
    *,
    target_words: int = 180,
    overlap_words: int = 45,
) -> list[Chunk]:
    """Pack blocks into chunks of roughly ``target_words`` with a sliding overlap.

    The overlap keeps an answer that straddles a boundary reachable from both
    sides, which matters most for definitions and numbered lists.
    """
    target_words = max(40, target_words)
    overlap_words = max(0, min(overlap_words, target_words // 2))
    min_words = max(20, target_words // 3)

    units = _split_units(blocks, hard_limit=int(target_words * 1.5))
    if not units:
        return []

    chunks: list[Chunk] = []
    current: list[_Unit] = []
    current_words = 0

    def flush() -> list[_Unit]:
        """Emit the pending units as a chunk and return the overlap tail."""
        nonlocal current_words
        if not current:
            return []
        text = " ".join(unit.text for unit in current)
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                page=current[0].page,
                text=text,
                n_words=current_words,
            )
        )
        tail: list[_Unit] = []
        tail_words = 0
        for unit in reversed(current):
            if tail_words + unit.n_words > overlap_words:
                break
            tail.insert(0, unit)
            tail_words += unit.n_words
        current_words = tail_words
        return tail

    for unit in units:
        if current and current_words + unit.n_words > target_words and current_words >= min_words:
            current = flush()
        current.append(unit)
        current_words += unit.n_words

    if current:
        # The tail returned by the final flush is already covered by the chunk
        # it overlaps, so drop it.
        text = " ".join(unit.text for unit in current)
        if text.strip():
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    page=current[0].page,
                    text=text,
                    n_words=current_words,
                )
            )

    return chunks
