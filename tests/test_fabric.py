# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Fabric tests. The refusals ARE the product: what the fabric will not route is what makes
routing through it safer than calling directly."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from symoneural_fabric import route as T
from symoneural_fabric import wiring as W

TOKEN = uuid.uuid4().hex


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SYM_FABRIC_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- the table comes from the board -------------------------------------------------------
def test_no_board_means_no_wiring_table(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "BOARD", str(tmp_path / "nope.board"))
    with pytest.raises(W.FabricError, match="no board at"):
        W.ports()


def test_a_board_with_no_ports_section_is_refused(monkeypatch, tmp_path):
    b = tmp_path / "b.board"; b.write_text("[model]\nname = symon\n")
    monkeypatch.setattr(W, "BOARD", str(b))
    with pytest.raises(W.FabricError, match="no \\[ports\\] section"):
        W.ports()


def test_every_port_on_the_board_is_accounted_for():
    assert W.unknown_on_board() == [], "a port is on the board with no entry and no reason"


def test_nothing_named_not_routable_appears_as_routable():
    assert not (set(W.components()) & set(W.not_routable()))


# --- the table never carries a credential ---------------------------------------------------
def test_the_table_holds_variable_names_and_never_values(monkeypatch):
    monkeypatch.setenv("SYM_BOARD_TOKEN", "a-value-that-must-not-appear")
    blob = repr(W.components())
    assert "SYM_BOARD_TOKEN" in blob
    assert "a-value-that-must-not-appear" not in blob


def test_a_set_token_is_reported_as_a_boolean_only(monkeypatch):
    monkeypatch.setenv("SYM_SCOPE_TOKEN", "x")
    assert W.components()["symonscope"]["token_set"] is True


# --- refusals --------------------------------------------------------------------------------
def test_an_unknown_component_is_refused_and_lists_what_is_routable():
    with pytest.raises(W.FabricError, match="not a routable component"):
        W.resolve("nope", "/api/nope/x")


def test_a_path_outside_the_components_prefix_is_refused():
    with pytest.raises(W.FabricError, match="outside board's published surface"):
        W.resolve("board", "/api/store/where")


def test_the_prefix_itself_resolves():
    assert W.resolve("board", "/api/board")["url"].endswith("/api/board")


def test_a_method_the_fabric_does_not_forward_is_refused():
    with pytest.raises(W.FabricError, match="is not a method"):
        T.call("board", "/api/board/health", "TRACE")


def test_an_unprovisioned_token_names_the_variable_rather_than_failing_downstream(monkeypatch):
    monkeypatch.delenv("SYM_BOARD_TOKEN", raising=False)
    with pytest.raises(W.FabricError, match="needs SYM_BOARD_TOKEN"):
        T.call("board", "/api/board/settings")


def test_the_fabric_refuses_to_take_a_token_from_a_caller():
    import inspect
    sig = inspect.signature(T.call)
    assert not any("token" in p or "auth" in p for p in sig.parameters), \
        "a caller must not be able to supply a credential"


def test_the_fabric_will_not_route_to_itself():
    assert "fabric" in W.not_routable()


def test_control_plane_is_never_routable():
    assert "control_plane" in W.not_routable()


# --- over http ---------------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    monkeypatch.delenv("SYM_FABRIC_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/fabric/health").status_code == 200
    r = c.get("/api/fabric/components")
    assert r.status_code == 503 and "SYM_FABRIC_TOKEN" in r.json()["detail"]


def test_an_unroutable_component_over_http_is_409_with_the_reason(client):
    r = client.post("/api/fabric/call", headers=auth(),
                    json={"component": "nope", "path": "/x"})
    assert r.status_code == 409 and "not a routable component" in r.json()["detail"]


def test_resolve_says_where_without_calling(client):
    r = client.get("/api/fabric/resolve?component=symonscope&path=/api/symonscope/units",
                   headers=auth())
    assert r.status_code == 200 and r.json()["url"].endswith("/api/symonscope/units")


def test_components_lists_what_is_unprovisioned(client):
    r = client.get("/api/fabric/components", headers=auth())
    b = r.json()
    assert "unprovisioned" in b and isinstance(b["unprovisioned"], list)
    assert b["source"].endswith("control.board")


def test_the_board_route_reports_the_ports_it_read(client):
    r = client.get("/api/fabric/board", headers=auth())
    assert r.status_code == 200 and "gateway" in r.json()["ports"]
