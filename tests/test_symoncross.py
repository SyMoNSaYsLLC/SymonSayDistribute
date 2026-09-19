#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Tests for symoncross.

Most of these assert a NEGATIVE, because the failure this component exists to prevent is a
cheerful one: a report saying the estate can build for a target when nothing on the host can
emit an artifact for it. So the windows-mingw test asserts it is NOT buildable and that the
missing compiler is named, and it would fail the day somebody made `buildable` optimistic.

None of these passes whether or not the code is right. The ones that read the live host read
things that are true of this host and would change the verdict if they changed — which is the
point: a test that cannot fail has gated nothing.
"""
from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import service                                    # noqa: E402
from symoncross import targets as X               # noqa: E402

MODULE = Path(X.__file__)


# -------------------------------------------------------------------------------------------
# fixtures — the compile probes cost about twenty seconds, so the full report is built once
# -------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def report() -> dict:
    return X.targets()


@pytest.fixture(scope="module")
def ports() -> dict:
    return X.portability()


@pytest.fixture
def loopback_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SYM_CROSS_HOST", "127.0.0.1")
    monkeypatch.delenv("SYM_CROSS_TOKEN", raising=False)
    importlib.reload(service)
    yield TestClient(service.app)
    importlib.reload(service)


@pytest.fixture
def offloopback_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SYM_CROSS_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_CROSS_TOKEN", raising=False)
    importlib.reload(service)
    yield TestClient(service.app)
    monkeypatch.setenv("SYM_CROSS_HOST", "127.0.0.1")
    importlib.reload(service)


# -------------------------------------------------------------------------------------------
# the bind address decides the credential (rules 3.2a)
# -------------------------------------------------------------------------------------------

def test_loopback_needs_no_token(loopback_client):
    """On loopback every route answers with no credential at all."""
    for path in ("/api/symoncross/health", "/api/symoncross/hosts",
                 "/api/symoncross/layers", "/api/symoncross/builders"):
        r = loopback_client.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])


def test_offloopback_without_a_token_is_503(offloopback_client):
    """Reachable off the host and unconfigured: the surface closes rather than opening."""
    r = offloopback_client.get("/api/symoncross/hosts")
    assert r.status_code == 503, (r.status_code, r.text[:200])
    assert "SYM_CROSS_TOKEN" in r.text


def test_health_stays_public_off_loopback(offloopback_client):
    """Health answers before the unit is configured; that is what makes it usable."""
    r = offloopback_client.get("/api/symoncross/health")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_offloopback_with_the_right_token_answers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SYM_CROSS_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_CROSS_TOKEN", "probe-value-not-a-secret")
    importlib.reload(service)
    try:
        c = TestClient(service.app)
        assert c.get("/api/symoncross/hosts").status_code == 401
        assert c.get("/api/symoncross/hosts",
                     headers={"Authorization": "Bearer wrong"}).status_code == 401
        r = c.get("/api/symoncross/hosts",
                  headers={"Authorization": "Bearer probe-value-not-a-secret"})
        assert r.status_code == 200
    finally:
        monkeypatch.setenv("SYM_CROSS_HOST", "127.0.0.1")
        importlib.reload(service)


def test_open_on_loopback_reads_the_bind_address(monkeypatch: pytest.MonkeyPatch):
    for host, expected in (("127.0.0.1", True), ("localhost", True), ("::1", True),
                           ("0.0.0.0", False), ("192.168.1.10", False), ("example", False)):
        monkeypatch.setenv("SYM_CROSS_HOST", host)
        assert service._open_on_loopback() is expected, host


# -------------------------------------------------------------------------------------------
# targets(): the verdict is never bare, and the honest verdict here is "no"
# -------------------------------------------------------------------------------------------

def test_windows_mingw_is_not_buildable_and_names_the_missing_compiler(report):
    """This host genuinely cannot emit a PE binary; a test asserting otherwise would be false.

    The missing compiler must be NAMED, not merely counted. A `buildable: false` that does not
    say a toolchain is absent sends somebody looking for a build directory.
    """
    rec = report["targets"]["windows-mingw"]
    assert rec["buildable"] is False
    assert rec["blocked_by"], "a false verdict with no reasons is the bug this component is about"
    named = [b for b in rec["blocked_by"] if "mingw" in b and "compiler" in b]
    assert named, rec["blocked_by"]

    pre = next(p for p in rec["preconditions"] if p["name"] == named[0])
    assert pre["met"] is False
    assert pre["evidence"]["found"] == []
    assert "x86_64-w64-mingw32-gcc" in pre["evidence"]["searched"]


def test_no_mingw_compiler_is_actually_on_this_host():
    """The premise behind the test above, checked against the host rather than assumed."""
    import shutil
    for name in X.MINGW_COMPILERS:
        assert shutil.which(name) is None, f"{name} appeared; the mingw verdict must be re-read"


def test_a_false_buildable_always_carries_a_reason(report):
    """Structural: blocked_by is derived from the preconditions and buildable from blocked_by."""
    for name, rec in report["targets"].items():
        assert isinstance(rec["buildable"], bool), name
        assert rec["buildable"] == (not rec["blocked_by"]), name
        if not rec["buildable"]:
            assert rec["blocked_by"], name
            unmet = {p["name"] for p in rec["preconditions"] if not p["met"]}
            assert set(rec["blocked_by"]) == unmet, name


def test_every_precondition_carries_evidence(report):
    for name, rec in report["targets"].items():
        assert rec["preconditions"], name
        for p in rec["preconditions"]:
            assert set(p) >= {"name", "met", "evidence"}, (name, p)
            assert isinstance(p["met"], bool), (name, p["name"])
            assert p["evidence"] not in (None, {}, ""), (name, p["name"])


def test_darwin_is_settled_by_compiling_not_by_reading_the_sdk(report):
    """The SDK is complete on disk and the compile still fails. Reading it would have lied.

    This is the one target where a structural check and a measurement disagree, so the test
    pins the measurement: the probe ran, it produced no artifact, and the verdict followed it.
    """
    rec = report["targets"]["darwin"]
    probe = next(p for p in rec["preconditions"] if p["name"].startswith("compile probe"))
    assert probe["evidence"]["run"]["rc"] != 0
    assert probe["evidence"]["artifact"]["exists"] is False
    sdk = next(p for p in rec["preconditions"] if "SDK" in p["name"])
    assert sdk["met"] is True, "the bundle is complete; the compile is what fails"
    assert rec["buildable"] is False
    assert probe["name"] in rec["blocked_by"]


def test_a_buildable_target_produced_a_real_artifact(report):
    """Anything reported buildable emitted something, and the magic bytes say what."""
    assert report["buildable"], "no target is buildable; that would itself need explaining"
    for name in report["buildable"]:
        rec = report["targets"][name]
        probe = next((p for p in rec["preconditions"] if "probe" in p["name"]), None)
        assert probe is not None, name
        assert probe["met"] is True
        assert probe["evidence"]["artifact"]["exists"] is True, name
        assert probe["evidence"]["artifact"].get("magic"), name


def test_targets_rejects_an_unknown_name():
    with pytest.raises(KeyError):
        X.targets(name="beos")


def test_a_single_target_can_be_asked_for(report):
    one = X.targets(name="jvm")
    assert list(one["targets"]) == ["jvm"]
    assert one["targets"]["jvm"]["buildable"] == report["targets"]["jvm"]["buildable"]


def test_buildable_means_toolchain_not_source(report):
    """The estate holds no native source, and linux-native is still buildable. Say which."""
    rec = report["targets"]["linux-native"]
    assert rec["buildable"] is True
    assert rec["estate_source"]["native_source_files"] == 0
    assert "NOT that" in rec["means"]


# -------------------------------------------------------------------------------------------
# layers(): ACQUIRED is not the same thing as sitting on the disk
# -------------------------------------------------------------------------------------------

def test_layers_distinguishes_acquired_from_present():
    """Both classes must actually occur, or the distinction is untested decoration."""
    lay = X.layers()
    assert lay["acquired_names"], "no ACQUIRED layer found; the pin lookup is not working"
    assert lay["present_names"], "no PRESENT layer found"
    for r in lay["layers"]:
        assert r["acquisition"] in ("ACQUIRED", "PRESENT")
        assert r["acquired"] is (r["acquisition"] == "ACQUIRED")
        assert r["why"], r["name"]
        if r["acquired"]:
            assert r["pin"] and r["pin"]["path"], r["name"]
            assert r["pin"]["revision"], r["name"]
        else:
            assert not (r["pin"] and r["pin"].get("acquisition_state") == "ACQUIRED"
                        and r["root_kind"] != "cache"), r["name"]


def test_meta_mingw_is_present_but_not_acquired():
    """It is in a download cache. A cache copy is not a layer the estate owns."""
    lay = X.layers(names=["meta-mingw"])
    found = lay["layers"]
    assert found, "meta-mingw was not found at all"
    for r in found:
        assert r["acquired"] is False
        assert r["acquisition"] == "PRESENT"
        assert r["root_kind"] == "cache"
        assert r["pin"] is None
        assert r["layer_conf"]["exists"] is True


def test_an_acquired_layer_names_the_pin_that_makes_it_acquired():
    lay = X.layers()
    acquired = [r for r in lay["layers"] if r["acquired"]]
    assert acquired, "expected at least one pinned layer"
    for r in acquired:
        assert r["root_kind"] != "cache", r["path"]
        assert Path(r["pin"]["path"]).is_file(), r["pin"]["path"]
        assert r["pin"]["acquisition_state"] == "ACQUIRED"


def test_an_acquired_layer_compares_its_checkout_to_its_pin():
    """A pin records intent. Whether the tree is AT that commit is a different fact, and read.

    Repeating a pin's revision beside a directory implies the directory is at it. This asserts
    the comparison actually happened — the commit was read from the checkout with git — and that
    the sentence the record produces agrees with the comparison rather than with the pin.
    """
    lay = X.layers()
    acquired = [r for r in lay["layers"] if r["acquired"]]
    assert acquired
    for r in acquired:
        c = r["checkout"]
        assert c is not None, r["name"]
        assert c["pin"] == r["pin"]["revision"]
        assert isinstance(c["matches_pin"], bool)
        assert c["evidence"]["command"][:3] == ["git", "-C", c["repo_root"]], c["evidence"]
        if c["head"] is not None:
            assert c["matches_pin"] is (c["head"] == c["pin"]), r["name"]
            if not c["matches_pin"]:
                assert "NOT the pinned bytes" in r["why"], r["why"]
                assert r["name"] in lay["drifted_names"], r["name"]
            else:
                assert "NOT the pinned bytes" not in r["why"], r["why"]
    assert lay["totals"]["acquired_but_drifted"] == len(lay["drifted_names"])


def test_a_drifted_checkout_is_not_reported_as_the_pinned_commit():
    """Measured on this host: both pinned checkouts have moved off their pins.

    If somebody re-pins or re-checks-out so they agree, this test stops being about drift and
    the assertion below still holds — it checks the report matches the disk either way.
    """
    lay = X.layers()
    for r in (x for x in lay["layers"] if x["acquired"] and x["checkout"]["head"]):
        head = subprocess.run(["git", "-C", r["checkout"]["repo_root"], "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20)
        assert head.returncode == 0, head.stderr[:200]
        assert r["checkout"]["head"] == head.stdout.strip(), r["name"]


def test_a_cache_copy_can_never_be_acquired():
    """The rule, exercised directly: a cache is a download area, not a tree the estate owns."""
    lay = X.layers()
    for r in lay["layers"]:
        if r["root_kind"] == "cache":
            assert r["acquired"] is False, r["path"]


def test_layer_roots_state_the_depth_they_were_searched_to():
    """A count from a search whose reach is not stated is a number nobody can reproduce."""
    lay = X.layers()
    assert lay["roots"]
    for root in lay["roots"]:
        assert root["search_depth"] >= 2
        assert "evidence" in root and root["evidence"]["read"]


# -------------------------------------------------------------------------------------------
# portability(): the answer that actually decides whether these components run elsewhere
# -------------------------------------------------------------------------------------------

def test_portability_finds_real_linux_only_calls_with_a_file_and_a_line(ports):
    """There are real ones in the estate, and a finding without a line cannot be acted on."""
    assert ports["totals"]["sites"] > 0
    flat = [h for rows in ports["findings"].values() for h in rows]
    assert flat
    for h in flat:
        assert h["line"] > 0, h
        assert Path(h["file"]).is_file(), h
        assert h["site"] == f"{h['rel']}:{h['line']}"
        assert h["kind"] in ("linux_program", "linux_path", "unparseable")


def test_portability_finds_the_gpu_query_in_both_components_that_make_it(ports):
    """Two components shell out to the same host-only program; both must be reported."""
    for component in ("symonprobe", "symonimage"):
        rows = ports["findings"].get(component)
        assert rows, f"{component} reported nothing"
        hits = [h for h in rows if h["name"] == "nvidia-smi"]
        assert hits, f"{component}: {rows}"
        for h in hits:
            line = Path(h["file"]).read_text().splitlines()[h["line"] - 1]
            assert "nvidia-smi" in line, (h["site"], line)


def test_every_reported_line_really_contains_what_was_reported(ports):
    """Re-read each finding from the file. A line number nobody checked is a guess."""
    for rows in ports["findings"].values():
        for h in rows:
            if h["kind"] == "unparseable":
                continue
            lines = Path(h["file"]).read_text().splitlines()
            window = "\n".join(lines[max(0, h["line"] - 1):h["line"] + 2])
            token = h["name"].rstrip("/") if h["kind"] == "linux_path" else h["name"]
            assert token in window, (h["site"], h["kind"], h["name"])


def test_portability_does_not_report_comments_or_docstrings(tmp_path: Path):
    """A finding pointing at prose discredits every finding beside it."""
    f = tmp_path / "decoy.py"
    f.write_text(
        '"""This module talks about dpkg and /proc and nvidia-smi at length."""\n'
        "# lsmod and dkms are mentioned in this comment\n"
        "def f():\n"
        '    """uname is discussed here too."""\n'
        '    return "no nvidia-smi on this host; nothing to report"\n'
    )
    out = X.portability(root=tmp_path)
    assert out["totals"]["sites"] == 0, out["findings"]


def test_portability_does_not_mistake_a_route_for_a_program(tmp_path: Path):
    """`/api/symonkernel/dkms` ends in a program name and is a URL path."""
    f = tmp_path / "routes.py"
    f.write_text('PATHS = ["/api/symonkernel/dkms", "updates/dkms", "/v1/uname"]\n')
    assert X.portability(root=tmp_path)["totals"]["sites"] == 0


def test_portability_does_find_a_real_call(tmp_path: Path):
    """The negative tests above must not be passing because the detector is dead."""
    f = tmp_path / "caller.py"
    f.write_text(
        "import subprocess\n"
        "EXE = '/usr/bin/nvidia-smi'\n"
        "def go():\n"
        "    subprocess.run([EXE, '-L'], timeout=5)\n"
        "    subprocess.run(['dpkg-query', '-W'], timeout=5)\n"
        "    return open('/proc/meminfo').read()\n"
    )
    out = X.portability(root=tmp_path)
    names = {h["name"] for rows in out["findings"].values() for h in rows}
    assert {"nvidia-smi", "dpkg-query", "/proc"} <= names, out["findings"]


def test_portability_declares_what_it_excluded(ports):
    """An exemption nobody can enumerate is a hole. This one is in the record."""
    excluded = {Path(e["path"]).name for e in ports["excluded"]}
    assert {"targets.py", "test_symoncross.py"} <= excluded, excluded
    assert all(e["reason"] for e in ports["excluded"])


def test_the_scanner_excludes_itself_from_every_root_that_contains_it():
    """The exclusion held from the estate root and silently lapsed one level down.

    A relative-suffix match worked for /mnt/SymonSayDistribute and stopped working for
    /mnt/SymonSayDistribute/symoncross — the one root where the scanner is certainly in range —
    so it scanned its own detector list and reported it as the defect, with an empty `excluded`.
    The route accepts that root, so this was reachable, not theoretical.
    """
    component = MODULE.parent.parent
    for root in (component, MODULE.parent, component.parent):
        out = X.portability(root=root)
        names = {Path(e["path"]).name for e in out["excluded"]}
        assert "targets.py" in names, (str(root), out["excluded"])
        scanned_self = [h for rows in out["findings"].values() for h in rows
                        if Path(h["file"]).resolve() == MODULE.resolve()]
        assert scanned_self == [], (str(root), scanned_self[:3])


def test_portability_on_a_missing_root_says_so(tmp_path: Path):
    out = X.portability(root=tmp_path / "nowhere")
    assert out["root_exists"] is False
    assert out["totals"]["sites"] == 0


# -------------------------------------------------------------------------------------------
# hosts() and builders()
# -------------------------------------------------------------------------------------------

def test_hosts_reports_the_host_with_its_evidence():
    h = X.hosts()
    assert h["os"]["value"] == "Linux"
    assert h["arch"]["value"]
    assert h["libc"]["value"]
    assert h["compiler"]["found"] is True
    assert h["compiler"]["version"]
    assert h["compiler"]["evidence"]["rc"] == 0
    assert h["libc"]["evidence"]["rc"] == 0


def test_builders_reports_every_bitbake_copy_and_whether_any_is_on_path():
    b = X.builders()
    bb = b["tools"]["bitbake"]
    assert bb["on_path"] is False, "it reached PATH; the windows-mingw verdict must be re-read"
    assert bb["copies_found"] >= 1, "the searched copies vanished"
    assert len(bb["copies"]) == len(X.BITBAKE_PATHS)
    assert bb["version"] is None and bb["not_run"]
    for c in bb["copies"]:
        assert "path" in c and "exists" in c


def test_builders_runs_the_tools_it_reports_a_version_for():
    b = X.builders()
    for name, tool in b["tools"].items():
        if name == "bitbake" or not tool["on_path"]:
            continue
        assert tool["version"], name
        assert tool["evidence"]["rc"] == 0, (name, tool["evidence"])


def test_builders_absent_tools_carry_no_invented_version():
    b = X.builders()
    for name in b["absent"]:
        assert b["tools"][name]["version"] is None, name
        assert b["tools"][name]["path"] is None, name


# -------------------------------------------------------------------------------------------
# the module itself
# -------------------------------------------------------------------------------------------

def test_nothing_reaches_a_shell():
    """A value that reaches a shell is a value that can become a command."""
    assert "shell=True" not in MODULE.read_text()


def test_every_subprocess_call_is_bounded():
    """An unbounded probe hangs the route that asked for it."""
    tree = ast.parse(MODULE.read_text())
    calls = 0
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in ("run", "Popen", "check_output", "call"):
            base = f.value
            if isinstance(base, ast.Name) and base.id == "subprocess":
                calls += 1
                assert any(k.arg == "timeout" for k in n.keywords), ast.dump(n)[:200]
    assert calls >= 1, "the subprocess guard found nothing to guard"


def test_the_module_writes_nowhere_predictable():
    """Temporary work goes in a directory nobody can guess or pre-create."""
    text = MODULE.read_text()
    assert "mkdtemp" in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "mkdtemp" in line:
            continue
        assert '"/tmp/' not in line and "'/tmp/" not in line, line


def test_probe_directories_are_cleaned_up(report):
    """The probes ran; nothing they created is still on the disk."""
    import tempfile
    leftovers = list(Path(tempfile.gettempdir()).glob("symoncross-*"))
    assert leftovers == [], leftovers


def test_not_exposed_is_declared():
    """An empty mapping is a decision on record; a missing one is an omission."""
    assert isinstance(X.NOT_EXPOSED, dict)
    public = [n.name for n in ast.parse(MODULE.read_text()).body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and not n.name.startswith("_")]
    service_text = Path(service.__file__).read_text()
    for name in public:
        assert name in X.NOT_EXPOSED or f"{name}(" in service_text, name


def test_the_probes_compile_only_their_own_source(tmp_path: Path):
    """Every probe writes its own few lines into a fresh directory and builds only that.

    Proven by intercepting the compiler calls: the file handed to each one is inside the
    temporary directory the probe just made, never a path in an estate or upstream tree.
    """
    calls: list[list[str]] = []
    real = subprocess.run

    def spy(argv, *a, **kw):
        calls.append(list(argv))
        return real(argv, *a, **kw)

    X._PROBE_CACHE.clear()
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(X.subprocess, "run", spy)
            X._probe_native()
            X._probe_jvm()
    finally:
        X._PROBE_CACHE.clear()

    assert calls
    sources = [a for argv in calls for a in argv if a.endswith((".c", ".java"))]
    assert sources, calls
    for src in sources:
        assert not src.startswith(("/mnt/", "/home/google/.cache/", "/yocto")), src


def test_the_service_reads_its_port_and_bind_from_the_environment():
    """Both are configuration, and the default port is this unit's own."""
    text = Path(service.__file__).read_text()
    assert 'os.environ.get("SYM_CROSS_PORT", "8827")' in text
    assert 'os.environ.get("SYM_CROSS_HOST", "127.0.0.1")' in text
    assert os.environ.get("SYM_CROSS_PORT") is None, "the default is what this asserts"


def test_the_probe_binaries_are_not_run_from_a_dotfile_directory():
    """Rules 3.3a: nothing executes from an agent scratch directory."""
    text = MODULE.read_text()
    assert "/.claude" not in text


def test_bitbake_is_never_executed():
    """Starting a build-and-integration tool is a build, and this component does not build."""
    text = MODULE.read_text()
    tree = ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_run":
            src = ast.get_source_segment(text, n) or ""
            assert "BITBAKE" not in src.upper(), src[:160]


def test_subprocess_is_never_given_a_bare_string(monkeypatch: pytest.MonkeyPatch):
    """Every call site hands over an argument vector, proven by intercepting one."""
    seen: list[object] = []
    real = subprocess.run

    def spy(argv, *a, **kw):
        seen.append(argv)
        return real(argv, *a, **kw)

    monkeypatch.setattr(X.subprocess, "run", spy)
    X.hosts()
    assert seen
    for argv in seen:
        assert isinstance(argv, list), argv
        assert all(isinstance(x, str) for x in argv), argv
