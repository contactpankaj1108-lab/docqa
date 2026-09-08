# DocQA

Ask questions about a collection of documents and get answers with citations.

Upload PDFs, Word files or plain text. Ask in natural language. Answers come only
from the uploaded corpus, with `[n]` markers linking back to the source document
and page. If the documents don't cover the question, the system says so.

```
 upload ──► extract ──► chunk ──► SQLite ──► inverted index
                                                  │
 question ─────────────────────────────► retrieve ┤
                                                  ▼
                                    Claude (grounded) ──► answer + citations
```

## Requirements

Python 3.10+. An Anthropic API key is optional (see [Without an API
key](#without-an-api-key)).

## Setup

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # optional
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."  # optional
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell 5.1 has no `&&` operator, so run these as separate lines
rather than chaining them.

Open http://localhost:8000 and drag files from `samples/` onto the page, or load
them from the shell:

```bash
python scripts/seed_samples.py
```

OpenAPI docs are at `/docs`.

### Docker

```bash
docker compose up --build
```

Serves on port 8000. Uploads and the index persist in the `docqa-data` volume.
`ANTHROPIC_API_KEY` passes through from the environment if set.

## Sample corpus

Five documents across three formats, with overlapping topics so cross-document
questions are testable (two of them cover incident reporting):

| File | Format | Contents |
|---|---|---|
| `data-science-intern-handbook.docx` | DOCX | Responsibilities, mentoring, evaluation |
| `information-security-policy.pdf` | PDF, 3pp | Classification, access, incidents, retention |
| `employee-leave-policy.txt` | TXT | Annual, sick, parental, unpaid leave |
| `it-helpdesk-faq.txt` | TXT | SLAs, password resets, hardware, expenses |
| `warehouse-safety-manual.txt` | TXT | PPE, forklifts, lockout/tagout, reporting |

Questions that exercise different paths:

```
What are the responsibilities of a data science intern?      # list from one doc
How quickly must a security incident be reported, and to whom?  # fact + page cite
How many annual leave days, and how many carry over?         # two facts, one section
How do incident reporting rules differ between the security
  policy and the warehouse manual?                           # spans two documents
What is our policy on remote work in Antarctica?             # should decline
```

```bash
python scripts/seed_samples.py --ask "What are the responsibilities of a data science intern?"
```

## Architecture

### Ingestion

`extraction.py` produces ordered `(page, paragraph)` blocks. PDFs via `pypdf`
with per-page attribution and hyphenation repair (`objec-\ntive` → `objective`);
DOCX via `python-docx`, with tables flattened row by row; text files through an
encoding ladder (UTF-8 → cp1252 → latin-1). Scanned PDFs with no text layer are
rejected with a message rather than indexed empty. OCR is out of scope.

`chunking.py` packs sentences into ~180-word chunks with 45 words of overlap.
Splits land on sentence boundaries so a chunk reads correctly as a quote and the
sentence carrying an answer isn't cut in half.

`store.py` writes documents and chunks to SQLite. That file is the only durable
state; the index is rebuilt from it at startup.

### Retrieval

`retrieval.py` maintains an in-memory inverted index, updated incrementally, so
an upload only touches postings for the terms it uses. Per query:

1. **BM25** over the inverted index. Cost tracks the number of chunks holding
   the query terms, not corpus size.
2. **Fuzzy term expansion.** Query terms pick up close neighbours via a
   character-trigram map over the vocabulary, covering `authorise`/`authorize`,
   `secrity`/`security` and similar. Trigrams beat 4-grams here: on short words
   they keep genuine variants (0.5–0.7 similarity) clear of unrelated words
   (below 0.4), where 4-grams collapse the gap.
3. **Dense vectors**, if `DOCQA_EMBEDDINGS=true` and `sentence-transformers` is
   installed, fused with BM25 by Reciprocal Rank Fusion. Off by default.
4. **Relevance floor.** A question with 3+ content words must match at least 2
   distinct ones, so out-of-domain questions return nothing instead of latching
   onto a single incidental word.
5. **MMR** selects the final passages, so the context isn't six near-identical
   chunks from one section.
6. **Neighbour expansion.** Each hit is widened with adjacent chunks, and
   overlapping ranges are merged so the same text isn't sent twice.

### Answering

`llm.py` sends numbered passages to Claude with a system prompt restricting it to
those passages, requiring `[n]` citations, and requiring an explicit "not covered
by these documents" when they don't answer the question. Responses stream to the
browser over SSE. Citation numbers are parsed back out and matched against the
passages actually sent, so the UI can mark which sources were used.

### Layout

```
app/
  main.py         FastAPI routes and schemas
  service.py      Ingest / retrieve / answer orchestration
  extraction.py   PDF, DOCX, TXT → text blocks
  chunking.py     Sentence-aware chunking
  retrieval.py    BM25, fuzzy expansion, RRF, MMR
  embeddings.py   Optional sentence-transformers provider
  llm.py          Claude prompting, streaming, extractive fallback
  store.py        SQLite persistence
  config.py       Environment-driven settings
web/              Single-page UI, no build step
scripts/          Sample generation, seeding, benchmark
tests/            Unit, pipeline and HTTP tests
samples/          Test corpus
```

`service.py` has no FastAPI imports, so the pipeline runs from a script or a test
without a server.

## API

| Method | Path | |
|---|---|---|
| `POST` | `/api/documents` | Upload files (multipart, field `files`) |
| `GET` | `/api/documents` | List with status and chunk counts |
| `GET` | `/api/documents/{id}` | Detail plus extracted-text preview |
| `GET` | `/api/documents/{id}/file` | Download the original |
| `DELETE` | `/api/documents/{id}` | Remove from storage and index |
| `POST` | `/api/ask` | Answer with sources |
| `POST` | `/api/ask/stream` | Same, as server-sent events |
| `GET` | `/api/stats` | Corpus and engine status |
| `GET` | `/health` | Liveness |

```bash
curl -F "files=@samples/information-security-policy.pdf" \
     http://localhost:8000/api/documents

curl -X POST http://localhost:8000/api/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "How quickly must a security incident be reported?"}'
```

```jsonc
{
  "answer": "Within one hour of discovery, to the security team ... [1]",
  "sources": [{
    "n": 1,
    "document_id": "5f0c...",
    "filename": "information-security-policy.pdf",
    "page": 1,
    "snippet": "Any suspected or actual security incident must be reported ...",
    "score": 8.41,
    "cited": true
  }],
  "mode": "generated",
  "model": "claude-opus-5",
  "timing_ms": { "retrieval": 11.4, "generation": 2103.7 }
}
```

`/api/ask` also takes `document_ids` to scope the search, `history` for follow-up
questions, and `top_k`.

## Performance

From `scripts/benchmark.py`: synthetic 1,500-word documents, 20,000-word
vocabulary, single process on a laptop.

| Documents | Chunks | Ingest | Retrieval p50 | p95 | Peak RSS | Cold start |
|---|---|---|---|---|---|---|
| 200 | 2,257 | 36 ms/doc | 12 ms | 19 ms | 40 MB | 1.6 s |
| 1,000 | 11,306 | 39 ms/doc | 52 ms | 166 ms | 152 MB | 10.5 s |

Retrieval is what a user waits for per question; the model call is an order of
magnitude larger. Ingestion happens once per document.

The benchmark is a deliberate worst case. Every synthetic document carries the
same twelve topic phrases and every query contains one, so each query walks
posting lists as long as the corpus. Real corpora spread common terms far more
thinly.

Caching SQLite connections per thread took p50 from 57 ms to 12 ms at 200
documents; reconnecting per query had been dominating retrieval.

### Limits

The index lives in memory in one process, which suits a corpus in the low
thousands. Beyond that:

- **Tens of thousands of documents** — move postings to SQLite FTS5 or an
  external search service behind the same `SearchIndex` interface.
- **Multiple replicas** — each would hold its own copy and re-read SQLite at
  boot. Shared state needs an external index.
- **Cold start** — 10.5 s at 11,000 chunks, since every chunk is re-tokenised at
  boot. Persisting postings alongside the chunks removes it.
- **Large uploads** — extraction and chunking run inside the request. The
  `status` column on `documents` is already there for a background worker.

## Without an API key

The service runs without Anthropic credentials. Upload, indexing, retrieval,
scoping, citations and the UI all work. Only the final answer changes: instead of
a generated answer you get the best-matching sentences from the retrieved
passages, still cited, labelled as extractive in the UI.

This keeps the system testable without credentials and means a credential problem
degrades the answer instead of taking the service down. The test suite runs in
this mode.

## Configuration

All settings have defaults; see `.env.example`.

| Variable | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables generated answers |
| `DOCQA_MODEL` | `claude-opus-5` | Model for answers |
| `DOCQA_EFFORT` | `medium` | Reasoning effort, `low`–`max` |
| `DOCQA_MAX_TOKENS` | `4000` | Answer length ceiling |
| `DOCQA_DATA_DIR` | `./data` | SQLite file and uploads |
| `DOCQA_MAX_UPLOAD_MB` | `25` | Per-file limit |
| `DOCQA_CHUNK_WORDS` | `180` | Target chunk size |
| `DOCQA_CHUNK_OVERLAP` | `45` | Overlap between chunks |
| `DOCQA_CANDIDATE_K` | `40` | Candidates before diversification |
| `DOCQA_TOP_K` | `6` | Passages sent to the model |
| `DOCQA_NEIGHBOUR_WINDOW` | `1` | Adjacent chunks per hit |
| `DOCQA_EMBEDDINGS` | `false` | Enable dense retrieval |
| `DOCQA_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |

Dense retrieval:

```bash
pip install sentence-transformers
DOCQA_EMBEDDINGS=true uvicorn app.main:app
```

## Development

```bash
pip install -r requirements-dev.txt
pytest                                    # 53 tests, ~10s
ruff check . && ruff format --check .
python scripts/benchmark.py --documents 200
python scripts/make_samples.py            # regenerate the sample corpus
```

Tests cover extraction for all three formats, chunk sizing and overlap, BM25
ranking, fuzzy matching, MMR, incremental add and removal, deduplication, path
traversal, index rebuild after restart, and every endpoint including the
streaming one.

`tests/test_service.py` holds a retrieval eval: nine questions paired with the
document that should answer them. It asserts the right document reaches the
model's context in all nine cases, plus a top-1 ranking rate. Extend it when
tuning retrieval.

## Assumptions

**Scale and scope.** A single-team knowledge base, hundreds to a few thousand
documents, one process, one writer. No multi-tenancy, accounts or per-document
permissions: anyone who can reach the service reads everything in it. Real auth
needs an identity provider, so it's left out rather than stubbed.

**Text only.** Answers come from a document's text layer. Scanned PDFs are
rejected rather than silently indexed as empty. Images, charts and diagrams are
not read. Tables are flattened to `cell | cell | cell`, which retrieves well but
loses column relationships in complex tables.

**Page numbers where they exist.** PDFs carry real page numbers. DOCX has no page
concept before layout and plain text has none, so those citations name the
document and chunk instead. Better than inventing plausible page numbers.

**English-oriented.** Tokenisation lowercases, strips accents and applies a
conservative English suffix stemmer. Other Latin-script languages retrieve on
exact terms but get no stemming benefit. The stemmer is one function to swap.

**"Not in the documents" is mostly the model's call.** The relevance floor drops
chunks sharing one incidental word, but a lexical retriever still returns
something for many out-of-domain questions. The grounding instruction is what
makes the final answer honest. Without an API key that judgement isn't available
and the extractive fallback quotes the closest passages.

**Identical files are deduplicated.** Re-uploading the same bytes returns the
existing document. A revised document is a new document; there's no version
tracking, so removing the old one is manual.

**History is client-held.** The API is stateless. The browser sends recent turns
with each question and follow-ups are condensed into a standalone query before
retrieval. No server-side sessions.

**Uploaders are trusted.** Filenames are sanitised against traversal and uploads
are size- and type-checked, but document content is treated as data to retrieve,
not as instructions. Untrusted uploaders would need prompt-injection defence in
the retrieved passages.

## Notes on the design

Lexical retrieval is the default and dense is opt-in. For policy and manual
corpora, questions tend to reuse the documents' own vocabulary, which is where
BM25 is strongest, and every result is explainable by the terms that matched.
Dense retrieval helps on paraphrased questions and fuses cleanly, but a several
hundred megabyte model download is a poor default for a 200-document corpus. The
fuzzy expansion layer recovers much of the vocabulary-mismatch benefit for free.

SQLite instead of a vector database: one file, no second service, transactional,
and the corpus is inspectable with `sqlite3`. The index rebuilds from it in
seconds. Replacing it later means replacing one class.

Citations are verified rather than trusted. The `[n]` markers in an answer are
parsed and checked against the passages that were sent, so a reader can follow
any claim back to its source text.

## License

MIT. See [LICENSE](LICENSE).
