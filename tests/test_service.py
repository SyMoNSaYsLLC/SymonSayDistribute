# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The agents surface. The tests that matter are about what it refuses before a run starts."""
import os, time, pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

os.environ["SYM_AGENTS_TOKEN"] = "test-token-not-a-credential"
import service

C = TestClient(service.app)
AUTH = {"authorization": "Bearer test-token-not-a-credential"}


def test_health_is_public():
    r = C.get("/api/agents/health")
    assert r.status_code == 200 and r.json()["tools"] > 0


def test_everything_else_needs_a_credential():
    for p in ("/api/agents/tools", "/api/agents/connectors", "/api/agents/runs"):
        assert C.get(p).status_code in (401, 403), p


def test_unconfigured_fails_closed():
    saved = os.environ.pop("SYM_AGENTS_TOKEN")
    try:
        assert C.get("/api/agents/tools", headers=AUTH).status_code == 503
    finally:
        os.environ["SYM_AGENTS_TOKEN"] = saved


def test_tools_are_declared_in_the_dialect_shape():
    d = C.get("/api/agents/tools", headers=AUTH).json()
    assert d["count"] >= 6
    for t in d["tools"]:
        assert set(("name", "description", "input_schema")) <= set(t)


def test_connectors_name_every_wire_and_its_far_end():
    d = C.get("/api/agents/connectors", headers=AUTH).json()
    assert d["connectors"], "no wires enumerated"
    for c in d["connectors"]:
        assert c["component"] != "?" and c["endpoint"]
    # reachability is measured, not assumed
    assert {r["component"] for r in d["reachable"]} >= {"board", "gateway", "ravencalc"}


def test_a_tool_that_does_not_exist_is_refused_before_the_run_starts():
    r = C.post("/api/agents/runs", headers=AUTH,
               json={"name": "x", "task": "go", "tools": ["no_such_tool"]})
    assert r.status_code == 422 and "do not exist" in r.json()["detail"]
    assert C.get("/api/agents/runs", headers=AUTH).json()["count"] == 0, "nothing was started"


def test_bounds_are_validated_at_the_edge():
    for bad in ({"max_steps": 0}, {"max_steps": 500}, {"max_seconds": 0}, {"max_seconds": -1}):
        r = C.post("/api/agents/runs", headers=AUTH,
                   json={"name": "x", "task": "go", "tools": [], **bad})
        assert r.status_code == 422, bad


def test_a_run_appears_in_the_list_the_instant_it_starts():
    """A registry that records a run only once the thread is going has a window in which a
    started run does not exist, and that window is where a supervisor loses track."""
    r = C.post("/api/agents/runs", headers=AUTH,
               json={"name": "probe", "task": "say hello", "tools": ["board_check"],
                     "max_steps": 1, "max_seconds": 5})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert any(x["id"] == rid for x in C.get("/api/agents/runs", headers=AUTH).json()["runs"])
    assert C.get(f"/api/agents/runs/{rid}", headers=AUTH).status_code == 200


def test_an_unknown_run_is_404_on_both_read_and_stop():
    assert C.get("/api/agents/runs/run_nope", headers=AUTH).status_code == 404
    assert C.post("/api/agents/runs/run_nope/stop", headers=AUTH).status_code == 404


def test_stopping_a_finished_run_says_so_rather_than_failing():
    """Driven through the registry with a send that returns at once, so this asserts the
    registry's behaviour rather than how fast the engine happens to be today."""
    from symoneural_agents.registry import Runs
    rs = Runs(max_concurrent=2)
    run = rs.start("brief", "x", service.TOOLS.grant([]),
                   lambda p, timeout=None: {"content": [{"type": "text", "text": "done"}]},
                   model="m", max_steps=1, max_seconds=5)
    for _ in range(100):
        if not rs.get(run.id).thread.is_alive():
            break
        time.sleep(0.02)
    assert "nothing to stop" in rs.stop(run.id).get("note", "")


def test_clear_never_drops_a_live_run():
    before = C.get("/api/agents/runs", headers=AUTH).json()["active"]
    d = C.delete("/api/agents/runs", headers=AUTH).json()
    after = C.get("/api/agents/runs", headers=AUTH).json()["active"]
    assert after == before, "a live run was dropped"


def test_no_route_leaks_the_gateway_credential():
    p = os.path.expanduser("~/.config/symoneural/gateway-9001.key")
    if not os.path.isfile(p):
        pytest.skip("no credential on this host")
    secret = open(p).read().strip()
    for path in ("/api/agents/tools", "/api/agents/connectors", "/api/agents/runs",
                 "/api/agents/health"):
        assert secret not in C.get(path, headers=AUTH).text, path
