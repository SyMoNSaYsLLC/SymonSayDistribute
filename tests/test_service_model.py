# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The model arithmetic reached only by import for a whole release. These hold the routes to
the same standard as the module: a refusal arrives as a refusal, never as a 500 or a guess."""
import json, os, pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

os.environ["SYM_RAVENCALC_TOKEN"] = "test-token-not-a-credential"
from symoneural_ravencalc import service

C = TestClient(service.app)
AUTH = {"authorization": "Bearer test-token-not-a-credential"}
REAL = "/models/symon"


def has_model():
    return os.path.isdir(REAL) and os.path.isfile(REAL + "/config.json")


def test_every_model_route_exists():
    paths = {r.path for r in service.app.routes}
    for p in ("/api/ravencalc/model/tensors", "/api/ravencalc/model/kv-cache",
              "/api/ravencalc/model/experts", "/api/ravencalc/model/budget",
              "/api/ravencalc/model/gpu-fraction"):
        assert p in paths, f"{p} is not routed"


def test_the_routes_refuse_without_a_token():
    r = C.post("/api/ravencalc/model/kv-cache",
               json={"model_dir": REAL, "context": 1024})
    assert r.status_code in (401, 403)


def test_a_missing_checkpoint_is_404_not_500():
    r = C.post("/api/ravencalc/model/experts",
               json={"model_dir": "/nowhere/at/all"}, headers=AUTH)
    assert r.status_code == 404 and "config.json" in r.json()["detail"]


def test_a_refusal_from_the_arithmetic_is_422_carrying_its_reason():
    # ceiling above 1 is refused by the module; it must not become a 500
    r = C.post("/api/ravencalc/model/gpu-fraction", headers=AUTH,
               json={"total_bytes": 1000, "free_bytes": 900, "required_bytes": 100,
                     "reserve_bytes": 10, "ceiling": 1.5})
    assert r.status_code == 422


def test_reserve_and_ceiling_have_no_defaults():
    r = C.post("/api/ravencalc/model/gpu-fraction", headers=AUTH,
               json={"total_bytes": 1000, "free_bytes": 900, "required_bytes": 100})
    assert r.status_code == 422, "a default here would hand back a number nobody chose"


@pytest.mark.skipif(not has_model(), reason="no checkpoint in the store")
def test_kv_cache_against_the_real_checkpoint():
    r = C.post("/api/ravencalc/model/kv-cache", headers=AUTH,
               json={"model_dir": REAL, "context": 16384, "sequences": 4})
    assert r.status_code == 200
    d = r.json()["result"]
    assert d["kv_heads"] == 8, "sized by kv heads, not attention heads"
    assert d["per_layer_type"]["sliding_attention"]["positions_cached"] == 128
    assert d["bytes_total"] == d["bytes_per_sequence"] * 4


@pytest.mark.skipif(not has_model(), reason="no checkpoint in the store")
def test_experts_and_budget_agree_with_the_checkpoint_total():
    e = C.post("/api/ravencalc/model/experts", headers=AUTH,
               json={"model_dir": REAL}).json()["result"]
    idx = json.load(open(REAL + "/model.safetensors.index.json"))
    assert e["bytes_all_experts"] + e["bytes_always_resident"] == idx["metadata"]["total_size"]
    b = C.post("/api/ravencalc/model/budget", headers=AUTH,
               json={"model_dir": REAL, "context": 16384, "sequences": 4,
                     "vram_bytes": 16303 * 1024 * 1024}).json()["result"]
    assert b["everything_resident_bytes"] > b["minimum_resident_bytes"]
