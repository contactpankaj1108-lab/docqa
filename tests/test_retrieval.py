from __future__ import annotations

from app.retrieval import SearchIndex
from app.textutils import stem, tokenize

CORPUS = [
    (
        "d1",
        "d1:0",
        "Interns must clean, validate and document datasets before any downstream model.",
    ),
    ("d1", "d1:1", "Every intern reports to a pod lead and is assigned a mentor."),
    ("d2", "d2:0", "Security incidents must be reported to the security team within one hour."),
    ("d2", "d2:1", "Passwords must be at least 14 characters and unique to each system."),
    ("d3", "d3:0", "Forklift operators hold a licence valid for three years."),
]


def build_index() -> SearchIndex:
    index = SearchIndex()
    for doc_id in ("d1", "d2", "d3"):
        index.add_chunks(doc_id, [(cid, text) for did, cid, text in CORPUS if did == doc_id])
    return index


def test_ranks_the_relevant_chunk_first() -> None:
    hits = build_index().search("how quickly must a security incident be reported")
    assert hits[0].chunk_id == "d2:0"


def test_document_filter_excludes_everything_else() -> None:
    hits = build_index().search("incident reporting", doc_ids=["d1"])
    assert all(hit.doc_id == "d1" for hit in hits)


def test_plural_and_typo_still_retrieve() -> None:
    index = build_index()
    # "passwords" -> "password" is stemming; "forklifts" and "secrity" need the
    # fuzzy expansion built over the vocabulary.
    assert index.search("password length")[0].chunk_id == "d2:1"
    assert index.search("forklifts")[0].doc_id == "d3"
    assert index.search("secrity incidents")[0].doc_id == "d2"


def test_unknown_terms_return_nothing() -> None:
    assert build_index().search("photosynthesis chlorophyll") == []


def test_stats_track_the_corpus() -> None:
    stats = build_index().stats()
    assert stats.chunks == len(CORPUS)
    assert stats.documents == 3
    assert stats.vocabulary > 0
    assert stats.dense is False


def test_removing_a_document_removes_its_chunks() -> None:
    index = build_index()
    index.remove_document("d2")

    assert index.has_document("d2") is False
    assert index.stats().chunks == 3
    assert all(hit.doc_id != "d2" for hit in index.search("security incident"))
    # The vocabulary shrinks too, so removed documents cannot leak through the
    # fuzzy expansion map.
    assert index.search("passwords") == []


def test_reindexing_after_removal_works() -> None:
    index = build_index()
    index.remove_document("d2")
    index.add_chunks("d2", [(cid, text) for did, cid, text in CORPUS if did == "d2"])
    assert index.search("security incident")[0].doc_id == "d2"


def test_mmr_prefers_spreading_across_documents() -> None:
    index = SearchIndex()
    # Four near-identical chunks in one document, one relevant chunk in another.
    index.add_chunks(
        "a", [(f"a:{i}", "annual leave entitlement is 24 days per year") for i in range(4)]
    )
    index.add_chunks("b", [("b:0", "annual leave carry over is capped at five days")])

    candidates = index.search("annual leave carry over days", limit=10)
    diversified = index.diversify(candidates, top_k=2, lambda_=0.6)
    assert len({hit.doc_id for hit in diversified}) == 2


def test_tokenizer_folds_case_accents_and_suffixes() -> None:
    assert tokenize("Résumé RESPONSIBILITIES") == ["resume", "responsibility"]
    assert stem("policies") == "policy"
    assert stem("was") == "was"  # too short to touch
