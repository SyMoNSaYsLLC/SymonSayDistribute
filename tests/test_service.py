# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The agents surface. The tests that matter are about what it refuses before a run starts."""
import contextlib, os, time, pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

os.environ["SYM_AGENTS_TOKEN"] = "test-token-not-a-credential"
import service

C = TestClient(service.app)
AUTH = {"authorization": "Bearer test-token-not-a-credential"}


@contextlib.contextmanager
def _bound(host):
    """Bind the unit to `host` for the block. The guard reads SYM_AGENTS_HOST per request, so
    the bind address is what decides whether a token is demanded at all."""
    saved = os.environ.get("SYM_AGENTS_HOST")
    os.environ["SYM_AGENTS_HOST"] = host
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("SYM_AGENTS_HOST", None)
        else:
            os.environ["SYM_AGENTS_HOST"] = saved


def test_health_is_public():
    r = C.get("/api/agents/health")
    assert r.status_code == 200 and r.json()["tools"] > 0


def test_everything_else_needs_a_credential():
    with _bound("0.0.0.0"):          # off-loopback: the token is what stands between them
        for p in ("/api/agents/tools", "/api/agents/connectors", "/api/agents/runs"):
            assert C.get(p).status_code in (401, 403), p


def test_unconfigured_fails_closed():
    saved = os.environ.pop("SYM_AGENTS_TOKEN")
    try:
        with _bound("0.0.0.0"):      # reachable off this host, and no token provisioned
            assert C.get("/api/agents/tools", headers=AUTH).status_code == 503
    finally:
        os.environ["SYM_AGENTS_TOKEN"] = saved


def test_loopback_needs_no_token():
    """On a loopback bind every route answers with no token at all, by design: a token there
    defends only against a caller who already has this host, and so can already read the token."""
    saved = os.environ.pop("SYM_AGENTS_TOKEN")
    try:
        with _bound("127.0.0.1"):
            assert C.get("/api/agents/tools").status_code == 200
    finally:
        os.environ["SYM_AGENTS_TOKEN"] = saved


def test_tools_are_declared_in_the_dialect_shape():
    d = C.get("/api/agents/tools", headers=AUTH).json()
    assert d["count"] >= 6
    for t in d["tools"]:
        assert set(("name", "description", "input_schema")) <= set(t)


def test_connectors_name_every_wire_and_how_it_is_routed():
    d = C.get("/api/agents/connectors", headers=AUTH).json()
    assert d["connectors"], "no wires enumerated"
    for c in d["connectors"]:
        assert c["component"] != "?", "a wire that does not name its component"
        # The endpoint is deliberately NOT asserted. Since every wire routes through the
        # fabric, this process no longer knows where anything is — the fabric does. Asserting
        # an endpoint here would only pass by reintroducing the local table this change
        # removed, which is the whole point of the change.
        assert c["via"] == "fabric" and c["fabric"]


def test_this_process_holds_one_credential_and_it_is_the_fabrics():
    import symoneural_agents.connectors as K
    assert not hasattr(K, "ENDPOINTS"), "a local endpoint table is back"
    assert not hasattr(K, "TOKEN_ENV"), "a local token table is back"
    assert K.FABRIC_TOKEN_ENV == "SYM_FABRIC_TOKEN"


def test_reachability_is_answered_by_the_fabric_or_says_it_cannot_be():
    d = C.get("/api/agents/connectors", headers=AUTH).json()
    rows = d["reachable"]
    assert rows
    # Either the fabric answered for every component, or it is down and says so plainly —
    # never a per-component guess assembled from a table this process no longer keeps.
    assert all("component" in r for r in rows)
    if len(rows) == 1 and rows[0]["component"] == "fabric":
        assert rows[0]["up"] is False and "while it is down" in rows[0]["note"]


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
