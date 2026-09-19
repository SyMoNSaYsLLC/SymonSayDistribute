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
