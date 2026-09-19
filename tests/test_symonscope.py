# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonscope tests. It reads the real estate, so most of these assert SHAPE and REFUSALS —
asserting today's unit list would make the tests fail every time the estate changes, which is
the opposite of what this unit is for."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from symonscope import edges as E
from symonscope import layers as L
from symonscope import live as V
from symonscope import survey as S

TOKEN = uuid.uuid4().hex


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SYM_SCOPE_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- refusals ------------------------------------------------------------------------
def test_an_unknown_tree_is_refused_and_lists_the_real_ones():
    with pytest.raises(S.SurveyError, match="is not one of the four trees"):
        S.units("NotATree")


def test_a_directory_with_no_bare_is_not_an_estate_tree(tmp_path):
    with pytest.raises(S.SurveyError, match="not an estate tree"):
        S._git(str(tmp_path), "tag", "--list")


def test_health_is_public_but_the_rest_is_closed(monkeypatch):
    monkeypatch.delenv("SYM_SCOPE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonscope/health").status_code == 200
    r = c.get("/api/symonscope/units")
    assert r.status_code == 503 and "SYM_SCOPE_TOKEN" in r.json()["detail"]


def test_a_wrong_token_is_401(client):
    assert client.get("/api/symonscope/units",
                      headers={"Authorization": "Bearer nope"}).status_code == 401


def test_an_unknown_tree_over_http_is_409_not_an_empty_list(client):
    r = client.get("/api/symonscope/units?tree=Nope", headers=auth())
    assert r.status_code == 409 and "not one of the four trees" in r.json()["detail"]


# --- the unit does not write ------------------------------------------------------------
def test_every_route_is_a_get(client):
    import service
    for r in service.app.routes:
        if hasattr(r, "methods") and str(r.path).startswith("/api/symonscope"):
            assert r.methods <= {"GET", "HEAD"}, f"{r.path} can do more than read"


# --- shape ------------------------------------------------------------------------------
def test_all_four_trees_are_reported_present_or_not():
    rows = S.trees()
    assert {r["tree"] for r in rows} == set(S.TREES)
    assert all("present" in r for r in rows)


def test_every_unit_names_its_kind_and_the_kind_is_one_we_know():
    known = {"service", "library", "tool", "documentation", "unknown", "web"}
    assert all(u["kind"] in known for u in S.units())


def test_a_service_declares_a_route_prefix_or_says_it_has_none():
    for u in S.units():
        if u["kind"] == "service":
            assert "route_prefix" in u and "port" in u


# --- edges carry evidence, which is the point --------------------------------------------
def test_every_edge_names_a_file_and_a_line():
    for e in E.edges()["edges"]:
        assert ":" in e["evidence"], e
        path, line = e["evidence"].rsplit(":", 1)
        assert line.isdigit() and path.startswith("/"), e


def test_no_edge_points_at_itself():
    assert all(e["from"] != e["to"] for e in E.edges()["edges"])


def test_edge_kinds_are_declared_not_invented():
    assert {e["kind"] for e in E.edges()["edges"]} <= {"import", "http", "declared"}


# --- layers are derived, and a cycle is a refusal ------------------------------------------
def test_layer_zero_units_depend_on_nothing():
    out = L.layers()
    zero = next((l for l in out["layers"] if l["layer"] == 0), None)
    assert zero is not None
    assert all(u["depends_on"] == [] for u in zero["units"])


def test_a_unit_in_a_cycle_gets_no_layer_rather_than_a_wrong_one():
    out = L.layers()
    in_cycle = {u for c in out["cycles"] for u in c}
    placed = {u["unit"] for l in out["layers"] for u in l["units"]}
    assert not (in_cycle & placed), "a unit in a cycle was given a layer anyway"


def test_a_synthetic_cycle_is_detected(monkeypatch):
    fake_units = [{"unit": "a", "kind": "service", "path": "/x/a"},
                  {"unit": "b", "kind": "service", "path": "/x/b"}]
    monkeypatch.setattr(L, "units", lambda tree="t": fake_units)
    monkeypatch.setattr(L, "edges", lambda tree="t": {"count": 2, "edges": [
        {"from": "a", "to": "b", "kind": "http"}, {"from": "b", "to": "a", "kind": "http"}]})
    out = L.layers("t")
    assert out["cycles"], "a -> b -> a was not reported"
    assert sorted(out["unplaced"]) == ["a", "b"]


def test_a_synthetic_chain_layers_cleanly(monkeypatch):
    fake = [{"unit": n, "kind": "service", "path": f"/x/{n}"} for n in ("a", "b", "c")]
    monkeypatch.setattr(L, "units", lambda tree="t": fake)
    monkeypatch.setattr(L, "edges", lambda tree="t": {"count": 2, "edges": [
        {"from": "c", "to": "b", "kind": "http"}, {"from": "b", "to": "a", "kind": "http"}]})
    out = L.layers("t")
    assert not out["cycles"] and not out["unplaced"]
    got = {u["unit"]: l["layer"] for l in out["layers"] for u in l["units"]}
    assert got == {"a": 0, "b": 1, "c": 2}


# --- live state names disagreements rather than hiding them ---------------------------------
def test_live_state_reports_whether_it_agrees_and_why_not():
    s = V.state()
    assert isinstance(s["agrees"], bool)
    assert all("why" in f and "kind" in f for f in s["findings"])


def test_board_ports_are_read_not_assumed():
    b = V.board_ports()
    assert isinstance(b, dict)
    assert all(isinstance(v, int) for v in b.values())


# --- the one route a model calls -------------------------------------------------------------
def test_survey_answers_in_one_call_with_a_headline(client):
    r = client.get("/api/symonscope/survey", headers=auth())
    assert r.status_code == 200
    b = r.json()
    for k in ("units", "subcomponents", "edges", "layers", "live", "headline"):
        assert k in b, k
    assert b["headline"]["units"] > 0
