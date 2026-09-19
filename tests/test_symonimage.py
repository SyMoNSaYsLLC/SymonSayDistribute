# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonimage tests. Almost all of them are about refusing, because the one thing this unit must
never do is start a generation that cannot finish on a card somebody else is using."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from symonimage import imager as R

TOKEN = uuid.uuid4().hex


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard.
    # On a loopback bind the guard returns before comparing anything, which would
    # make every authenticated test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_IMAGE_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_IMAGE_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- the card is shared, and that is the whole design -------------------------------------
def test_room_names_the_process_holding_the_card():
    r = R.room()
    assert "need_gib" in r and "have_gib" in r
    if not r["enough"]:
        assert "do not co-fit" in r["why"]
        assert r["shortfall_gib"] > 0


def test_generate_refuses_when_there_is_not_room_rather_than_starting(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "room", lambda **kw: {
        "enough": False, "why": "11.8 GiB of weights against 0.5 GiB free; X holds it. "
                                "One card: these do not co-fit"})
    with pytest.raises(R.ImageError, match="do not co-fit"):
        R.generate(prompt="a cat", out_path=str(tmp_path / "x.png"), steps=4,
                   width=256, height=256)


def test_the_room_check_can_be_skipped_only_explicitly(monkeypatch, tmp_path):
    """Skipping is available for an operator who knows the card is theirs, but it is never the
    default — the default must be the safe one, because the unsafe one wastes somebody's card."""
    import inspect
    sig = inspect.signature(R.generate)
    assert sig.parameters["skip_room_check"].default is False


# --- nothing that decides what the card does has a default ---------------------------------
@pytest.mark.parametrize("field", ["steps", "width", "height"])
def test_the_generation_shape_has_no_default(field):
    import inspect
    sig = inspect.signature(R.generate)
    assert sig.parameters[field].default is inspect.Parameter.empty, \
        f"{field} has a default; it decides what the card is asked to do"


@pytest.mark.parametrize("bad", [{"steps": 0}, {"width": 0}, {"height": -1}])
def test_a_non_positive_shape_is_refused(bad, monkeypatch, tmp_path):
    monkeypatch.setattr(R, "room", lambda **kw: {"enough": True, "why": ""})
    args = {"prompt": "x", "out_path": str(tmp_path / "x.png"), "steps": 4,
            "width": 64, "height": 64}
    args.update(bad)
    with pytest.raises(R.ImageError, match="must be positive"):
        R.generate(**args)


def test_an_empty_prompt_generates_nothing(tmp_path):
    with pytest.raises(R.ImageError, match="generates nothing"):
        R.generate(prompt="   ", out_path=str(tmp_path / "x.png"), steps=4,
                   width=64, height=64)


# --- the prompt never reaches a shell ----------------------------------------------------------
def test_the_runtime_is_invoked_with_an_argument_vector_never_a_shell():
    import inspect
    src = inspect.getsource(R.generate)
    assert "shell=True" not in src, "a prompt that reaches a shell is a prompt that is a command"
    assert "argv" in src


# --- it reads the real runtime and the real store ------------------------------------------------
def test_the_runtime_reports_a_version_and_a_commit():
    v = R.version()
    assert v["version"] and v["commit"], "the runtime did not identify itself"


def test_the_commit_is_the_one_pinned_in_the_source_tree():
    from pathlib import Path
    import json
    pin = Path("/mnt/SymonSaySource/diffuse/pins/stable-diffusion.cpp.json")
    if not pin.is_file():
        pytest.skip("no pin on this host")
    want = json.loads(pin.read_text())
    rev = str(want.get("intended_revision") or want.get("revision") or "")
    if not rev:
        pytest.skip("the pin records no revision")
    assert R.version()["commit"] in rev or rev.startswith(R.version()["commit"])


def test_the_weights_are_complete_and_carry_their_licence():
    w = R.weights()
    assert w["complete"] is True, w["why"]
    assert w["licence"] is True, "the licence text is not carried with the weights"


def test_a_missing_binary_is_named_rather_than_failing_later(monkeypatch, tmp_path):
    monkeypatch.setenv("SYM_IMAGE_BIN", str(tmp_path / "not-here"))
    with pytest.raises(R.ImageError, match="no image runtime at"):
        R.binary()


def test_a_missing_store_is_named(monkeypatch, tmp_path):
    monkeypatch.setenv("SYM_IMAGE_STORE", str(tmp_path / "nope"))
    with pytest.raises(R.ImageError, match="no model store at"):
        R.store()


# --- over http --------------------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    """Off-loopback the bind is reachable, so the token is required and an unset one closes the
    unit: becoming reachable through a config change must not make it public through that same
    change. The host is set before the reload so the guard is in its off-loopback mode."""
    monkeypatch.setenv("SYM_IMAGE_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_IMAGE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonimage/health").status_code == 200
    assert c.get("/api/symonimage/room").status_code == 503


def test_loopback_needs_no_token(monkeypatch):
    """The other half of the contract: on the loopback default no token is asked for, because a
    token on a 127.0.0.1 bind defends only against a caller who could already read the token."""
    monkeypatch.delenv("SYM_IMAGE_HOST", raising=False)
    monkeypatch.delenv("SYM_IMAGE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonimage/health").status_code == 200
    assert c.get("/api/symonimage/room").status_code == 200, \
        "a loopback bind must not refuse a caller over a token it cannot justify asking for"


def test_ready_reports_everything_generate_would_check_without_generating(client):
    r = client.get("/api/symonimage/ready", headers=auth())
    assert r.status_code == 200
    b = r.json()
    assert set(b) >= {"runtime", "weights", "room", "ready", "blocked_on"}
    if not b["ready"]:
        assert b["blocked_on"], "not ready but nothing named as blocking"
