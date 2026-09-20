# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonengine tests. Invariants and refusals, not today's counts — asserting 367
architectures would fail the day vllm is upgraded, which is the day this should still work."""
import importlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from symonengine import capability as C

TOKEN = uuid.uuid4().hex
VENV = "/home/google/.venvs/vllm-0271-cu130"
SYMON = "/mnt/models/symon"


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard.
    # On a loopback bind the guard returns before comparing anything, which would
    # make every authenticated test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_ENGINE_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_ENGINE_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- refusals -----------------------------------------------------------------------
def test_a_directory_that_is_not_an_environment_is_refused(tmp_path):
    with pytest.raises(C.CapabilityError, match="not a python environment"):
        C.surface(tmp_path)


def test_a_checkpoint_with_no_config_cannot_be_answered_for(tmp_path):
    with pytest.raises(C.CapabilityError, match="has no config.json"):
        C.serves(VENV, tmp_path)


def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    # The bind address decides. Bind wide BEFORE the reload: on a loopback bind the guard
    # returns early and the closure asserted below is never the code under test.
    monkeypatch.setenv("SYM_ENGINE_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_ENGINE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonengine/health").status_code == 200
    assert c.get("/api/symonengine/surface").status_code == 503


def test_loopback_needs_no_token(monkeypatch):
    """The other half of the same contract: on the loopback default there is no token to get
    wrong, because a key defends traffic that leaves this machine and loopback traffic does
    not leave it. Unset host AND unset token must still answer, or the provisioning step the
    guard exists to remove comes back."""
    monkeypatch.delenv("SYM_ENGINE_HOST", raising=False)
    monkeypatch.delenv("SYM_ENGINE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonengine/surface").status_code == 200


def test_asking_supports_nothing_is_a_400(client):
    assert client.get("/api/symonengine/supports", headers=auth()).status_code == 400


def test_every_route_is_read_only(client):
    import service
    for r in service.app.routes:
        if hasattr(r, "methods") and str(r.path).startswith("/api/symonengine"):
            assert r.methods <= {"GET", "HEAD"}


# --- a feature flag must say where it looked ------------------------------------------
def test_every_feature_records_the_paths_it_looked_in():
    s = C.surface(VENV)
    for name, v in s["features"].items():
        assert "looked_in" in v and v["looked_in"], name
        if v["present"]:
            assert v["found_at"] in v["looked_in"]


def test_a_feature_that_moved_is_still_found():
    # These moved to vllm.v1.* in 0.27.1. A probe naming one path reported them absent.
    s = C.surface(VENV)
    for name in ("prefix_caching", "speculative_decoding", "structured_outputs"):
        assert s["features"][name]["present"] is True, f"{name} reported absent"
        assert len(s["features"][name]["looked_in"]) > 1


# --- the surface is read, not remembered -------------------------------------------------
def test_the_surface_names_how_it_was_obtained():
    s = C.surface(VENV)
    assert "asked of the installed package" in s["read_how"]


def test_parsers_are_deferred_rather_than_duplicated():
    s = C.surface(VENV)
    assert "symonprobe" in s["parsers"]["where"]
    assert "disagree" in s["parsers"]["why_not_here"]


def test_counts_match_the_lists_they_count():
    s = C.surface(VENV)
    assert s["counts"]["architectures"] == len(s["architectures"])
    assert s["counts"]["quantization"] == len(s["quantization"])


# --- serves ---------------------------------------------------------------------------------
def test_this_build_serves_symon_and_says_why():
    r = C.serves(VENV, SYMON)
    assert r["serves"] is True
    assert r["architectures_declared"] == r["architectures_supported"]
    assert r["quantization_supported"] is True


def test_an_unsupported_architecture_is_refused_with_the_registry_size(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(
        {"architectures": ["NotARealArchitectureForCausalLM"]}))
    r = C.serves(VENV, tmp_path)
    assert r["serves"] is False
    assert "not in this build's registry" in r["why"]


def test_an_unsupported_quantization_is_refused_by_name(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(
        {"architectures": ["GptOssForCausalLM"],
         "quantization_config": {"quant_method": "not-a-real-method"}}))
    r = C.serves(VENV, tmp_path)
    assert r["serves"] is False and "not-a-real-method" in r["why"]


def test_a_checkpoint_declaring_nothing_is_not_approved_by_silence(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    r = C.serves(VENV, tmp_path)
    assert r["serves"] is None
    assert "declares no architecture" in r["why"]


def test_serves_says_what_it_did_not_check():
    r = C.serves(VENV, SYMON)
    joined = " ".join(r["not_checked"])
    assert "FITS the card" in joined and "model-store" in joined


# --- §3.1b-iii: a build invoked without a recorded version is invoked blind ------------------
# The pin census lives in capability.py, not in a module of its own: `pins.py` in two
# components is what no-divergent-copy refuses, and every unit here keeps its own
# comparison inside its own uniquely named domain module.
P = C


def test_every_thing_this_unit_reads_a_version_of_has_a_row():
    """Nothing may be omitted. Each of vllm, torch and the interpreter is either asserted
    against a pin or named as having none; a program left out reads as one with nothing to
    check, which is the blind invocation the rule forbids."""
    p = P.pinned(VENV)
    assert p["count"] == len(P.INVOKED) == 3
    assert {r["program"] for r in p["programs"]} == {"vllm", "torch", "python"}
    for r in p["programs"]:
        assert r["state"] in ("MATCHES", "DRIFT-RECORDED", "DRIFT-NEW", "UNRESOLVED-PIN",
                              "UNREADABLE", "NO-PIN"), r
        assert r["where"] and r["why"] and r["pin_note"], r


def test_nothing_has_moved_since_it_was_recorded():
    """THE assertion §3.1b-iii asks for. `surface()` reports 367 architectures and 31
    quantization methods; every one of those numbers belongs to a specific vLLM. If that vLLM
    moves and nobody records it, this fails — which is the whole point, because otherwise the
    first person to notice is somebody whose serving decision was made from stale counts."""
    p = P.pinned(VENV)
    assert p["new_drift"] == [], "; ".join(
        r["why"] for r in p["programs"] if r["state"] == "DRIFT-NEW")


def test_the_drift_that_exists_today_is_carried_rather_than_hidden():
    """A pin records the INTENDED revision, the checkout the OBSERVED one, and where they
    disagree the disagreement is preserved. Not vacuous: this asserts the drift is REPORTED
    with both versions, so `new_drift == []` above cannot be passing because nothing compares.

    If this ever fails because the venv and the pins have come to agree, that is a real change
    and the KNOWN_DRIFT entry should be deleted rather than this test weakened."""
    rows = {r["program"]: r for r in P.pinned(VENV)["programs"]}
    for name in ("vllm", "torch"):
        r = rows[name]
        assert r["state"] == "DRIFT-RECORDED", r
        assert r["pinned"] and r["observed"] and r["pinned"] != r["observed"], r
        assert r["pin_file"] and r["pin_file"].startswith("/mnt/SymonSaySource"), r
        assert "2026-09-20" in r["why"], "a carried drift must say when it was recorded"


def test_an_unrecorded_movement_is_caught(monkeypatch):
    """The partner to the two tests above. With one KNOWN_DRIFT entry removed, the SAME build
    must come back DRIFT-NEW naming both versions — otherwise DRIFT-RECORDED proves only that
    this classifies everything as expected."""
    trimmed = {k: v for k, v in P.KNOWN_DRIFT.items() if k[0] != "vllm"}
    monkeypatch.setattr(P, "KNOWN_DRIFT", trimmed)
    p = P.pinned(VENV)
    assert p["new_drift"] == ["vllm"], p["by_state"]
    r = next(x for x in p["programs"] if x["program"] == "vllm")
    assert r["state"] == "DRIFT-NEW"
    assert r["pinned"] in r["why"] and r["observed"] in r["why"], r["why"]


def test_a_pin_that_names_no_version_is_never_reported_as_agreement(monkeypatch, tmp_path):
    """UNRESOLVED must not read as MATCHES. adaptive-fabric/pins/torch-2.11.x.json is exactly
    such a pin, and a comparison that treated 'no version recorded' as 'the version agrees'
    would launder it into a pass."""
    pins = tmp_path / "llm" / "pins"
    pins.mkdir(parents=True)
    (pins / "vllm.json").write_text(
        '{"component": "vllm", "intended_tag_version": "UNRESOLVED"}')
    monkeypatch.setattr(P, "PIN_ROOT", str(tmp_path))
    r = next(x for x in P.pinned(VENV)["programs"] if x["program"] == "vllm")
    assert r["state"] == "UNRESOLVED-PIN", r


def test_a_missing_pin_registry_does_not_look_like_agreement(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "PIN_ROOT", str(tmp_path / "absent"))
    p = P.pinned(VENV)
    assert p["pins_available"] == 0
    assert "MATCHES" not in p["by_state"] and "DRIFT-RECORDED" not in p["by_state"], p["by_state"]


def test_the_interpreter_has_no_pin_and_says_so():
    """§3.1b-iii step 1: 'a component invoking something with no pin is naming a gap'. None of
    the 108 pins is CPython, and this must report that rather than skip the row."""
    r = next(x for x in P.pinned(VENV)["programs"] if x["program"] == "python")
    assert r["state"] == "NO-PIN" and r["pin"] is None and r["pin_file"] is None
    assert "GAP" in r["pin_note"] and "Closed by" in r["pin_note"]
    assert r["reports"], "the interpreter was not asked what version it is"


def test_a_local_build_tag_is_not_treated_as_a_release_difference():
    """torch reports 2.13.0+cu130. The +cu130 is a build tag, not a release, and comparing the
    raw strings would report drift on every CUDA-built wheel forever."""
    assert P._norm("2.13.0+cu130") == "2.13.0"
    assert P._norm("v0.29.0") == "0.29.0"
    assert P._norm("no version here") == ""


def test_pinned_is_routed_and_answers_for_the_venv_it_is_given(client):
    r = client.get("/api/symonengine/pinned", headers=auth())
    assert r.status_code == 200
    b = r.json()
    assert b["venv"] == "/home/google/.venvs/vllm-0271-cu130"
    assert b["count"] == len(P.INVOKED)
    assert b["drift_policy"]
