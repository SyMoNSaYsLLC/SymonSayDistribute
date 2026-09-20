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


# --- §3.1b-iii: a probe whose own inputs can move underneath it reports yesterday's machine --
# The pin census lives in runtime.py, not in a module of its own: `pins.py` in two
# components is what no-divergent-copy refuses, and every unit here keeps its own
# comparison inside its own uniquely named domain module.
P = R


def test_everything_this_probe_reads_a_version_of_has_a_row():
    """Nothing may be omitted. nvidia-smi, torch, vLLM, the CUDA toolkit and the interpreter
    are each either asserted against a pin or named as having none."""
    p = P.pinned(VLLM_VENV)
    assert p["count"] == len(P.INVOKED) == 5
    assert {r["program"] for r in p["programs"]} == {"nvidia-smi", "torch", "vllm", "cuda",
                                                     "python"}
    for r in p["programs"]:
        assert r["state"] in ("MATCHES", "DRIFT-RECORDED", "DRIFT-NEW", "UNRESOLVED-PIN",
                              "UNREADABLE", "NO-PIN"), r
        assert r["where"] and r["why"] and r["pin_note"], r


def test_nothing_this_probe_rests_on_has_moved_since_it_was_recorded():
    """THE assertion §3.1b-iii asks for. `fit()` answers `runs_here` from a compiled arch list
    belonging to one torch, and `parsers()` returns names belonging to one vLLM. If either
    moves unrecorded, this fails here rather than in somebody's serving decision."""
    p = P.pinned(VLLM_VENV)
    assert p["new_drift"] == [], "; ".join(
        r["why"] for r in p["programs"] if r["state"] == "DRIFT-NEW")


def test_the_driver_this_card_runs_is_the_one_the_estate_pinned():
    """The row that genuinely agrees, asserted by running nvidia-smi rather than by recording
    what it once said. Not vacuous: it fails if the driver is upgraded without the pin."""
    r = next(x for x in P.pinned(VLLM_VENV)["programs"] if x["program"] == "nvidia-smi")
    if r["state"] == "UNREADABLE" and "could not run" in r["reports"]:
        pytest.skip("no nvidia-smi on this host")
    assert r["pin_file"] and r["pin_file"].startswith("/mnt/SymonSaySource")
    assert r["observed"] and r["state"] == "MATCHES", r["why"]
    # and it is the same string devices() serves, not a second reading of a different thing
    assert D.devices()[0]["driver_version"] == r["reports"]


def test_the_build_drift_that_exists_today_is_carried_rather_than_hidden():
    """A pin records the INTENDED revision, the checkout the OBSERVED one, and the
    disagreement is preserved. This also stops the test above passing vacuously: if nothing
    ever disagreed, `new_drift == []` would prove only that nothing is compared."""
    rows = {r["program"]: r for r in P.pinned(VLLM_VENV)["programs"]}
    for name in ("torch", "vllm"):
        r = rows[name]
        assert r["state"] == "DRIFT-RECORDED", r
        assert r["pinned"] and r["observed"] and r["pinned"] != r["observed"], r
        assert "2026-09-20" in r["why"], "a carried drift must say when it was recorded"


def test_an_unrecorded_movement_is_caught(monkeypatch):
    """The partner to the tests above: with one KNOWN_DRIFT entry removed the same host must
    come back DRIFT-NEW naming both versions."""
    monkeypatch.setattr(P, "KNOWN_DRIFT",
                        {k: v for k, v in P.KNOWN_DRIFT.items() if k[0] != "torch"})
    p = P.pinned(VLLM_VENV)
    assert p["new_drift"] == ["torch"], p["by_state"]
    r = next(x for x in p["programs"] if x["program"] == "torch")
    assert r["pinned"] in r["why"] and r["observed"] in r["why"], r["why"]


def test_a_pin_that_names_no_version_is_never_reported_as_agreement(monkeypatch, tmp_path):
    """UNRESOLVED must not read as MATCHES — four of the 108 pins carry exactly that."""
    d = tmp_path / "platform" / "pins"
    d.mkdir(parents=True)
    (d / "open-gpu-kernel-modules.json").write_text(
        '{"component": "open-gpu-kernel-modules", "intended_tag_version": "UNRESOLVED"}')
    monkeypatch.setattr(P, "PIN_ROOT", str(tmp_path))
    r = next(x for x in P.pinned(VLLM_VENV)["programs"] if x["program"] == "nvidia-smi")
    assert r["state"] == "UNRESOLVED-PIN", r


def test_a_missing_pin_registry_does_not_look_like_agreement(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "PIN_ROOT", str(tmp_path / "absent"))
    p = P.pinned(VLLM_VENV)
    assert p["pins_available"] == 0
    assert "MATCHES" not in p["by_state"] and "DRIFT-RECORDED" not in p["by_state"]


def test_the_two_things_with_no_pin_are_named_as_gaps():
    """§3.1b-iii step 1: 'a component invoking something with no pin is naming a gap'. The
    CUDA toolkit and CPython are both absent from the 108, and this unit's own reason for
    existing is that the toolkit version is not the card's capability — so leaving the
    toolkit unrecorded is the sharpest gap here."""
    p = P.pinned(VLLM_VENV)
    assert set(p["unpinned"]) == {"cuda", "python"}, p["unpinned"]
    for r in p["programs"]:
        if r["state"] == "NO-PIN":
            assert r["pin"] is None and r["pin_file"] is None
            assert "GAP" in r["pin_note"] and "Closed by" in r["pin_note"]


def test_one_unreadable_source_does_not_silence_the_whole_census(tmp_path):
    """A venv with no importable vLLM must still yield a driver answer. A census that dies on
    the first failure turns one missing package into 'nothing is checked'."""
    p = P.pinned(tmp_path)          # not a venv at all
    assert p["count"] == len(P.INVOKED)
    driver = next(r for r in p["programs"] if r["program"] == "nvidia-smi")
    assert driver["state"] in ("MATCHES", "DRIFT-RECORDED", "DRIFT-NEW"), driver
    build_rows = [r for r in p["programs"] if r["program"] in ("torch", "vllm")]
    assert all(r["state"] == "UNREADABLE" for r in build_rows), build_rows


def test_pinned_is_routed(client):
    r = client.get(f"/api/symonprobe/pinned?venv={VLLM_VENV}", headers=auth())
    assert r.status_code == 200
    b = r.json()
    assert b["venv"] == VLLM_VENV and b["count"] == len(P.INVOKED)
    assert b["drift_policy"]
