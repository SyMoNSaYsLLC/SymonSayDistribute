# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonskill tests.

Most run against a synthetic collection under tmp_path, so a malformed skill can be tested
without writing one into the real collection. Three run against the real six on this host,
and skip cleanly if they are not present — the estate must be testable on a machine that has
not checked out the skills branch.
"""
import importlib
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from symonskill import catalogue as C

TOKEN = uuid.uuid4().hex
REAL = Path("/mnt/SymonSayDistribute/skills")


def make_skill(root: Path, name: str, *, frontmatter: str | None = None,
               body: str = "Follow these steps.\n" * 12, scripts: list[str] | None = None) -> Path:
    d = root / name
    (d / "scripts").mkdir(parents=True, exist_ok=True)
    fm = frontmatter if frontmatter is not None else (
        f"---\nname: {name}\ndescription: A synthetic skill for deciding placement of storage "
        f"volumes during migration.\nlicense: SymonSaysLLC Proprietary License 1.0\n---\n")
    (d / "SKILL.md").write_text(fm + "\n" + body)
    for s in (scripts or []):
        (d / "scripts" / s).write_text("#!/bin/sh\necho hi\n")
    return d


@pytest.fixture
def collection(monkeypatch, tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(root))
    return root


@pytest.fixture
def client(monkeypatch, tmp_path):
    root = tmp_path / "skills"; root.mkdir(exist_ok=True)
    make_skill(root, "placement-check")
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(root))
    # Off-loopback so `headers=auth()` actually exercises the guard; on a loopback bind it
    # returns before comparing anything and every authenticated test would pass with no token.
    monkeypatch.setenv("SYM_SKILL_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_SKILL_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- frontmatter: the contract, and every way it can be wrong --------------------------------
def test_a_well_formed_block_is_read():
    r = C.parse_frontmatter("---\nname: a-skill\ndescription: does a thing\n---\nbody\n")
    assert r["ok"] and r["fields"]["name"] == "a-skill"


def test_no_frontmatter_is_named_as_such():
    r = C.parse_frontmatter("# just a heading\n")
    assert not r["ok"] and "no frontmatter" in r["why"]


def test_a_missing_description_is_refused_with_the_reason_it_matters():
    """The description is what decides relevance. Without it a skill can be listed, never chosen."""
    r = C.parse_frontmatter("---\nname: a-skill\n---\nbody\n")
    assert not r["ok"]
    assert "description" in r["why"] and "relevant" in r["why"]


def test_a_missing_name_is_refused():
    assert not C.parse_frontmatter("---\ndescription: does a thing\n---\n")["ok"]


def test_an_empty_value_counts_as_missing():
    assert not C.parse_frontmatter("---\nname: a\ndescription:   \n---\n")["ok"]


def test_a_malformed_line_is_reported_with_its_number():
    r = C.parse_frontmatter("---\nname: a\nthis is not a pair\ndescription: d\n---\n")
    assert not r["ok"] and "line 3" in r["why"]


def test_quotes_are_stripped_from_values():
    r = C.parse_frontmatter('---\nname: "a-skill"\ndescription: \'does a thing\'\n---\n')
    assert r["fields"]["name"] == "a-skill" and r["fields"]["description"] == "does a thing"


def test_parsing_never_raises_on_hostile_input():
    """A malformed skill is a finding to report, not an exception that hides the other five."""
    for bad in ("", "---\n", "---\n---\n", "---\n" + "x" * 5000 + "\n---\n", "\x00\x01"):
        assert C.parse_frontmatter(bad)["ok"] in (True, False)


# --- the catalogue ----------------------------------------------------------------------------
def test_a_valid_skill_is_found(collection):
    make_skill(collection, "storage-place", scripts=["go.py"])
    r = C.skills()
    assert r["count"] == 1 and r["valid"] == 1
    assert r["skills"][0]["scripts"] == ["go.py"]


def test_an_invalid_skill_is_listed_not_hidden(collection):
    """A catalogue that drops a malformed skill reports a tidier estate than the one that exists."""
    make_skill(collection, "good-one")
    make_skill(collection, "broken-one", frontmatter="not frontmatter at all\n")
    r = C.skills()
    assert r["count"] == 2 and r["valid"] == 1 and r["invalid"] == 1
    assert r["invalid_names"] == ["broken-one"]
    assert "listed rather than hidden" in r["why"]


def test_a_directory_without_a_skill_md_is_not_a_skill(collection):
    (collection / "just-a-folder").mkdir()
    make_skill(collection, "real-skill")
    assert C.skills()["count"] == 1


def test_a_declared_name_that_is_not_the_directory_is_flagged(collection):
    """A caller asking by either name misses it under the other, and nothing else would notice."""
    make_skill(collection, "on-disk",
               frontmatter="---\nname: declared-differently\ndescription: a thing\n---\n")
    r = C.skills()
    assert r["name_mismatches"] == ["on-disk"]
    assert "will miss it" in r["skills"][0]["name_mismatch"]


def test_a_missing_root_is_reported_rather_than_silently_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(tmp_path / "absent"))
    r = C.skills()
    assert r["count"] == 0 and r["roots"][0]["exists"] is False


def test_several_roots_are_searched(monkeypatch, tmp_path):
    import os as _os
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    make_skill(a, "from-a"); make_skill(b, "from-b")
    monkeypatch.setenv("SYM_SKILL_ROOTS", f"{a}{_os.pathsep}{b}")
    assert {s["skill"] for s in C.skills()["skills"]} == {"from-a", "from-b"}


# --- get ---------------------------------------------------------------------------------------
def test_a_skill_can_be_fetched_by_directory_or_declared_name(collection):
    make_skill(collection, "on-disk",
               frontmatter="---\nname: declared\ndescription: a thing about storage\n---\n")
    assert C.get("on-disk")["skill"] == "on-disk"
    assert C.get("declared")["skill"] == "on-disk"


def test_the_body_comes_back_without_the_frontmatter(collection):
    make_skill(collection, "a-skill", body="THE BODY TEXT\n")
    b = C.get("a-skill")["body"]
    assert "THE BODY TEXT" in b and "description:" not in b


def test_an_unknown_skill_is_refused_with_what_IS_known(collection):
    make_skill(collection, "known-one")
    with pytest.raises(C.SkillError, match="known-one"):
        C.get("no-such-skill")


def test_an_empty_name_is_refused(collection):
    with pytest.raises(C.SkillError, match="required"):
        C.get("  ")


# --- relevance ----------------------------------------------------------------------------------
def test_relevance_ranks_by_words_the_description_actually_contains(collection):
    make_skill(collection, "storage-skill",
               frontmatter="---\nname: storage-skill\ndescription: migrate storage volumes "
                           "between disks\n---\n")
    make_skill(collection, "licence-skill",
               frontmatter="---\nname: licence-skill\ndescription: decide which licence a "
                           "component carries\n---\n")
    r = C.relevant("migrate storage volumes to another disk")
    assert r["matches"][0]["skill"] == "storage-skill"
    assert "storage" in r["matches"][0]["matched"]


def test_relevance_returns_the_matched_words_so_the_ranking_can_be_disagreed_with(collection):
    make_skill(collection, "a-skill",
               frontmatter="---\nname: a-skill\ndescription: about placement decisions\n---\n")
    assert C.relevant("placement of a component")["matches"][0]["matched"] == ["placement"]


def test_no_match_is_an_answer_not_a_failure(collection):
    make_skill(collection, "storage-skill",
               frontmatter="---\nname: storage-skill\ndescription: migrate volumes\n---\n")
    r = C.relevant("photosynthesis in tropical ferns")
    assert r["matches"] == [] and "better than ranking" in r["why"]


def test_an_invalid_skill_is_never_offered_as_relevant(collection):
    make_skill(collection, "broken", frontmatter="no frontmatter\n")
    with pytest.raises(C.SkillError):
        C.relevant("")


def test_a_query_of_only_short_words_is_refused(collection):
    """One-word queries rank everything equally and help nobody."""
    with pytest.raises(C.SkillError, match="three characters"):
        C.relevant("a of to the")


# --- validate -----------------------------------------------------------------------------------
def test_validate_is_clean_on_a_well_formed_collection(collection):
    make_skill(collection, "fine-one", scripts=["run.py"])
    assert C.validate()["ok"] is True


def test_validate_reports_a_valid_skill_with_nothing_to_follow(collection):
    make_skill(collection, "hollow", body="short\n", scripts=[])
    v = C.validate()
    assert v["ok"] is False
    assert any(p["kind"] == "empty" for p in v["problems"])


def test_validate_reports_and_never_repairs(collection):
    """Correcting somebody's procedure on our own judgement is not a catalogue's business."""
    d = make_skill(collection, "broken", frontmatter="no frontmatter\n")
    before = (d / "SKILL.md").read_text()
    C.validate()
    assert (d / "SKILL.md").read_text() == before


def test_the_catalogue_never_executes_anything():
    """Running a skill needs the permission to execute. A catalogue that ran things could not
    be asked what is available without risk."""
    import inspect
    src = inspect.getsource(C)
    for banned in ("subprocess", "os.system", "eval(", "exec(", "Popen"):
        assert banned not in src, f"{banned} makes this an executor, not a catalogue"


# --- against the real collection, skipping cleanly when it is absent -----------------------------
@pytest.mark.skipif(not REAL.is_dir(), reason="the skills branch is not checked out here")
def test_the_real_collection_is_found(monkeypatch):
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(REAL))
    r = C.skills()
    assert r["count"] >= 1, "the skills branch exists but no skill was found in it"


@pytest.mark.skipif(not REAL.is_dir(), reason="the skills branch is not checked out here")
def test_every_real_skill_carries_a_usable_contract(monkeypatch):
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(REAL))
    r = C.skills()
    assert r["invalid"] == 0, f"invalid: {r['invalid_names']} — {[s['why'] for s in r['skills'] if not s['valid']]}"


@pytest.mark.skipif(not REAL.is_dir(), reason="the skills branch is not checked out here")
def test_a_real_task_finds_a_real_skill(monkeypatch):
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(REAL))
    r = C.relevant("decide which licence this component carries and where it belongs")
    assert r["matches"], "no skill matched a task the collection plainly covers"


# --- over http ------------------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(tmp_path))
    monkeypatch.setenv("SYM_SKILL_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_SKILL_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonskill/health").status_code == 200
    assert c.get("/api/symonskill/skills").status_code == 503


def test_loopback_needs_no_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SYM_SKILL_ROOTS", str(tmp_path))
    monkeypatch.delenv("SYM_SKILL_HOST", raising=False)
    monkeypatch.delenv("SYM_SKILL_TOKEN", raising=False)
    import service
    importlib.reload(service)
    assert TestClient(service.app).get("/api/symonskill/skills").status_code == 200


def test_the_catalogue_over_http(client):
    r = client.get("/api/symonskill/skills", headers=auth())
    assert r.status_code == 200 and r.json()["count"] == 1
    g = client.get("/api/symonskill/skills/placement-check", headers=auth())
    assert g.status_code == 200 and "body" in g.json()


def test_an_unknown_skill_over_http_is_409_not_500(client):
    r = client.get("/api/symonskill/skills/nope", headers=auth())
    assert r.status_code == 409 and "no skill" in r.json()["detail"]


def test_relevance_over_http(client):
    r = client.get("/api/symonskill/relevant", params={"task": "placement of storage volumes"},
                   headers=auth())
    assert r.status_code == 200 and r.json()["matches"]
