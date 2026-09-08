"""Tokenisation helpers shared by the indexer and the retriever."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")

# Kept short deliberately: BM25 already discounts common terms via IDF, and
# a long stop list hurts phrase-like questions.
STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those of in on at to for
    from by with without into over under again further is are was were be been
    being am do does did doing have has had having i you he she it we they me
    him her them my your his its our their as so such about above below between
    while during before after up down out off there here when where why how all
    any both each few more most other some only own same too very s t can will
    just should now what which who whom whose
    """.split()
)

_SUFFIX_RULES = (
    ("ies", "y", 3),
    ("ied", "y", 3),
    ("sses", "ss", 3),
    ("ing", "", 4),
    ("edly", "", 4),
    ("ed", "", 4),
    ("ly", "", 4),
    ("es", "", 4),
    ("s", "", 4),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9•\(\[\"'-])")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def stem(word: str) -> str:
    """Strip common inflectional suffixes.

    Not Porter - only the endings that cause misses in practice (plurals,
    gerunds, past tense). Short words are left alone to avoid over-stemming.
    """
    if len(word) <= 4:
        return word
    for suffix, replacement, min_stem in _SUFFIX_RULES:
        if word.endswith(suffix):
            stemmed = word[: -len(suffix)] + replacement
            if len(stemmed) >= min_stem:
                return stemmed
    return word


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Lowercase, de-accent, split on non-alphanumerics, then stem."""
    normalised = strip_accents(text.lower())
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(normalised):
        if not keep_stopwords and raw in STOPWORDS:
            continue
        tokens.append(stem(raw))
    return tokens


def char_ngrams(term: str, n: int = 3) -> set[str]:
    """Boundary-padded character n-grams for fuzzy term matching.

    n=3 by default: on short words trigrams keep spelling variants (0.5-0.7
    similarity) clear of unrelated words (<0.4); 4-grams collapse that gap.
    """
    padded = "$" + term + "$"
    if len(padded) <= n:
        return {padded}
    return {padded[i : i + n] for i in range(len(padded) - n + 1)}


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    return intersection / (len(a) + len(b) - intersection)


def sentences(text: str) -> Iterator[str]:
    """Split on sentence-ish boundaries without dragging in an NLP dependency."""
    buffer = text.strip()
    if not buffer:
        return
    for part in _SENTENCE_SPLIT.split(buffer):
        cleaned = part.strip()
        if cleaned:
            yield cleaned
