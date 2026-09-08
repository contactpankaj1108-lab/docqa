"""Measure ingestion and retrieval cost as the corpus grows.

    python scripts/benchmark.py --documents 200

Generates synthetic documents (so the numbers are reproducible on any machine),
ingests them, then times retrieval. Retrieval time is the number that matters:
it is what a user waits for on every question, on top of model latency.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.service import DocQAService  # noqa: E402

TOPICS = [
    "expense approval",
    "incident response",
    "annual leave",
    "forklift operation",
    "data retention",
    "supplier onboarding",
    "laptop refresh",
    "parental leave",
    "access review",
    "conveyor maintenance",
    "password policy",
    "mentor programme",
]
VERBS = ["must", "should", "may", "is required to", "is expected to"]
OBJECTS = [
    "be recorded in the register within two working days",
    "be approved by the department head before it takes effect",
    "follow the escalation path defined in the appendix",
    "be reviewed quarterly by the responsible owner",
    "be reported to the compliance team within 24 hours",
    "be retained for seven years unless a longer period applies",
]


def build_vocabulary(size: int, rng: random.Random) -> list[str]:
    """A pseudo-vocabulary, drawn from Zipf-like frequencies when sampled.

    Vocabulary size drives BM25 cost far more than document count does: a
    corpus of a few hundred repeated phrases gives every term a posting list as
    long as the corpus, which is a worst case no real document set hits.
    """
    letters = "abcdefghijklmnopqrstuvwxyz"
    return ["".join(rng.choice(letters) for _ in range(rng.randint(4, 11))) for _ in range(size)]


def zipf_sample(vocabulary: list[str], rng: random.Random) -> str:
    # Rank-biased pick: common words dominate, the long tail still shows up.
    rank = min(int(len(vocabulary) ** rng.random()), len(vocabulary) - 1)
    return vocabulary[rank]


def synthetic_document(index: int, words: int, rng: random.Random, vocabulary: list[str]) -> str:
    lines = [f"Operating Procedure {index:04d}", ""]
    written = 0
    while written < words:
        topic = rng.choice(TOPICS)
        filler = " ".join(zipf_sample(vocabulary, rng) for _ in range(rng.randint(12, 25)))
        sentence = (
            f"Section on {topic}. Any {topic} request {rng.choice(VERBS)} "
            f"{rng.choice(OBJECTS)}. {filler.capitalize()}. "
            f"Staff handling {topic} in site {index} record the outcome in the operations log."
        )
        lines.append(sentence)
        written += len(sentence.split())
    return "\n".join(lines)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=int, default=200)
    parser.add_argument("--words", type=int, default=1500)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--vocabulary", type=int, default=20000)
    args = parser.parse_args()

    rng = random.Random(7)
    vocabulary = build_vocabulary(args.vocabulary, rng)
    settings = Settings(data_dir=Path(tempfile.mkdtemp(prefix="dqbench")))
    service = DocQAService(settings)

    tracemalloc.start()
    started = time.perf_counter()
    for index in range(args.documents):
        body = synthetic_document(index, args.words, rng, vocabulary)
        service.ingest(f"procedure-{index:04d}.txt", body.encode("utf-8"))
    ingest_seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stats = service.stats()
    print(
        f"Corpus       : {stats['documents']} documents, {stats['chunks']} chunks, "
        f"{stats['vocabulary']} vocabulary terms"
    )
    print(
        "Ingestion    : {:.1f} s total, {:.0f} ms/document, {:.0f} words/s".format(
            ingest_seconds, ingest_seconds / args.documents * 1000, stats["words"] / ingest_seconds
        )
    )
    print(f"Peak memory  : {peak / 1024 / 1024:.0f} MB during ingestion (index + parsing)")

    questions = [
        f"What must happen to a {rng.choice(TOPICS)} request involving "
        f"{zipf_sample(vocabulary, rng)} and {zipf_sample(vocabulary, rng)}?"
        for _ in range(args.queries)
    ]
    latencies = []
    for question in questions:
        started = time.perf_counter()
        service.retrieve(question, doc_ids=None, top_k=6)
        latencies.append((time.perf_counter() - started) * 1000)

    print(
        f"Retrieval    : p50 {statistics.median(latencies):.1f} ms, "
        f"p95 {percentile(latencies, 0.95):.1f} ms, max {max(latencies):.1f} ms "
        f"({len(latencies)} queries)"
    )

    started = time.perf_counter()
    DocQAService(settings)
    print(
        "Cold start   : %.2f s to rebuild the index from SQLite" % (time.perf_counter() - started)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
