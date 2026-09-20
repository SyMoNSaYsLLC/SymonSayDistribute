# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonsdk tests.

Most of these are about the gap between INSTALLED and USABLE, because that gap is the only
reason this unit exists. Two of them are paired on purpose: one asserts the right answer, its
partner asserts that the wrong implementation would have produced a different one. A test that
passes whether or not the code is right has gated nothing.
"""
import importlib
import shutil
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

from symonsdk import toolchains as R

TOKEN = uuid.uuid4().hex
CAPABILITY_ROUTES = ("/api/symonsdk/toolchains", "/api/symonsdk/venvs",
                     "/api/symonsdk/sdks", "/api/symonsdk/sources")


def _client(monkeypatch, host, token=None):
    monkeypatch.setenv("SYM_SDK_HOST", host)
    if token is None:
        monkeypatch.delenv("SYM_SDK_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SYM_SDK_TOKEN", token)
    import service
    importlib.reload(service)
    return TestClient(service.app)


@pytest.fixture
def loopback(monkeypatch):
    return _client(monkeypatch, "127.0.0.1")


@pytest.fixture
def off_loopback_unset(monkeypatch):
    return _client(monkeypatch, "0.0.0.0")


@pytest.fixture
def off_loopback_keyed(monkeypatch):
    return _client(monkeypatch, "0.0.0.0", TOKEN)


# --- the bind address decides, not a convention (rules 3.2a) --------------------------------
def test_loopback_needs_no_token(loopback):
    for route in CAPABILITY_ROUTES:
        r = loopback.get(route)
        assert r.status_code == 200, f"{route} -> {r.status_code} {r.text[:200]}"
    assert loopback.get("/api/symonsdk/can-build", params={"ecosystem": "c"}).status_code == 200


def test_off_loopback_with_no_token_is_503(off_loopback_unset):
    for route in CAPABILITY_ROUTES:
        r = off_loopback_unset.get(route)
        assert r.status_code == 503, f"{route} -> {r.status_code}"
        assert "SYM_SDK_TOKEN" in r.json()["detail"]


def test_health_is_public_on_either_bind(loopback, off_loopback_unset):
    for c in (loopback, off_loopback_unset):
        r = c.get("/api/symonsdk/health")
        assert r.status_code == 200 and r.json()["unit"] == "symonsdk"


def test_off_loopback_compares_the_token_rather_than_waving_it_through(off_loopback_keyed):
    # Without this, "loopback needs no token" would pass against a guard that never guards.
    assert off_loopback_keyed.get(CAPABILITY_ROUTES[0]).status_code == 401
    assert off_loopback_keyed.get(CAPABILITY_ROUTES[0],
                                  headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert off_loopback_keyed.get(
        CAPABILITY_ROUTES[0], headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


# --- the regression that matters: a tool whose version argv is not --version ------------------
def _tool(name):
    return next(t for t in R.toolchains()["tools"] if t["name"] == name)


def test_go_is_reported_present_and_versioned_not_broken():
    entry = _tool("go")
    if not entry["found"]:
        pytest.skip("go is on no PATH entry on this host")

    # If `go --version` ever starts working, this test stops proving anything, so it says so
    # instead of passing quietly.
    naive = subprocess.run([entry["path"], "--version"], capture_output=True, text=True,
                           timeout=10, check=False)
    assert naive.returncode != 0, ("`go --version` now exits 0; this regression test has "
                                   "become vacuous and needs a new trap")

    assert "--version" not in entry["argv"], entry["argv"]
    assert entry["rc"] == 0
    assert entry["usable"] is True, entry["why"]
    assert entry["version"] and entry["release"], entry


def test_usable_is_derived_from_the_exit_code_not_from_resolution(monkeypatch):
    # The partner to the test above. With the wrong argv wired in, the same present, working
    # toolchain must be reported UNUSABLE — which is what makes the passing case meaningful.
    if not shutil.which("go"):
        pytest.skip("go is on no PATH entry on this host")
    monkeypatch.setitem(R._TOOLS, "go", (("--version",), "Go toolchain", (), {}))
    wrong = R._probe_one("go")
    assert wrong["found"] is True
    assert wrong["rc"] not in (0, None)
    assert wrong["usable"] is False
    assert "exited" in wrong["why"]


def test_java_version_goes_to_stderr_and_is_still_captured():
    entry = _tool("java")
    if not entry["found"]:
        pytest.skip("java is on no PATH entry on this host")
    assert entry["argv"][1:] == ["-version"]
    assert entry["usable"] is True and entry["version"], entry["why"]


def test_a_shim_is_invoked_by_the_name_that_was_looked_for():
    # `rustc` and `swift` are both symlinks into something that decides which tool it is from
    # argv[0]. Resolving the link before running it made `rustc` report the version of the
    # installer behind it, and made `swift` fail outright — a present, working toolchain
    # reported broken. Both were produced by this module before the fix.
    for name in ("rustc", "cargo"):
        t = _tool(name)
        if not t["found"]:
            continue
        assert t["usable"] is True, t["why"]
        assert t["version"].startswith(name), (
            f"{name} reported {t['version']!r} — the link was resolved before running it")
    for name in ("swift", "swiftc"):
        t = _tool(name)
        if not t["found"]:
            continue
        assert t["usable"] is True, t["why"]


def test_the_probe_runs_the_path_that_was_resolved_not_its_target():
    for t in R.toolchains()["tools"]:
        if t["found"] and t["on_path"]:
            assert t["path"] == shutil.which(t["name"]), t
            assert t["argv"][0] == t["path"]


def test_an_absent_tool_is_named_rather_than_omitted():
    out = R.toolchains()
    names = {t["name"] for t in out["tools"]}
    assert names == set(R._TOOLS)
    for t in out["tools"]:
        if not t["found"]:
            assert t["usable"] is False and t["path"] is None
            assert t["name"] in t["why"] and "absent" in t["why"]


def test_every_probe_is_bounded():
    rc, text = R._run(["sleep", "5"], timeout=0.2)
    assert rc is None and "timed out" in text


def test_no_probe_is_built_as_a_shell_string():
    src = (R.__file__ and open(R.__file__, encoding="utf-8").read()) or ""
    assert "shell=True" not in src


# --- a virtualenv whose interpreter is gone ---------------------------------------------------
def _fake_venv(root, name, interpreter_target, dists=()):
    d = root / name
    (d / "bin").mkdir(parents=True)
    (d / "pyvenv.cfg").write_text(f"home = {interpreter_target.parent}\nversion = 3.13.5\n")
    (d / "bin" / "python3").symlink_to(interpreter_target)
    site = d / "lib" / "python3.13" / "site-packages"
    site.mkdir(parents=True)
    for dist in dists:
        (site / dist).mkdir()
    (site / "not_a_distribution").mkdir()
    return d


def test_a_venv_whose_interpreter_is_gone_is_reported_unusable(monkeypatch, tmp_path):
    root = tmp_path / "venvs"
    root.mkdir()
    _fake_venv(root, "fine", tmp_path / "real" / "bin" / "python3",
               dists=("alpha-1.0.dist-info", "beta-2.0.egg-info"))
    # Point the good one at the interpreter running these tests, so it genuinely runs.
    (root / "fine" / "bin" / "python3").unlink()
    (root / "fine" / "bin" / "python3").symlink_to(sys.executable)
    gone = tmp_path / "deleted-runtime" / "bin" / "python3"
    _fake_venv(root, "broken", gone)

    monkeypatch.setenv(R.VENV_ROOT_VAR, str(root))
    out = R.venvs()
    by = {v["name"]: v for v in out["venvs"]}

    # Not vacuous: one of the two must come back usable, or this proves only that the function
    # says "no" to everything.
    assert by["fine"]["usable"] is True, by["fine"]["why"]
    assert by["fine"]["interpreter_runs"] is True
    assert by["fine"]["distributions"] == 2

    broken = by["broken"]
    assert broken["usable"] is False
    assert broken["interpreter_exists"] is False
    assert broken["interpreter_runs"] is False
    assert "does not exist" in broken["why"]
    assert str(gone) in broken["interpreter_link_target"]

    assert out["unusable"] == ["broken"]
    assert out["usable_count"] == 1 and out["count"] == 2


def test_a_missing_venv_root_is_answered_not_raised(monkeypatch, tmp_path):
    monkeypatch.setenv(R.VENV_ROOT_VAR, str(tmp_path / "nowhere"))
    out = R.venvs()
    assert out["root_exists"] is False and out["count"] == 0 and "no such directory" in out["why"]


def test_live_venvs_each_answer_the_interpreter_question(loopback):
    out = loopback.get("/api/symonsdk/venvs").json()
    if not out["root_exists"]:
        pytest.skip(f"no virtualenv root at {out['root']} on this host")
    for v in out["venvs"]:
        assert isinstance(v["interpreter_exists"], bool)
        assert isinstance(v["usable"], bool)
        assert v["why"]


# --- can_build names which part is missing ----------------------------------------------------
def test_can_build_names_every_missing_precondition_separately(monkeypatch, tmp_path):
    empty = tmp_path / "an-empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    out = R.can_build("rust")

    assert out["can_build"] is False
    assert "rustc" in out["missing"] and "cargo" in out["missing"]
    assert len(out["preconditions"]) == 3
    for c in out["preconditions"]:
        assert c["met"] is False and c["evidence"] and c["kind"]
    assert "rustc" in out["why"] and "cannot build rust" in out["why"]


def test_can_build_is_capable_of_yes():
    # The partner to the test above: with the real PATH, something on this host must build,
    # or "cannot build" means only that the function always says no.
    yes = [e for e in R._ECOSYSTEMS if R.can_build(e)["can_build"]]
    assert yes, "no ecosystem on this host reports can_build — check the preconditions"


def test_an_ecosystem_that_is_simply_not_installed_says_which_part():
    out = R.can_build("php")
    if out["can_build"]:
        pytest.skip("php has been installed on this host since this test was written")
    assert out["missing"] == ["php"]
    assert "absent" in out["preconditions"][0]["evidence"]


def test_node_and_its_package_manager_are_answered_separately():
    out = R.can_build("node")
    assert [c["name"] for c in out["preconditions"]] == ["node", "npm"]
    assert all(isinstance(c["met"], bool) for c in out["preconditions"])
    if not out["can_build"]:
        assert out["missing"] and set(out["missing"]) <= {"node", "npm"}
        for c in out["preconditions"]:
            if not c["met"]:
                assert c["evidence"]


def test_aliases_resolve_and_an_unknown_ecosystem_names_the_known_ones():
    assert R.can_build("CPP")["ecosystem"] == "c++"
    assert R.can_build("Golang")["ecosystem"] == "go"
    with pytest.raises(R.SdkError, match="unknown ecosystem"):
        R.can_build("cobol")


def test_unknown_ecosystem_is_a_400_carrying_the_vocabulary(loopback):
    r = loopback.get("/api/symonsdk/can-build", params={"ecosystem": "cobol"})
    assert r.status_code == 400
    assert "rust" in r.json()["detail"] and "unknown ecosystem" in r.json()["detail"]


# --- the trees --------------------------------------------------------------------------------
def test_sdk_trees_report_presence_size_and_versions_read_from_disk(loopback):
    out = loopback.get("/api/symonsdk/sdks").json()
    assert out["count"] == len(R._SDK_TREES)
    for t in out["sdks"]:
        assert t["why"]
        if t["present"]:
            assert t["root"] and t["size_bytes"] is not None and t["size_human"]
            assert isinstance(t["versions"], list)
        else:
            assert t["root"] is None and t["versions"] == []
    assert any(t["versions"] for t in out["sdks"]), "no SDK tree offered a readable version"
    # A total that silently omits a tree whose size timed out is a floor wearing a measurement.
    assert out["total_measured"] is (out["unmeasured"] == [])


def test_source_trees_carry_a_manifest_and_a_git_answer(loopback):
    out = loopback.get("/api/symonsdk/sources").json()
    for s in out["sources"]:
        assert s["manifests"] and s["builds_with"]
        assert isinstance(s["git"], bool)
        assert s["path"].startswith("/")
    assert out["count"] == len(out["sources"])


# --- the gate's question, asked here too ------------------------------------------------------
def test_every_public_capability_has_a_route_or_a_reason():
    import ast
    import pathlib
    mod = pathlib.Path(R.__file__)
    svc = (mod.parent.parent / "service.py").read_text(encoding="utf-8")
    tree = ast.parse(mod.read_text(encoding="utf-8"))
    public = [n.name for n in tree.body
              if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
    assert public, "no public capability found"
    for name in public:
        assert f"{name}(" in svc or name in R.NOT_EXPOSED, f"{name} is unreachable"
    assert isinstance(R.NOT_EXPOSED, dict)


# --- §3.1b-iii: a build input with no recorded version is invoked blind --------------------
def test_every_usable_toolchain_is_accounted_for_as_pinned_or_unrecorded():
    """No toolchain may be silently omitted. Each is MATCHES, DRIFTED, UNRESOLVED-PIN or
    UNRECORDED — an unrecorded build tool is the gap §3.1b-iii exists to make visible."""
    p = R.pinned()
    states = {r["state"] for r in p["toolchains"]}
    assert states <= {"MATCHES", "DRIFTED", "UNRESOLVED-PIN", "UNRECORDED"}, states
    assert p["toolchains_checked"] == len(p["toolchains"])
    assert p["toolchains_checked"] > 0, "no toolchain was checked; the probe returned nothing"


def test_an_empty_or_unresolved_pin_is_never_reported_as_agreement():
    """UNRESOLVED must not read as MATCHES. This is the half that protects the rule."""
    for r in R.pinned()["toolchains"]:
        if r.get("pinned") in (None, "", "UNRESOLVED", "?"):
            assert r["state"] != "MATCHES", f"{r['tool']} claimed agreement with {r['pinned']!r}"


def test_a_drifted_toolchain_names_both_versions(monkeypatch, tmp_path):
    """A mismatch must say what was pinned AND what is here, or it cannot be acted on."""
    pin_dir = tmp_path / "build" / "pins"
    pin_dir.mkdir(parents=True)
    (pin_dir / "python3.json").write_text(
        '{"component": "python3", "intended_tag_version": "0.0.0-not-this-one"}')
    monkeypatch.setattr(R, "PIN_ROOT", str(tmp_path))
    rows = {r["tool"]: r for r in R.pinned()["toolchains"]}
    assert "python3" in rows
    assert rows["python3"]["state"] == "DRIFTED"
    assert "0.0.0-not-this-one" in rows["python3"]["why"]
    assert rows["python3"]["release"] and rows["python3"]["release"] in rows["python3"]["why"]


def test_a_missing_pin_root_reports_everything_unrecorded(monkeypatch, tmp_path):
    """No pin registry at all must not look like agreement across the board."""
    monkeypatch.setattr(R, "PIN_ROOT", str(tmp_path / "absent"))
    p = R.pinned()
    assert p["pins_available"] == 0
    assert p["matched"] == [] and p["drifted"] == []
    assert len(p["unrecorded"]) == p["toolchains_checked"]


def test_nothing_moved_underneath_us_without_being_recorded():
    """The assertion §3.1b-iii actually wants: not 'no drift' but 'no UNRECORDED drift'.

    Pin/checkout drift is preserved, so demanding zero drift would be demanding the rule be
    broken. What must hold is that every movement has been looked at. A toolchain that changes
    version with no KNOWN_DRIFT entry fails here, which is the whole point — otherwise the
    upgrade is discovered by a user rather than by a test.
    """
    p = R.pinned()
    assert p["new_drift"] == [], "; ".join(
        r["why"] for r in p["toolchains"] if r["state"] == "DRIFTED" and not r.get("recorded"))


def test_removing_a_ledger_entry_makes_that_drift_new_again(monkeypatch):
    """The partner to the test above, and the reason it is not vacuous.

    If nothing on this host ever drifted, `new_drift == []` would prove only that nothing is
    compared. Remove the ninja entry and the same host must come back naming ninja.
    """
    live = R.pinned()
    if "ninja" not in live["recorded_drift"]:
        import pytest
        pytest.skip("ninja is not drifting on this host; nothing to un-record")
    monkeypatch.setattr(R, "KNOWN_DRIFT",
                        {k: v for k, v in R.KNOWN_DRIFT.items() if k[0] != "ninja"})
    p = R.pinned()
    assert "ninja" in p["new_drift"], p["new_drift"]
    row = next(r for r in p["toolchains"] if r["tool"] == "ninja")
    assert row["pinned"] in row["why"] and row["release"] in row["why"], row["why"]


def test_an_unresolved_pin_is_not_counted_as_drift():
    """A pin file that records no version compared nothing, so it cannot have drifted.

    node's pin is UNRESOLVED; it used to appear in `drifted` alongside genuinely moved
    toolchains, which claimed knowledge this unit does not have.
    """
    p = R.pinned()
    for r in p["toolchains"]:
        if r["state"] == "UNRESOLVED-PIN":
            assert r["tool"] not in p["drifted"], f"{r['tool']} is unresolved, not drifted"
            assert r["tool"] in p["unresolved"]
    assert not (set(p["drifted"]) & set(p["unresolved"]))
