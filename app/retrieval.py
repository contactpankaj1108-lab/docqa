"""Hybrid retrieval: BM25 over an incremental inverted index, fuzzy term
expansion, optional dense vectors fused with RRF, and MMR diversification.

Query cost tracks the number of chunks containing the query terms rather than
corpus size, so adding documents doesn't slow down unrelated questions.

Fuzzy expansion runs off a character n-gram map over the vocabulary (orders of
magnitude smaller than the corpus) and covers "authorise"/"authorize" style
mismatches that a plain keyword index misses.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from .textutils import char_ngrams, jaccard, tokenize

BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60
FUZZY_MIN_SIMILARITY = 0.45
FUZZY_MAX_EXPANSIONS = 3
FUZZY_WEIGHT = 0.45
# Queries with more content words than this must match at least two of them.
MIN_TERM_MATCH_THRESHOLD = 2


@dataclass
class ScoredChunk:
    chunk_id: str
    doc_id: str
    score: float


@dataclass
class IndexStats:
    chunks: int
    documents: int
    vocabulary: int
    dense: bool


class SearchIndex:
    """In-memory hybrid index. All mutations and reads are lock-guarded."""

    def __init__(self, embedder=None) -> None:
        self._lock = threading.RLock()
        self._embedder = embedder

        self._postings: dict[str, dict[str, int]] = {}
        self._gram_index: dict[str, set[str]] = {}
        self._chunk_terms: dict[str, set[str]] = {}
        self._chunk_len: dict[str, int] = {}
        self._chunk_doc: dict[str, str] = {}
        self._doc_chunks: dict[str, list[str]] = {}
        self._total_len = 0

        self._vectors: dict[str, list[float]] = {}

    # -- lifecycle --------------------------------------------------------

    def stats(self) -> IndexStats:
        with self._lock:
            return IndexStats(
                chunks=len(self._chunk_len),
                documents=len(self._doc_chunks),
                vocabulary=len(self._postings),
                dense=bool(self._vectors),
            )

    def has_document(self, doc_id: str) -> bool:
        with self._lock:
            return doc_id in self._doc_chunks

    def add_chunks(self, doc_id: str, chunks: list[tuple[str, str]]) -> None:
        """Add ``(chunk_id, text)`` pairs for one document.

        Incremental: an upload only touches postings for terms it actually uses.
        """
        vectors: list[list[float]] | None = None
        if self._embedder is not None and chunks:
            try:
                vectors = self._embedder.encode([text for _, text in chunks])
            except Exception:
                vectors = None

        with self._lock:
            bucket = self._doc_chunks.setdefault(doc_id, [])
            for position, (chunk_id, text) in enumerate(chunks):
                tokens = tokenize(text)
                if not tokens:
                    continue
                counts: dict[str, int] = {}
                for token in tokens:
                    counts[token] = counts.get(token, 0) + 1

                for term, tf in counts.items():
                    postings = self._postings.get(term)
                    if postings is None:
                        postings = {}
                        self._postings[term] = postings
                        for gram in char_ngrams(term):
                            self._gram_index.setdefault(gram, set()).add(term)
                    postings[chunk_id] = tf

                self._chunk_terms[chunk_id] = set(counts)
                self._chunk_len[chunk_id] = len(tokens)
                self._chunk_doc[chunk_id] = doc_id
                self._total_len += len(tokens)
                bucket.append(chunk_id)

                if vectors is not None and position < len(vectors):
                    self._vectors[chunk_id] = vectors[position]

    def remove_document(self, doc_id: str) -> None:
        with self._lock:
            for chunk_id in self._doc_chunks.pop(doc_id, []):
                for term in self._chunk_terms.pop(chunk_id, ()):  # noqa: B007
                    postings = self._postings.get(term)
                    if postings is None:
                        continue
                    postings.pop(chunk_id, None)
                    if not postings:
                        del self._postings[term]
                        for gram in char_ngrams(term):
                            holders = self._gram_index.get(gram)
                            if holders is not None:
                                holders.discard(term)
                                if not holders:
                                    del self._gram_index[gram]
                self._total_len -= self._chunk_len.pop(chunk_id, 0)
                self._chunk_doc.pop(chunk_id, None)
                self._vectors.pop(chunk_id, None)

    # -- query expansion --------------------------------------------------

    def _expand(self, term: str) -> list[tuple[str, float]]:
        """Map one query term to itself plus close lexical neighbours."""
        expansions: list[tuple[str, float]] = []
        if term in self._postings:
            expansions.append((term, 1.0))

        grams = char_ngrams(term)
        candidates: dict[str, int] = {}
        for gram in grams:
            for other in self._gram_index.get(gram, ()):  # small per-gram fan-out
                if other != term:
                    candidates[other] = candidates.get(other, 0) + 1

        scored: list[tuple[float, str]] = []
        for candidate, shared in candidates.items():
            # Cheap upper bound on Jaccard before paying for the real thing.
            if shared < 2 and len(grams) > 2:
                continue
            similarity = jaccard(grams, char_ngrams(candidate))
            if similarity >= FUZZY_MIN_SIMILARITY:
                scored.append((similarity, candidate))

        scored.sort(reverse=True)
        for similarity, candidate in scored[:FUZZY_MAX_EXPANSIONS]:
            expansions.append((candidate, FUZZY_WEIGHT * similarity))
        return expansions

    # -- scoring ----------------------------------------------------------

    def _bm25(
        self, query_terms: list[str], allowed: set[str] | None, limit: int
    ) -> list[ScoredChunk]:
        n_chunks = len(self._chunk_len)
        if not n_chunks or not query_terms:
            return []
        avgdl = self._total_len / n_chunks or 1.0

        # One group per distinct query term, holding that term and its fuzzy
        # neighbours. Grouping lets us tell "matched three different concepts"
        # apart from "matched one concept three times".
        groups: list[dict[str, float]] = []
        for term in dict.fromkeys(query_terms):
            expanded = dict(self._expand(term))
            if expanded:
                groups.append(expanded)
        if not groups:
            return []

        scores: dict[str, float] = {}
        matched: dict[str, set[int]] = {}

        for group_index, group in enumerate(groups):
            for term, weight in group.items():
                postings = self._postings.get(term)
                if not postings:
                    continue
                df = len(postings)
                idf = math.log(1.0 + (n_chunks - df + 0.5) / (df + 0.5))
                for chunk_id, tf in postings.items():
                    if allowed is not None and self._chunk_doc.get(chunk_id) not in allowed:
                        continue
                    length = self._chunk_len.get(chunk_id, 1)
                    denominator = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * length / avgdl)
                    scores[chunk_id] = (
                        scores.get(chunk_id, 0.0)
                        + weight * idf * (tf * (BM25_K1 + 1.0)) / denominator
                    )
                    matched.setdefault(chunk_id, set()).add(group_index)

        # One incidental shared word is noise; requiring two distinct matches
        # is what lets out-of-domain questions come back empty.
        min_terms = 1 if len(groups) <= MIN_TERM_MATCH_THRESHOLD else 2
        ranked = sorted(
            (
                (chunk_id, score)
                for chunk_id, score in scores.items()
                if len(matched[chunk_id]) >= min_terms
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:limit]
        return [
            ScoredChunk(chunk_id, self._chunk_doc.get(chunk_id, ""), score)
            for chunk_id, score in ranked
        ]

    def _dense(self, query: str, allowed: set[str] | None, limit: int) -> list[ScoredChunk]:
        if self._embedder is None or not self._vectors:
            return []
        try:
            query_vector = self._embedder.encode([query])[0]
        except Exception:
            return []

        scored: list[tuple[float, str]] = []
        for chunk_id, vector in self._vectors.items():
            if allowed is not None and self._chunk_doc.get(chunk_id) not in allowed:
                continue
            scored.append(
                (sum(a * b for a, b in zip(query_vector, vector, strict=False)), chunk_id)
            )
        scored.sort(reverse=True)
        return [
            ScoredChunk(chunk_id, self._chunk_doc.get(chunk_id, ""), score)
            for score, chunk_id in scored[:limit]
        ]

    def search(
        self,
        query: str,
        *,
        limit: int = 40,
        doc_ids: list[str] | None = None,
    ) -> list[ScoredChunk]:
        """Rank chunks for a query, fusing every ranker that is available."""
        query_terms = tokenize(query)
        if not query_terms:
            return []
        allowed = set(doc_ids) if doc_ids else None

        with self._lock:
            lexical = self._bm25(query_terms, allowed, limit)
            dense = self._dense(query, allowed, limit) if self._vectors else []

        if not dense:
            return lexical
        return _reciprocal_rank_fusion([lexical, dense], limit)

    # -- diversification --------------------------------------------------

    def diversify(
        self, candidates: list[ScoredChunk], *, top_k: int, lambda_: float = 0.7
    ) -> list[ScoredChunk]:
        """Maximal Marginal Relevance over the candidate pool.

        Chunk similarity is Jaccard over term sets, already held in memory.
        """
        if len(candidates) <= top_k:
            return candidates[:top_k]

        with self._lock:
            term_sets = {c.chunk_id: self._chunk_terms.get(c.chunk_id, set()) for c in candidates}

        best_score = max((c.score for c in candidates), default=1.0) or 1.0
        remaining = list(candidates)
        selected: list[ScoredChunk] = []

        while remaining and len(selected) < top_k:
            best_index = 0
            best_value = float("-inf")
            for index, candidate in enumerate(remaining):
                relevance = candidate.score / best_score
                redundancy = max(
                    (
                        jaccard(term_sets[candidate.chunk_id], term_sets[chosen.chunk_id])
                        for chosen in selected
                    ),
                    default=0.0,
                )
                value = lambda_ * relevance - (1.0 - lambda_) * redundancy
                if value > best_value:
                    best_value = value
                    best_index = index
            selected.append(remaining.pop(best_index))
        return selected


def _reciprocal_rank_fusion(rankings: list[list[ScoredChunk]], limit: int) -> list[ScoredChunk]:
    """Combine rankings without needing their scores to be comparable."""
    fused: dict[str, float] = {}
    owners: dict[str, str] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item.chunk_id] = fused.get(item.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            owners[item.chunk_id] = item.doc_id
    ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [ScoredChunk(chunk_id, owners.get(chunk_id, ""), score) for chunk_id, score in ordered]
