# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""Plugins. The tests that matter are the refusals: presence is not consent, a manifest is not
code, and a licence this runtime cannot absorb is reported rather than loaded."""
import json, pytest
from symoneural_agents import plugins as P


def write(root, name, **over):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    m = {"name": name, "version": "1.0.0",
         "licence": "LicenseRef-SymonSaysLLC-Proprietary-1.0",
         "component": "board", "endpoint": "http://127.0.0.1:8811",
         "tools": [{"name": "check", "description": "d", "path": "/api/board/check"}]}
    m.update(over)
    (d / "plugin.json").write_text(json.dumps(m))
    return d


def test_presence_is_not_consent(tmp_path, monkeypatch):
    write(tmp_path, "p1")
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    monkeypatch.delenv("SYM_PLUGINS_ENABLED", raising=False)
    tools, record = P.load(lambda *a, **k: None)
    assert tools == []
    assert record[0]["state"] == "present, not enabled"


def test_enabling_by_name_loads_its_tools(tmp_path, monkeypatch):
    write(tmp_path, "p1")
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    monkeypatch.setenv("SYM_PLUGINS_ENABLED", "p1")
    tools, record = P.load(lambda *a, **k: {"ok": True})
    assert [t.name for t in tools] == ["p1_check"]
    assert record[0]["state"] == "loaded"


def test_a_licence_this_runtime_cannot_absorb_is_refused(tmp_path, monkeypatch):
    write(tmp_path, "gpl", licence="GPL-3.0-only")
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    monkeypatch.setenv("SYM_PLUGINS_ENABLED", "gpl")
    tools, record = P.load(lambda *a, **k: None)
    assert tools == []
    assert record[0]["state"] == "enabled but refused"
    assert "placement decision" in record[0]["why"]


def test_a_broken_manifest_is_listed_with_its_reason_not_omitted(tmp_path, monkeypatch):
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "plugin.json").write_text("{not json")
    (tmp_path / "nomanifest").mkdir()
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    rows = {r["name"]: r for r in P.discover()}
    assert rows["bad"]["loadable"] is False and "JSON" in rows["bad"]["why"]
    assert rows["nomanifest"]["why"] == "no plugin.json"


def test_a_manifest_missing_what_it_needs_is_refused(tmp_path, monkeypatch):
    for missing in ("licence", "component", "endpoint", "tools"):
        d = tmp_path / f"m_{missing}"
        d.mkdir()
        m = {"name": "x", "version": "1", "licence": "MIT", "component": "board",
             "endpoint": "http://x", "tools": [{"name": "t", "description": "d", "path": "/p"}]}
        del m[missing]
        (d / "plugin.json").write_text(json.dumps(m))
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    for r in P.discover():
        assert r["loadable"] is False and "lacks" in r["why"], r


def test_a_plugin_declaring_no_tools_grants_nothing(tmp_path, monkeypatch):
    write(tmp_path, "empty", tools=[])
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    r = P.discover()[0]
    assert r["loadable"] is False and "grants nothing" in r["why"]


def test_a_tool_path_must_be_a_path(tmp_path, monkeypatch):
    write(tmp_path, "weird", tools=[{"name": "t", "description": "d", "path": "http://elsewhere"}])
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    r = P.discover()[0]
    assert r["loadable"] is False and "must begin with /" in r["why"]


def test_a_plugin_never_receives_a_socket_only_a_description(tmp_path, monkeypatch):
    """The whole safety argument: a manifest can describe a request, never perform one."""
    seen = {}
    def call(component, path, method, body):
        seen.update(component=component, path=path, method=method)
        return {"ok": True}
    write(tmp_path, "p1")
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    monkeypatch.setenv("SYM_PLUGINS_ENABLED", "p1")
    tools, _ = P.load(call)
    out, err = P.Tool and tools[0].run({}), None
    assert seen == {"component": "board", "path": "/api/board/check", "method": "GET"}


def test_a_mutating_method_is_marked(tmp_path, monkeypatch):
    write(tmp_path, "w", tools=[{"name": "go", "description": "d", "path": "/x", "method": "POST"}])
    monkeypatch.setenv("SYM_PLUGINS_DIR", str(tmp_path))
    monkeypatch.setenv("SYM_PLUGINS_ENABLED", "w")
    tools, _ = P.load(lambda *a, **k: None)
    assert tools[0].mutates is True
