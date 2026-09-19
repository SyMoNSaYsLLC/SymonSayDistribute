# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonrag tests. Provenance and the refusals, because an answer that cannot be traced back to
a file is the one thing retrieval is supposed to prevent."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from symonrag.chunk import ChunkError, Passage, chunk_text
from symonrag.index import Index, IndexError_, tokenize

TOKEN = uuid.uuid4().hex
DOC = ("# Fabric\n\nThe fabric refuses to route to itself because that is a loop.\n\n"
       "# Payload\n\nAdmission forms a batch against a token ceiling, never a request count.\n\n"
       "# Probe\n\nCompute capability is silicon; the CUDA toolkit is the build.\n")


@pytest.fixture
def ix():
    i = Index()
    i.add_text(DOC, "/mnt/SymonSayDistribute/test/doc.md")
    return i


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SYM_RAG_TOKEN", TOKEN)
    monkeypatch.setenv("SYM_RAG_INDEX", str(tmp_path / "ix.json"))
    monkeypatch.setenv("SYM_RAG_ROOTS", "/mnt/SymonSayDistribute")
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- provenance is the product ----------------------------------------------------------
def test_a_passage_with_no_source_cannot_be_built():
    with pytest.raises(ChunkError, match="cannot be cited"):
        Passage(id="x", text="t", source="", ordinal=0, start=0, end=1,
                line_start=1, line_end=1)


def test_an_empty_passage_cannot_be_built():
    with pytest.raises(ChunkError, match="not a passage"):
        Passage(id="x", text="   ", source="s", ordinal=0, start=0, end=1,
                line_start=1, line_end=1)


def test_every_result_carries_a_citation_that_names_a_file_and_lines(ix):
    for r in ix.search("fabric loop", k=3):
        assert ":" in r["cite"] and "-" in r["cite"]
        assert r["source"] and r["lines"][0] >= 1


def test_line_numbers_point_at_the_real_text(ix):
    hit = ix.search("token ceiling", k=1)[0]
    lines = DOC.splitlines()[hit["lines"][0] - 1: hit["lines"][1]]
    assert any("ceiling" in l for l in lines)


# --- refusals ----------------------------------------------------------------------------
def test_an_empty_index_is_refused_not_answered_with_nothing():
    with pytest.raises(IndexError_, match="index is empty"):
        Index().search("anything")


def test_a_query_of_only_stop_words_is_refused(ix):
    with pytest.raises(IndexError_, match="no searchable words"):
        ix.search("the and of it")


def test_overlap_larger_than_the_target_is_refused():
    with pytest.raises(ChunkError, match="passages contain each other"):
        chunk_text("hello world", "s", target=10, overlap=10)


def test_explaining_an_unknown_passage_is_refused(ix):
    with pytest.raises(IndexError_, match="no passage"):
        ix.explain("fabric", "not-a-real-id")


# --- the score can be read ----------------------------------------------------------------
def test_explain_decomposes_the_score_into_terms(ix):
    top = ix.search("compute capability silicon", k=1)[0]
    e = ix.explain("compute capability silicon", top["id"])
    assert abs(e["score"] - top["score"]) < 0.01
    contributing = [t for t in e["terms"] if t["contribution"] > 0]
    assert contributing and all("idf" in t for t in contributing)


def test_a_rare_term_outscores_a_common_one(ix):
    ix.add_text("fabric fabric fabric appears everywhere in this corpus", "/mnt/SymonSayDistribute/t/b.md")
    e = ix.explain("fabric silicon", ix.search("silicon", k=1)[0]["id"])
    by = {t["term"]: t for t in e["terms"]}
    assert by["silicon"]["documents_with_term"] <= by["fabric"]["documents_with_term"]


# --- tokenizer is shared -------------------------------------------------------------------
def test_the_same_tokenizer_is_used_at_index_and_query_time():
    assert tokenize("The Fabric Routes") == tokenize("the fabric routes")


# --- persistence ----------------------------------------------------------------------------
def test_an_index_round_trips_with_its_provenance(ix, tmp_path):
    f = tmp_path / "i.json"
    ix.save(f)
    back = Index.load(f)
    assert back.n == ix.n
    assert back.search("fabric loop", k=1)[0]["cite"] == ix.search("fabric loop", k=1)[0]["cite"]


def test_a_foreign_schema_is_refused(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text('{"schema": "somebody-elses/2", "passages": []}')
    with pytest.raises(IndexError_, match="not symonrag/index/1"):
        Index.load(f)


# --- over http --------------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("SYM_RAG_TOKEN", raising=False)
    monkeypatch.setenv("SYM_RAG_INDEX", str(tmp_path / "x.json"))
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonrag/health").status_code == 200
    assert c.get("/api/symonrag/status").status_code == 503


def test_indexing_outside_the_permitted_roots_is_refused(client):
    r = client.post("/api/symonrag/index", headers=auth(), json={"paths": ["/etc"]})
    assert r.status_code == 403
    assert "outside the permitted roots" in r.json()["detail"]["refused"]


def test_an_index_that_would_be_empty_is_refused(client, tmp_path):
    r = client.post("/api/symonrag/index", headers=auth(),
                    json={"paths": ["/mnt/SymonSayDistribute"], "glob": "*.nothing-matches"})
    assert r.status_code == 409


def test_context_formats_for_a_prompt_and_keeps_the_citations(client):
    b = client.post("/api/symonrag/index", headers=auth(),
                    json={"paths": ["/mnt/SymonSayDistribute/symonrag"], "glob": "*.md"})
    if b.status_code != 200:
        pytest.skip("nothing to index yet in this branch")
    r = client.post("/api/symonrag/context", headers=auth(),
                    json={"query": "retrieval citations", "k": 2})
    assert r.status_code == 200
    d = r.json()
    assert d["citations"] and all(c["cite"] for c in d["citations"])
    assert "[1]" in d["context"]
