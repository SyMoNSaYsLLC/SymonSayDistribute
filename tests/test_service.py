# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The store surface. What matters is that it never claims a model is sound without checking."""
import contextlib, json, os, pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

os.environ["SYM_STORE_TOKEN"] = "test-token-not-a-credential"
import service
from store import inspect as S

C = TestClient(service.app)
AUTH = {"authorization": "Bearer test-token-not-a-credential"}
REAL = os.path.isdir("/mnt/models/symon")


@contextlib.contextmanager
def _bound(host):
    """Bind the unit to `host` for the block. The guard reads SYM_STORE_HOST per request, so
    the bind address is what decides whether a token is demanded at all."""
    saved = os.environ.get("SYM_STORE_HOST")
    os.environ["SYM_STORE_HOST"] = host
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("SYM_STORE_HOST", None)
        else:
            os.environ["SYM_STORE_HOST"] = saved


def test_health_is_public():
    assert C.get("/api/store/health").status_code == 200


def test_everything_else_needs_a_credential():
    with _bound("0.0.0.0"):          # off-loopback: the token is what stands between them
        for p in ("/api/store/where", "/api/store/models"):
            assert C.get(p).status_code in (401, 403), p


def test_unconfigured_fails_closed():
    saved = os.environ.pop("SYM_STORE_TOKEN")
    try:
        with _bound("0.0.0.0"):      # reachable off this host, and no token provisioned
            assert C.get("/api/store/where", headers=AUTH).status_code == 503
    finally:
        os.environ["SYM_STORE_TOKEN"] = saved


def test_loopback_needs_no_token():
    """On a loopback bind every route answers with no token at all, by design: a token there
    defends only against a caller who already has this host, and so can already read the token."""
    saved = os.environ.pop("SYM_STORE_TOKEN")
    try:
        with _bound("127.0.0.1"):
            assert C.get("/api/store/where").status_code == 200
    finally:
        os.environ["SYM_STORE_TOKEN"] = saved


def test_where_reports_disk_or_says_why_not(tmp_path, monkeypatch):
    monkeypatch.setenv("SYM_MODELS_DIR", "/dev/shm")
    d = C.get("/api/store/where", headers=AUTH).json()
    assert d["is_disk"] is False, "tmpfs must never be reported as disk"
    assert d["why"], "a refusal must say why"


def test_a_missing_model_is_404_on_every_route():
    assert C.get("/api/store/models/nope", headers=AUTH).status_code == 404
    assert C.post("/api/store/models/nope/verify", headers=AUTH).status_code == 404


def test_a_model_without_a_manifest_is_named_as_unverifiable(tmp_path, monkeypatch):
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "weights.bin").write_bytes(b"x")
    monkeypatch.setenv("SYM_MODELS_DIR", str(tmp_path))
    d = C.get("/api/store/models", headers=AUTH).json()
    assert "bare" in d["unverifiable"]
    row = next(r for r in d["models"] if r["name"] == "bare")
    assert row["manifest"] is False and "drifted" in row["why"]


def test_verify_separates_moved_from_gone_from_untracked(tmp_path, monkeypatch):
    m = tmp_path / "m"; m.mkdir()
    (m / "a").write_text("one"); (m / "b").write_text("two")
    man = {"schema": "symoneural-model-store/1", "name": "m", "files": {
        "a": {"sha256": S.sha256(m / "a"), "bytes": 3},
        "b": {"sha256": S.sha256(m / "b"), "bytes": 3},
        "c": {"sha256": "0" * 64, "bytes": 0}}}
    (m / "MANIFEST.sha256.json").write_text(json.dumps(man))
    (m / "a").write_text("CHANGED")          # moved
    (m / "extra").write_text("x")            # untracked
    monkeypatch.setenv("SYM_MODELS_DIR", str(tmp_path))
    d = C.post("/api/store/models/m/verify", headers=AUTH).json()
    assert d["ok"] is False
    assert [x["file"] for x in d["moved"]] == ["a"]
    assert d["gone"] == ["c"]
    assert d["untracked"] == ["extra"]
    assert "drifted" in d["verdict"]


def test_verify_passes_only_when_every_digest_matches(tmp_path, monkeypatch):
    m = tmp_path / "ok"; m.mkdir()
    (m / "a").write_text("one")
    (m / "MANIFEST.sha256.json").write_text(json.dumps(
        {"name": "ok", "files": {"a": {"sha256": S.sha256(m / "a"), "bytes": 3}}}))
    monkeypatch.setenv("SYM_MODELS_DIR", str(tmp_path))
    d = C.post("/api/store/models/ok/verify", headers=AUTH).json()
    assert d["ok"] is True and d["checked"] == 1


@pytest.mark.skipif(not REAL, reason="no model in the real store")
def test_the_real_store_verifies():
    d = C.post("/api/store/models/symon/verify", headers=AUTH).json()
    assert d["ok"] is True, d
    assert d["checked"] == 12


# --- every advertised subcommand must have something behind it --------------------------
def test_every_cli_subcommand_resolves_to_something_that_exists():
    """`verify` was advertised in the usage, dispatched to store/verify.py, and that file was
    never written — so the command the placement itself recommends next died with a python
    file-not-found after a successful 12 GiB copy. A front door onto nothing is worse than no
    door, because the tool told the operator to use it."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cli = (root / "model-store").read_text()

    # the case arms of the dispatcher, e.g.  place)  exec python3 "$HERE/store/place.py" ...
    arms = re.findall(r'^\s{2}([a-z]+)\)\s+exec\s+\S+\s+"\$HERE/([^"]+)"', cli, re.M)
    assert arms, "no dispatch arms found — this test is looking in the wrong place"
    for name, rel in arms:
        target = root / rel
        assert target.exists(), f"`{name}` dispatches to {rel}, which does not exist"

    # and anything named in the usage block is either dispatched or explicitly refused
    usage = re.findall(r"^#\s+model-store\s+([a-z]+)", cli, re.M)
    handled = set(re.findall(r"^\s{2}([a-z]+)\)", cli, re.M))
    for name in usage:
        assert name in handled, f"usage advertises `{name}` and nothing handles it"


def test_pin_refuses_rather_than_pretending_and_says_where_it_lives():
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([str(root / "model-store"), "pin", "anything"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2, "pin should refuse, not succeed and not crash"
    assert "source-pin" in r.stderr, "the refusal should say where pinning actually lives"
