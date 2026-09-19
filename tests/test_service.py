# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The board over HTTP. The tests that matter are the ones about what it refuses to say."""
import os, pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

os.environ["SYM_BOARD_TOKEN"] = "test-token-not-a-credential"
import service

C = TestClient(service.app)
AUTH = {"authorization": "Bearer test-token-not-a-credential"}


def test_health_is_public_and_answers_unconfigured():
    r = C.get("/api/board/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_every_other_route_refuses_without_a_credential():
    for p in ("/api/board/sections", "/api/board/settings", "/api/board/live",
              "/api/board/diff", "/api/board/check", "/api/board/client"):
        assert C.get(p).status_code in (401, 403), p


def test_unconfigured_fails_closed_rather_than_open():
    saved = os.environ.pop("SYM_BOARD_TOKEN")
    try:
        r = C.get("/api/board/sections", headers=AUTH)
        assert r.status_code == 503, "a board with no token must refuse, never answer freely"
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
