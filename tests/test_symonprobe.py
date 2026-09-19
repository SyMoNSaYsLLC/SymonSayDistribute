# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonprobe tests. This reads real hardware, so they assert INVARIANTS and REFUSALS rather
than today's numbers — asserting 16303 MiB would fail the day the card changes, which is the
day the tests should still work."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from symonprobe import device as D
from symonprobe import runtime as R

TOKEN = uuid.uuid4().hex
VLLM_VENV = "/home/google/.venvs/vllm-0271-cu130"


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard.
    # On a loopback bind the guard returns before comparing anything, which would
    # make every authenticated test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_PROBE_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_PROBE_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- refusals ---------------------------------------------------------------------------
def test_a_directory_that_is_not_a_venv_is_refused(tmp_path):
    with pytest.raises(D.ProbeError, match="not a python environment"):
        D.build(tmp_path)


def test_a_venv_without_vllm_is_refused_by_name(tmp_path):
    (tmp_path / "bin").mkdir()
    with pytest.raises(D.ProbeError, match="not a python environment"):
        R.parsers(tmp_path)


def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    # The bind address decides. Bind wide BEFORE the reload: on a loopback bind the guard
    # returns early and the closure asserted below is never the code under test.
    monkeypatch.setenv("SYM_PROBE_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_PROBE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonprobe/health").status_code == 200
    r = c.get("/api/symonprobe/devices")
    assert r.status_code == 503 and "SYM_PROBE_TOKEN" in r.json()["detail"]


def test_loopback_needs_no_token(monkeypatch):
    """The other half of the same contract: on the loopback default there is no token to get
    wrong, because a key defends traffic that leaves this machine and loopback traffic does
    not leave it. Unset host AND unset token must still answer, or the provisioning step the
    guard exists to remove comes back."""
    monkeypatch.delenv("SYM_PROBE_HOST", raising=False)
    monkeypatch.delenv("SYM_PROBE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonprobe/devices").status_code == 200


def test_a_bad_venv_over_http_is_409_not_500(client):
    r = client.get("/api/symonprobe/build?venv=/nope/nothing", headers=auth())
    assert r.status_code == 409


def test_every_route_is_read_only(client):
    import service
    for rt in service.app.routes:
        if hasattr(rt, "methods") and str(rt.path).startswith("/api/symonprobe"):
            assert rt.methods <= {"GET", "HEAD"}, f"{rt.path} can do more than read"


# --- the distinction this unit exists for --------------------------------------------------
def test_compute_capability_is_labelled_as_silicon_not_as_cuda():
    for d in D.devices():
        assert "NOT a CUDA version" in d["compute_capability_is"]
        assert d["compute_capability_arch"].startswith("sm_")


def test_fit_reports_both_numbers_separately_and_says_they_differ():
    f = D.fit(VLLM_VENV)
    pair = f["these_are_not_the_same_number"]
    assert set(pair) >= {"compute_capability", "cuda_toolkit"}
    assert pair["compute_capability"] != pair["cuda_toolkit"]


def test_fit_decides_on_the_arch_list_and_not_on_the_venv_name():
    f = D.fit(VLLM_VENV)
    assert f["runs_here"] == (f["device_arch"] in f["build_arch_list"])


def test_a_build_missing_this_arch_would_be_reported_unfit(monkeypatch):
    monkeypatch.setattr(D, "build", lambda v: {"arch_list": ["sm_70"], "cuda_built_against": "13.0"})
    f = D.fit(VLLM_VENV)
    assert f["runs_here"] is False
    assert "cannot run here regardless of the CUDA version" in f["why"]


# --- parser discovery ------------------------------------------------------------------------
def test_registered_names_are_found_and_are_not_file_names():
    p = R.parsers(VLLM_VENV)
    assert p["counts"]["tool_call"] > 0 and p["counts"]["reasoning"] > 0
    assert not any(n.endswith("_tool_parser") for n in p["tool_call_parsers"])


def test_suggest_offers_candidates_and_refuses_to_call_them_an_answer():
    s = R.suggest(VLLM_VENV, "/mnt/models/symon")
    assert "candidates" in s and "caveat" in s
    assert "not an answer" in s["caveat"]


def test_a_candidate_is_only_offered_if_the_runtime_actually_registers_it():
    s = R.suggest(VLLM_VENV, "/mnt/models/symon")
    for kind, key in (("tool_call", "tool_call_parser"), ("reasoning", "reasoning_parser")):
        got = s["candidates"][key]
        if got is not None:
            assert got in s["available"][kind]


# --- shape --------------------------------------------------------------------------------------
def test_venvs_are_found_and_each_reports_whether_it_has_an_interpreter():
    rows = R.venvs()
    assert rows and all("has_python" in v for v in rows)


def test_packages_can_be_filtered(client):
    r = client.get(f"/api/symonprobe/packages?venv={VLLM_VENV}&contains=torch", headers=auth())
    assert r.status_code == 200
    assert all("torch" in p["name"].lower() for p in r.json()["packages"])
