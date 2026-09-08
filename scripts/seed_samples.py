"""Ingest everything in ``samples/`` straight into the index.

Useful for a first run and for smoke-testing the pipeline without a server:

    python scripts/seed_samples.py
    python scripts/seed_samples.py --ask "What does a data science intern do?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.extraction import SUPPORTED_EXTENSIONS  # noqa: E402
from app.service import DocQAService, IngestError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest the sample corpus.")
    parser.add_argument(
        "--dir",
        default=str(Path(__file__).resolve().parent.parent / "samples"),
        help="Directory of documents to ingest (default: samples/).",
    )
    parser.add_argument("--ask", help="Ask a question once ingestion finishes.")
    args = parser.parse_args()

    source = Path(args.dir)
    if not source.is_dir():
        print(f"No such directory: {source}", file=sys.stderr)
        return 1

    service = DocQAService(settings)
    files = sorted(p for p in source.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not files:
        print(f"No supported documents in {source}", file=sys.stderr)
        return 1

    for path in files:
        try:
            document, duplicate = service.ingest(path.name, path.read_bytes())
        except IngestError as exc:
            print(f"  FAILED  {path.name:<44} {exc}")
            continue
        status = "SKIP" if duplicate else "OK"
        print(
            f"  {status:<7} {document.filename:<44} "
            f"{document.n_chunks:3d} chunks, {document.n_words:5d} words"
        )

    stats = service.stats()
    print(
        f"\nIndex: {stats['documents']} documents, {stats['chunks']} chunks, "
        f"{stats['vocabulary']} terms | answers: {stats['generation']}"
    )

    if args.ask:
        result = service.ask(args.ask)
        print(f"\nQ: {args.ask}\n")
        print(result["answer"])
        print("\nSources:")
        for source_item in result["sources"]:
            marker = "*" if source_item["cited"] else " "
            page = f" p{source_item['page']}" if source_item["page"] else ""
            print(
                f"  {marker} [{source_item['n']}] {source_item['filename']}{page} "
                f"(score {source_item['score']:.3f})"
            )
        timing = result["timing_ms"]
        print(f"\nRetrieval {timing['retrieval']}ms | generation {timing['generation']}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
