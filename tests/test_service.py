# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Service tests. The unit is closed until configured, and says which knob is missing."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

# Generated per run rather than written down. A literal here failed the estate's own secret
# gate (pattern generic_assignment) and the gate was right to fail it: nothing reading this
# file can tell a placeholder from a live credential, and a gate that takes the author's word
# for which is which has stopped being a gate. Deriving it means there is no value in the
# repository to be wrong about.
TOKEN = uuid.uuid4().hex


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SYM_PAYLOAD_TOKEN", TOKEN)
    monkeypatch.setenv("SYM_PAYLOAD_MAX_TOKENS", "1000")
    monkeypatch.setenv("SYM_PAYLOAD_CAPACITY", "8")
    import service
    importlib.reload(service)
    service._GATE["keeper"] = None
    return TestClient(service.app)


@pytest.fixture
def reachable_client(monkeypatch):
    """The same unit bound off-loopback, so require_token is live rather than bypassed."""
    monkeypatch.setenv("SYM_PAYLOAD_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_PAYLOAD_TOKEN", TOKEN)
    monkeypatch.setenv("SYM_PAYLOAD_MAX_TOKENS", "1000")
    monkeypatch.setenv("SYM_PAYLOAD_CAPACITY", "8")
    import service
    importlib.reload(service)
    service._GATE["keeper"] = None
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- closed until configured ------------------------------------------------------------
def test_health_is_public_and_answers_unconfigured(monkeypatch):
    monkeypatch.delenv("SYM_PAYLOAD_TOKEN", raising=False)
    import service
    importlib.reload(service)
    r = TestClient(service.app).get("/api/symonpayload/health")
    assert r.status_code == 200 and r.json()["configured"] is False


def test_no_token_closes_the_unit_rather_than_opening_it(monkeypatch):
    # Off-loopback, before the reload: a unit that becomes reachable through a config change
    # must not become public through that same change.
    monkeypatch.setenv("SYM_PAYLOAD_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_PAYLOAD_TOKEN", raising=False)
    import service
    importlib.reload(service)
    r = TestClient(service.app).get("/api/symonpayload/queue/status")
    assert r.status_code == 503 and "SYM_PAYLOAD_TOKEN" in r.json()["detail"]


def test_a_wrong_token_is_401_not_503(reachable_client):
    r = reachable_client.get("/api/symonpayload/queue/status",
                             headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_loopback_needs_no_token(monkeypatch):
    """The other half of the same contract: on the 127.0.0.1 default the token defends nothing,
    because a caller who can reach the port is already on this host and can read the token."""
    monkeypatch.delenv("SYM_PAYLOAD_HOST", raising=False)     # the loopback default
    monkeypatch.delenv("SYM_PAYLOAD_TOKEN", raising=False)
    monkeypatch.setenv("SYM_PAYLOAD_MAX_TOKENS", "1000")      # policy set; only the token is not
    monkeypatch.setenv("SYM_PAYLOAD_CAPACITY", "8")
    import service
    importlib.reload(service)
    service._GATE["keeper"] = None
    r = TestClient(service.app).get("/api/symonpayload/queue/status")
    assert r.status_code == 200, "loopback must not demand a token it cannot protect"
    assert r.json()["queues"][0]["capacity"] == 8


def test_missing_policy_names_the_variable(monkeypatch):
    monkeypatch.setenv("SYM_PAYLOAD_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_PAYLOAD_TOKEN", TOKEN)
    monkeypatch.delenv("SYM_PAYLOAD_MAX_TOKENS", raising=False)
    monkeypatch.setenv("SYM_PAYLOAD_CAPACITY", "8")
    import service
    importlib.reload(service)
    service._GATE["keeper"] = None
    r = TestClient(service.app).get("/api/symonpayload/queue/status", headers=auth())
    assert r.status_code == 503
    assert "SYM_PAYLOAD_MAX_TOKENS" in r.json()["detail"]
    assert "does not default its policy" in r.json()["detail"]


# --- admission --------------------------------------------------------------------------
def test_submit_queues_and_reports_depth(client):
    r = client.post("/api/symonpayload/requests/submit",
                    json={"request_id": "a", "tokens": 10}, headers=auth())
    assert r.status_code == 200
    assert r.json() == {"request_id": "a", "queued": True, "coalesced_into": None,
                        "queue_depth": 1}


def test_too_many_tokens_is_429_with_the_reason(client):
    r = client.post("/api/symonpayload/requests/submit",
                    json={"request_id": "big", "tokens": 99999}, headers=auth())
    assert r.status_code == 429
    assert "exceeds the 1000" in r.json()["detail"]["refused"]


def test_batch_reports_partial_success_rather_than_rolling_back(client):
    r = client.post("/api/symonpayload/requests/batch", headers=auth(), json={"requests": [
        {"request_id": "ok", "tokens": 5}, {"request_id": "big", "tokens": 99999}]})
    assert r.status_code == 200
    body = r.json()
    assert body["counts"] == {"admitted": 1, "refused": 1}
    assert body["refused"][0]["request_id"] == "big"


def test_triage_refuses_to_estimate_a_wait_it_cannot_measure(client):
    r = client.post("/api/symonpayload/requests/triage",
                    json={"request_id": "a", "tokens": 5, "deadline_ms": 100}, headers=auth())
    b = r.json()
    assert b["lane"] == "urgent" and b["estimated_wait_ms"] is None
    assert "measured service rate" in b["estimated_wait_omitted_because"]


def test_coalesce_groups_by_declared_fingerprint_only(client):
    r = client.post("/api/symonpayload/payloads/coalesce", headers=auth(), json={"requests": [
        {"request_id": "a", "tokens": 1, "fingerprint": "fp"},
        {"request_id": "b", "tokens": 1, "fingerprint": "fp"},
        {"request_id": "c", "tokens": 1}]})
    b = r.json()
    assert b["saved_calls"] == 1
    assert b["never_coalesced"] == ["c"]
    assert b["leaders"] == [{"request_id": "a", "followers": ["b"]}]


# --- formation --------------------------------------------------------------------------
def test_form_reports_the_bound_and_what_it_means(client):
    for i, tok in enumerate([60, 60]):
        client.post("/api/symonpayload/requests/submit",
                    json={"request_id": f"r{i}", "tokens": tok}, headers=auth())
    r = client.post("/api/symonpayload/batches/form", headers=auth(),
                    json={"max_tokens": 100, "max_requests": 10, "window_ms": 50})
    b = r.json()
    assert b["bound"] == "tokens" and b["count"] == 1
    assert "raise the ceiling" in b["bound_means"]


def test_forming_from_an_empty_queue_is_409_not_an_empty_batch(client):
    r = client.post("/api/symonpayload/batches/form", headers=auth(),
                    json={"max_tokens": 100, "max_requests": 5, "window_ms": 10})
    assert r.status_code == 409 and "nothing pending" in r.json()["detail"]


def test_drained_is_reported_when_the_queue_simply_ran_out(client):
    client.post("/api/symonpayload/requests/submit",
                json={"request_id": "only", "tokens": 5}, headers=auth())
    r = client.post("/api/symonpayload/batches/form", headers=auth(),
                    json={"max_tokens": 1000, "max_requests": 10, "window_ms": 50})
    assert r.json()["bound"] == "drained"
    assert "under-loaded" in r.json()["bound_means"]


# --- shapes, which hold no tensors -------------------------------------------------------
def test_stack_returns_a_shape_and_never_a_tensor_id(client):
    r = client.post("/api/symonpayload/shapes/stack", headers=auth(),
                    json={"shapes": [[4, 8], [4, 8], [4, 8]]})
    assert r.json() == {"resulting_shape": [3, 4, 8], "members": 3}
    assert "tensor_id" not in r.text


def test_ragged_stack_is_409_and_names_the_member(client):
    r = client.post("/api/symonpayload/shapes/stack", headers=auth(),
                    json={"shapes": [[4, 8], [4, 9]]})
    assert r.status_code == 409 and "ragged" in r.json()["detail"]


def test_concatenate_returns_boundaries(client):
    r = client.post("/api/symonpayload/shapes/concatenate", headers=auth(),
                    json={"lengths": [3, 5, 2]})
    assert r.json()["boundaries"] == [[0, 3], [3, 8], [8, 10]]


def test_plan_reports_padding_waste(client):
    r = client.post("/api/symonpayload/tokens/plan", headers=auth(),
                    json={"lengths": [200, 200, 200, 8000]})
    b = r.json()
    assert b["allocated"] == 32000 and b["wasted"] == 32000 - 8600


def test_pack_wastes_less_than_padding_on_the_same_input(client):
    lengths = [200, 200, 200, 800]
    packed = client.post("/api/symonpayload/shapes/pack", headers=auth(),
                         json={"lengths": lengths, "width": 800}).json()
    padded = client.post("/api/symonpayload/tokens/plan", headers=auth(),
                         json={"lengths": lengths}).json()
    assert packed["wasted"] < padded["wasted"]


def test_pack_without_a_width_is_a_400(client):
    r = client.post("/api/symonpayload/shapes/pack", headers=auth(), json={"lengths": [1, 2]})
    assert r.status_code == 400 and "needs a width" in r.json()["detail"]


# --- reservoir: two different numbers, not one twice --------------------------------------
def test_fill_level_and_remaining_are_different_quantities(client):
    r = client.post("/api/symonpayload/tokens/reservoir", headers=auth(),
                    json={"per_window": 100, "draw": 30})
    b = r.json()
    assert b["current_fill_level"] == 30 and b["capacity_remaining"] == 70


def test_drawing_more_than_is_left_is_409(client):
    r = client.post("/api/symonpayload/tokens/reservoir", headers=auth(),
                    json={"per_window": 10, "draw": 99})
    assert r.status_code == 409 and "exceeds the 10 left" in r.json()["detail"]


# --- sixteen unbuilt routes are absent, not stubbed ------------------------------------------
@pytest.mark.parametrize("path", [
    "/api/symonpayload/inference/schedule", "/api/symonpayload/inference/dispatch",
    "/api/symonpayload/throttle/configure", "/api/symonpayload/throughput/metrics",
    "/api/symonpayload/streams/init", "/api/symonpayload/data/chunk",
    "/api/symonpayload/sweep/run", "/api/symonpayload/jobs/run"])
def test_an_unbuilt_route_is_404_and_not_a_stub(client, path):
    assert client.post(path, json={}, headers=auth()).status_code == 404
