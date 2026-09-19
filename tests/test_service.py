# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The store surface. What matters is that it never claims a model is sound without checking."""
import json, os, pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

os.environ["SYM_STORE_TOKEN"] = "test-token-not-a-credential"
import service
from store import inspect as S

C = TestClient(service.app)
AUTH = {"authorization": "Bearer test-token-not-a-credential"}
REAL = os.path.isdir("/models/symon")


def test_health_is_public():
    assert C.get("/api/store/health").status_code == 200


def test_everything_else_needs_a_credential():
    for p in ("/api/store/where", "/api/store/models"):
        assert C.get(p).status_code in (401, 403), p


def test_unconfigured_fails_closed():
    saved = os.environ.pop("SYM_STORE_TOKEN")
    try:
        assert C.get("/api/store/where", headers=AUTH).status_code == 503
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
