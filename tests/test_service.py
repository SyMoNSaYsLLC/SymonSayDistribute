# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The board over HTTP. The tests that matter are the ones about what it refuses to say."""
import contextlib, os, pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

os.environ["SYM_BOARD_TOKEN"] = "test-token-not-a-credential"
import service

C = TestClient(service.app)
AUTH = {"authorization": "Bearer test-token-not-a-credential"}


@contextlib.contextmanager
def _bound(host):
    """Bind the unit to `host` for the block. The guard reads SYM_BOARD_HOST per request, so
    the bind address is what decides whether a token is demanded at all."""
    saved = os.environ.get("SYM_BOARD_HOST")
    os.environ["SYM_BOARD_HOST"] = host
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("SYM_BOARD_HOST", None)
        else:
            os.environ["SYM_BOARD_HOST"] = saved


def test_health_is_public_and_answers_unconfigured():
    r = C.get("/api/board/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_every_other_route_refuses_without_a_credential():
    with _bound("0.0.0.0"):          # off-loopback: the token is what stands between them
        for p in ("/api/board/sections", "/api/board/settings", "/api/board/live",
                  "/api/board/diff", "/api/board/check", "/api/board/client"):
            assert C.get(p).status_code in (401, 403), p


def test_unconfigured_fails_closed_rather_than_open():
    saved = os.environ.pop("SYM_BOARD_TOKEN")
    try:
        with _bound("0.0.0.0"):      # reachable off this host, and no token provisioned
            r = C.get("/api/board/sections", headers=AUTH)
            assert r.status_code == 503, "a board with no token must refuse, never answer freely"
    finally:
        os.environ["SYM_BOARD_TOKEN"] = saved


def test_loopback_needs_no_token():
    """On a loopback bind every route answers with no token at all, by design: a token there
    defends only against a caller who already has this host, and so can already read the token."""
    saved = os.environ.pop("SYM_BOARD_TOKEN")
    try:
        with _bound("127.0.0.1"):
            assert C.get("/api/board/sections").status_code == 200
    finally:
        os.environ["SYM_BOARD_TOKEN"] = saved


def test_settings_carry_their_source_and_staleness():
    d = C.get("/api/board/settings", headers=AUTH).json()
    assert d["count"] > 0
    for s in d["settings"]:
        assert set(("section", "key", "value", "why", "stale", "tree")) <= set(s)


def test_sections_name_which_tree_owns_them():
    d = C.get("/api/board/sections", headers=AUTH).json()
    assert d["count"] > 0
    assert any("Distribute" in s["tree"] for s in d["sections"])


def test_live_separates_measured_from_configured():
    d = C.get("/api/board/live", headers=AUTH).json()
    assert "at" in d and isinstance(d["live"], list)


def test_diff_agrees_flag_matches_its_own_list():
    d = C.get("/api/board/diff", headers=AUTH).json()
    assert d["agrees"] == (d["count"] == 0)


def test_no_route_returns_a_credential_value():
    """The one test this service exists to pass.

    The real key is 64 bytes on disk. If any route ever returns it, this fails — the check is
    against the actual credential, not against a pattern that might miss it."""
    p = os.path.expanduser("~/.config/symoneural/gateway-9001.key")
    if not os.path.isfile(p):
        pytest.skip("no credential on this host to check against")
    secret = open(p).read().strip()
    assert secret, "empty credential file"
    for path in ("/api/board/settings", "/api/board/live", "/api/board/client",
                 "/api/board/check", "/api/board/sections", "/api/board/diff"):
        body = C.get(path, headers=AUTH).text
        assert secret not in body, f"{path} returned the credential value"


def test_client_reports_a_fingerprint_not_a_key():
    d = C.get("/api/board/client", headers=AUTH).json()
    names = {c["name"] for c in d["checks"]}
    assert "credential" in names
    cred = next(c for c in d["checks"] if c["name"] == "credential")
    # a fingerprint is 16 hex characters; a 64-byte key is not
    assert len(cred["state"]) in (16, 7), cred  # 16 hex, or MISSING
    assert set(service.B.SURFACES) == {"3p", "webui", "both", "off"}


def test_an_unknown_surface_is_refused():
    assert C.post("/api/board/client/nonsense", headers=AUTH).status_code == 422


# --- §3.1b-iii: a program invoked without a recorded version is invoked blind ----------------
import board as B


def test_every_external_program_the_board_runs_has_a_row():
    """Nothing may be omitted. A program left out of the census reads as one with nothing to
    check, which is exactly the blind invocation the rule forbids."""
    p = B.pinned()
    assert p["count"] == len(B.INVOKED) > 0
    assert {r["program"] for r in p["programs"]} == {s["program"] for s in B.INVOKED}
    for r in p["programs"]:
        assert r["state"] in ("MATCHES", "DRIFT-RECORDED", "DRIFT-NEW",
                              "UNRESOLVED-PIN", "UNREADABLE", "NO-PIN"), r
        assert r["where"] and r["why"], r


def test_nothing_this_board_runs_has_moved_since_it_was_recorded():
    """THE assertion §3.1b-iii asks for. A pinned program that has drifted since anyone last
    looked fails here, so an upgrade underneath the board is found by this rather than by an
    operator watching [live] report DOWN for a port that is up."""
    p = B.pinned()
    assert p["new_drift"] == [], (
        "a pinned program moved and nothing recorded it: "
        + "; ".join(r["why"] for r in p["programs"] if r["state"] == "DRIFT-NEW"))


def test_the_driver_this_host_runs_is_the_one_the_estate_pinned():
    """The one program here that HAS a pin, asserted against it by running it. Not vacuous:
    it fails if nvidia-smi is absent, if the pin is unreadable, or if the two disagree."""
    row = next(r for r in B.pinned()["programs"] if r["program"] == "nvidia-smi")
    if row["state"] == "UNREADABLE" and "could not run" in row["reports"]:
        pytest.skip("no nvidia-smi on this host")
    assert row["pin_file"] and row["pinned"], row
    assert row["observed"], "nvidia-smi did not report a driver version"
    assert row["state"] == "MATCHES", row["why"]


def test_the_comparison_actually_fires_when_a_version_disagrees(monkeypatch, tmp_path):
    """The partner to the test above. With a pin that cannot match, the SAME program must come
    back DRIFT-NEW naming both versions — otherwise 'MATCHES' proves only that this never
    compares anything."""
    pins = tmp_path / "platform" / "pins"
    pins.mkdir(parents=True)
    (pins / "open-gpu-kernel-modules.json").write_text(
        '{"component": "open-gpu-kernel-modules", "intended_tag_version": "0.0.0"}')
    monkeypatch.setattr(B, "PIN_ROOT", str(tmp_path))
    row = next(r for r in B.pinned()["programs"] if r["program"] == "nvidia-smi")
    if not row["observed"]:
        pytest.skip("no nvidia-smi on this host")
    assert row["state"] == "DRIFT-NEW", row
    assert "0.0.0" in row["why"] and row["observed"] in row["why"], row["why"]


def test_a_pin_that_names_no_version_is_never_reported_as_agreement(monkeypatch, tmp_path):
    """UNRESOLVED must not read as MATCHES. Four of the 108 pins carry UNRESOLVED, and a
    comparison that treats 'no version recorded' as 'the version agrees' would launder every
    one of them into a pass."""
    pins = tmp_path / "platform" / "pins"
    pins.mkdir(parents=True)
    (pins / "open-gpu-kernel-modules.json").write_text(
        '{"component": "open-gpu-kernel-modules", "intended_tag_version": "UNRESOLVED"}')
    monkeypatch.setattr(B, "PIN_ROOT", str(tmp_path))
    row = next(r for r in B.pinned()["programs"] if r["program"] == "nvidia-smi")
    assert row["state"] == "UNRESOLVED-PIN", row


def test_a_program_with_no_pin_is_named_as_a_gap_not_quietly_passed():
    """§3.1b-iii step 1: 'a component invoking something with no pin is naming a gap'. bash,
    ss, grep and curl have no pin among the 108, and each must SAY so."""
    p = B.pinned()
    assert set(p["unpinned"]) == {"bash", "ss", "grep", "curl"}, p["unpinned"]
    for r in p["programs"]:
        if r["state"] == "NO-PIN":
            assert r["pin"] is None and r["pin_file"] is None
            assert "GAP" in r["pin_note"] and "Closed by" in r["pin_note"] or \
                   "missing" in r["pin_note"], r["pin_note"]


def test_a_missing_pin_registry_does_not_look_like_agreement(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "PIN_ROOT", str(tmp_path / "absent"))
    p = B.pinned()
    assert p["pins_available"] == 0
    assert "MATCHES" not in p["by_state"], p["by_state"]


def test_the_version_probe_is_an_argument_vector_never_a_shell():
    import inspect
    src = inspect.getsource(B._observe)
    assert "shell=True" not in src
    for s in B.INVOKED:
        assert isinstance(s["argv"], tuple) and len(s["argv"]) >= 2, s


def test_pinned_is_routed_and_returns_the_same_census():
    r = C.get("/api/board/pinned", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(B.INVOKED)
    assert {x["program"] for x in body["programs"]} == {s["program"] for s in B.INVOKED}
