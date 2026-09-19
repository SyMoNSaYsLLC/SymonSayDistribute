# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonkernel tests.

Most of these assert a REFUSAL or the SHAPE of an answer, because the way this unit fails is
not by crashing — it is by answering "nothing to report" when it could not ask the question.
An empty list, a missing kernel, a driver with no build: each of those has a truthful form and
a comfortable one, and the comfortable one is indistinguishable from healthy in every report.

Every test here is written so that it fails if the code stops being right. Several are pinned
to what this host actually holds, read from disk at the time they run rather than recorded.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from symonkernel import kernel as K

TOKEN = uuid.uuid4().hex


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard.
    # On a loopback bind the guard returns before comparing anything, which would
    # make every authenticated test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_KERNEL_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_KERNEL_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def _fake_modules_root(tmp_path: Path, release: str, *, out_of_tree=()) -> Path:
    """A kernel directory with a module tree and no header tree, built under tmp_path."""
    d = tmp_path / "modules" / release
    (d / "kernel" / "drivers").mkdir(parents=True)
    (d / "kernel" / "drivers" / "something.ko.xz").write_bytes(b"")
    for name in out_of_tree:
        oot = d / K.OUT_OF_TREE
        oot.mkdir(parents=True, exist_ok=True)
        (oot / f"{name}.ko.xz").write_bytes(b"")
    return tmp_path / "modules"


# --- the difference is the answer, and it is only an answer after normalisation --------------

def test_the_hyphen_underscore_normalisation_is_load_bearing():
    """A module is spelled with hyphens on disk and underscores in the loaded table.

    Without the normalisation every such module lands in BOTH halves of the difference at once,
    so the output reads as two findings where there are none. This asserts the two spellings
    really are different on this host, and that the normalisation closes the gap — a test that
    would pass on a raw comparison is not testing anything.
    """
    m = K.modules()
    hyphenated = [Path(p).name
                  for paths in m["files"]["out_of_tree_paths"].values()
                  for p in paths if "-" in Path(p).name]
    if not hyphenated:
        pytest.skip("no hyphenated out-of-tree module file on this host")
    loaded = set(K._loaded())
    for filename in hyphenated:
        assert "-" in filename
        assert K._module_name(filename).replace("_", "-") in filename.replace(".ko.xz", "")
        assert "-" not in K._module_name(filename)
    # and the normalised name is the one the loaded table would use
    assert any(K._module_name(f) in loaded for f in hyphenated), \
        "not one hyphenated module file matched the loaded table after normalisation"


def test_no_module_is_reported_as_both_missing_and_extra(tmp_path):
    """The bug this rules out is one module appearing in BOTH halves of the difference.

    Asserted against a tree built here holding exactly one module file — a hyphenated one whose
    underscored name is genuinely loaded. On this host's own tree the intersection is empty
    whether the names are reconciled or not, so asserting it there would pass regardless of
    whether the code is right, which is not a test.
    """
    # The expected mapping is spelled out HERE rather than taken from the code under test.
    # Selecting the fixture with `_module_name` made this test skip instead of fail when that
    # function was broken on purpose — the guard inherited the bug it was meant to catch.
    expected = lambda filename: filename.split(".")[0].replace("-", "_")
    m = K.modules()
    loaded = set(K._loaded())
    pick = next((Path(p).name
                 for paths in m["files"]["out_of_tree_paths"].values() for p in paths
                 if "-" in Path(p).name and expected(Path(p).name) in loaded), None)
    if pick is None:
        pytest.skip("no loaded module with a hyphenated file on this host")
    rel = os.uname().release
    oot = tmp_path / "modules" / rel / K.OUT_OF_TREE
    oot.mkdir(parents=True)
    (oot / pick).write_bytes(b"")
    r = K.modules(rel, root=str(tmp_path / "modules"))
    name = expected(pick)
    assert r["built_not_loaded"] == [], \
        f"{pick} is loaded; reporting it as built-and-not-loaded is the unreconciled spelling"
    assert name not in r["loaded_without_a_file"], \
        f"{name} is loaded and its file is right there; the two spellings were not reconciled"
    assert not (set(r["built_not_loaded"]) & set(r["loaded_without_a_file"]))


def test_the_module_difference_is_the_measured_one():
    """Pinned to disk: what is placed out-of-tree here and not loaded, read at test time.

    This is not a tautology — it recomputes the difference from the file listing and the loaded
    table independently of the code under test, and fails if the two disagree.
    """
    m = K.modules()
    placed = {K._module_name(Path(p).name)
              for paths in m["files"]["out_of_tree_paths"].values() for p in paths}
    loaded = set(K._loaded())
    assert set(m["built_not_loaded"]) == placed - loaded
    assert placed, "no out-of-tree module on this host — this test checked nothing"


def test_the_in_tree_modules_are_counted_not_listed():
    """Several thousand in-tree modules are shipped and a couple of hundred are loaded.

    Listing the rest as findings would bury the one that matters, so the count is reported and
    the list is not.
    """
    m = K.modules()
    assert isinstance(m["in_tree_built_not_loaded"], int)
    assert m["in_tree_built_not_loaded"] > len(m["built_not_loaded"])


def test_a_kernel_that_is_not_running_gets_no_difference_invented():
    ks = K.kernels()
    other = next((k["release"] for k in ks["kernels"]
                  if not k["running"] and k["has_module_tree"]), None)
    if other is None:
        pytest.skip("only one kernel with a module tree on this host")
    m = K.modules(other)
    assert m["compares_running"] is False
    assert m["loaded"] is None
    assert m["built_not_loaded"] is None, \
        "a difference against a kernel that is not running compares two kernels"
    assert "not the running kernel" in m["why"]
    assert m["files"]["total"] > 0, "the files are still reported; only the difference is not"


def test_an_unknown_kernel_is_refused_and_the_real_ones_are_named():
    with pytest.raises(K.KernelError, match="no module tree for") as e:
        K.modules("0.0.0-not-a-kernel")
    assert os.uname().release in str(e.value), "the refusal did not say what IS here"


def test_no_loaded_table_is_refused_rather_than_read_as_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "PROC_MODULES", str(tmp_path / "no-such-file"))
    with pytest.raises(K.KernelError, match="not guessed at"):
        K._loaded()


# --- the manager is found by looking, not by asking PATH -------------------------------------

def test_the_manager_is_located_off_path():
    """The binary lives in a directory that is not on this user's PATH.

    A unit that asked PATH would report it absent on a host where it is installed and working,
    and "absent" is the one wrong answer that reads as good news.
    """
    d = K.dkms()
    if shutil.which("dkms") is None:
        assert d["present"] is True, \
            "PATH does not find the manager and neither did this — the locator is PATH-bound"
        assert d["on_path"] is False
        assert "NOT on PATH" in d["why"]
    assert d["binary"] and Path(d["binary"]).is_file()
    assert os.access(d["binary"], os.X_OK)


def test_an_absent_manager_is_named_and_never_an_empty_list(monkeypatch, tmp_path):
    real_which = shutil.which
    monkeypatch.setattr(K, "DKMS_CANDIDATES", (str(tmp_path / "nothing-here"),))
    monkeypatch.setattr(K.shutil, "which",
                        lambda n, *a, **kw: None if n == "dkms" else real_which(n, *a, **kw))
    d = K.dkms()
    assert d["present"] is False
    assert d["state"] == "absent"
    assert d["entries"] == []
    assert "nothing to report" in d["why"], \
        "an empty entry list with no reason beside it reads as a clean bill of health"
    assert d["searched"], "the refusal did not say where it looked"


@pytest.mark.parametrize("line,want", [
    ("nvidia/615.71.09, 7.1.13+deb14-amd64, x86_64: installed",
     {"module": "nvidia", "version": "615.71.09", "kernel": "7.1.13+deb14-amd64",
      "arch": "x86_64", "state": "installed"}),
    ("nvidia, 615.71.09, 7.1.13+deb14-amd64, x86_64: installed",
     {"module": "nvidia", "version": "615.71.09", "kernel": "7.1.13+deb14-amd64",
      "arch": "x86_64", "state": "installed"}),
    ("nvidia/615.71.09: added",
     {"module": "nvidia", "version": "615.71.09", "kernel": None,
      "arch": None, "state": "added"}),
])
def test_both_manager_spellings_parse_to_the_same_fields(line, want):
    """The older spelling separates the version with a comma, the current one with a slash.

    A parser that handles only one reports the other as a module called `nvidia` at no version
    for no kernel, which is an entry that silently matches nothing in coverage.
    """
    got = K._parse_dkms_line(line)
    for field, value in want.items():
        assert got[field] == value, f"{field}: {got[field]!r} != {value!r}"


def test_a_line_with_no_kernel_is_kept_rather_than_dropped():
    got = K._parse_dkms_line("nvidia/615.71.09: added")
    assert got is not None and got["kernel"] is None
    assert got["state"] == "added", "a build that is added and not built is a real state"


# --- the point of the unit --------------------------------------------------------------------

def test_an_index_only_directory_is_not_reported_as_a_gap():
    """A removed kernel leaves its `modules.*` index files behind with no module tree.

    Counting those as kernels that ought to have a driver produces loud findings on a host
    where nothing is wrong, and a report whose first three lines are false is a report nobody
    reads the fourth line of.
    """
    dead = {k["release"] for k in K.kernels()["kernels"] if not k["has_module_tree"]}
    if not dead:
        pytest.skip("no index-only kernel directory on this host")
    c = K.coverage()
    bucketed = {s["release"] for s in c["index_only"]}
    # The identity, not just the absence: asserting only that the bucket does not overlap the
    # gaps passes when the bucket is EMPTY, which is precisely the behaviour being ruled out.
    assert bucketed == dead, "an index-only directory was not bucketed as one"
    assert not (dead & set(c["uncovered"])), "an index-only directory was counted as a gap"
    assert not (dead & set(c["covered"])), "an index-only directory was counted as covered"
    for s in c["index_only"]:
        assert "no module tree" in s["why"]


def test_an_index_only_directory_is_bucketed_on_any_host(tmp_path):
    """The same rule against a tree built here, so it holds on a host with no stale kernel."""
    root = tmp_path / "modules"
    (root / "9.9.9-live-amd64" / "kernel").mkdir(parents=True)
    (root / "9.9.9-live-amd64" / "kernel" / "a.ko.xz").write_bytes(b"")
    (root / "9.9.9-dead-amd64").mkdir(parents=True)
    (root / "9.9.9-dead-amd64" / "modules.dep").write_text("")
    c = K.coverage(root=str(root))
    assert [s["release"] for s in c["index_only"]] == ["9.9.9-dead-amd64"]
    assert "9.9.9-dead-amd64" not in c["uncovered"] + c["covered"]
    assert "9.9.9-live-amd64" in c["uncovered"] + c["covered"], \
        "a directory with a module tree was dropped from the verdict entirely"


def test_every_kernel_directory_is_reported_including_the_dead_ones():
    ks = K.kernels()
    on_disk = sorted(p.name for p in Path(K.MODULES_ROOT).iterdir() if p.is_dir())
    assert sorted(k["release"] for k in ks["kernels"]) == on_disk, \
        "a kernel directory was filtered out; silence is how a stale one stays invisible"
    assert os.uname().release in ks["with_module_tree"]


def test_a_kernel_with_no_build_is_named_with_what_it_would_take(tmp_path):
    """A synthetic kernel with a module tree, no headers and no build: it must show up.

    This is the failure the unit exists for, reproduced where it can be reproduced safely.
    """
    rel = "0.0.0-synthetic-amd64"
    root = _fake_modules_root(tmp_path, rel)
    c = K.coverage(root=str(root))
    assert rel in c["uncovered"], "a kernel with no module built for it was not reported"
    assert c["complete"] is False
    entry = next(k for k in c["kernels"] if k["release"] == rel)
    assert entry["covered"] is False
    assert entry["would_need"], "a gap with nothing named as needed is a gap nobody can close"
    assert any("headers" in n["what"] for n in entry["would_need"])


def test_the_command_that_would_close_a_gap_is_reported_as_an_argument_vector(tmp_path):
    rel = "0.0.0-synthetic-amd64"
    root = _fake_modules_root(tmp_path, rel)
    if not K.dkms()["present"]:
        pytest.skip("no module manager on this host to name a build command from")
    entry = next(k for k in K.coverage(root=str(root))["kernels"] if k["release"] == rel)
    builds = [n for n in entry["would_need"] if n["argv"]]
    assert builds, "no build command named for a kernel with no build"
    for b in builds:
        assert isinstance(b["argv"], list), "a command reported as a string is a command that " \
                                            "invites a shell"
        assert b["argv"][0] == K.dkms()["binary"]
        assert "does not run it" in b["why"]


def test_out_of_tree_modules_with_no_manager_are_a_gap_not_a_clean_result(monkeypatch, tmp_path):
    """Modules placed and nothing accounting for them is the failure in its worst form.

    Nothing will rebuild them for the next kernel and nothing will notice. Reporting that as
    covered because the manager returned no entries is exactly the comfortable answer.
    """
    real_which = shutil.which
    monkeypatch.setattr(K, "DKMS_CANDIDATES", (str(tmp_path / "nothing-here"),))
    monkeypatch.setattr(K.shutil, "which",
                        lambda n, *a, **kw: None if n == "dkms" else real_which(n, *a, **kw))
    c = K.coverage()
    live = [k for k in c["kernels"] if k["release"] in c["covered"] + c["uncovered"]]
    placed = [k for k in live if k["release"] in c["uncovered"]]
    assert placed, "with no manager and modules on disk, nothing was reported as a gap"
    assert c["complete"] is False
    for k in placed:
        assert k["would_need"], "a gap with no manager named nothing as needed"
        assert any("manager" in n["what"] for n in k["would_need"])


def test_nothing_is_covered_by_a_reported_state_alone(tmp_path):
    """The manager saying `installed` is not the same as the file being under the kernel.

    A synthetic kernel named after a release the manager really does report, with an empty
    module directory, must still come back uncovered.
    """
    d = K.dkms()
    entry = next((e for e in d["entries"] if e["kernel"]), None)
    if entry is None:
        pytest.skip("the manager reports no build to borrow a release name from")
    root = _fake_modules_root(tmp_path, entry["kernel"])
    c = K.coverage(root=str(root))
    k = next(x for x in c["kernels"] if x["release"] == entry["kernel"])
    assert k["covered"] is False, "a reported state was taken as proof the files are placed"
    assert any(m["files_missing"] for m in k["modules"])


def test_the_module_names_come_from_the_package_not_from_this_file():
    """A hardcoded module list is right until the driver adds a module, then wrong in silence."""
    src = inspect.getsource(K)
    pkgs = K.coverage()["dkms"]["packages"]
    if not pkgs:
        pytest.skip("no managed package on this host")
    for p in pkgs:
        for name in p["built_module_names"]:
            assert f'"{name}"' not in src, f"{name} is written into this file rather than read"


def test_the_newest_kernel_is_not_claimed_to_be_the_one_that_boots():
    c = K.coverage()
    if c["newest_installed"] is None:
        pytest.skip("no kernel with a module tree")
    assert "bootloader" in c["newest_installed"]["caveat"], \
        "the newest kernel is presented as the next boot without saying it was not read"


# --- can a module be built, and which precondition said no ---------------------------------------

def test_every_precondition_is_reported_separately_with_a_reason():
    b = K.buildable()
    assert set(b["preconditions"]) >= {
        "build_link", "headers", "headers_are_for_this_kernel", "kbuild",
        "compiler", "compiler_matches_kernel", "make", "module_manager"}
    for name, c in b["preconditions"].items():
        assert isinstance(c["ok"], bool), f"{name} has no answer"
        assert c["why"], f"{name} answered with no reason"
    assert b["ok"] == (not b["blocked_on"])


def test_a_missing_build_link_names_itself_rather_than_just_saying_no(tmp_path):
    rel = "0.0.0-synthetic-amd64"
    root = _fake_modules_root(tmp_path, rel)
    b = K.buildable(rel, root=str(root))
    assert b["ok"] is False
    assert b["preconditions"]["build_link"]["ok"] is False
    assert "build_link" in b["blocked_on"], "the failing precondition was not named"
    assert "headers" in b["blocked_on"]
    assert "build_link" in b["why"], "the summary does not say which precondition refused"


def test_headers_for_the_wrong_kernel_are_caught(tmp_path, monkeypatch):
    """A header tree can resolve and belong to a different kernel.

    It compiles, and produces a module that will not load. The tree states its own release, so
    that is read instead of trusting the directory name.
    """
    rel = os.uname().release
    b = K.buildable(rel)
    check = b["preconditions"]["headers_are_for_this_kernel"]
    if not b["preconditions"]["headers"]["ok"]:
        pytest.skip("no header tree on this host to check the release of")
    assert check["utsrelease"] == rel
    assert check["ok"] is True
    wrong = {"present": True, "path": str(tmp_path), "package": f"linux-headers-{rel}",
             "utsrelease": "9.9.9-someone-elses-kernel", "matches_release": False,
             "kbuild_scripts": True, "symbol_table": True,
             "conventional_path": str(tmp_path), "conventional_present": False,
             "why": "a header tree is present and states its own release"}
    monkeypatch.setattr(K, "_headers", lambda release, blink: wrong)
    b2 = K.buildable(rel)
    assert b2["preconditions"]["headers_are_for_this_kernel"]["ok"] is False
    assert "headers_are_for_this_kernel" in b2["blocked_on"]
    assert "will not load" in b2["preconditions"]["headers_are_for_this_kernel"]["why"]


def test_the_compiler_question_is_two_questions_and_both_are_answered():
    """`a compiler exists` and `the compiler the kernel was built with exists` differ here.

    Both versions are reported. The mismatch does not flip the verdict: this unit does not run
    a build, so it is not entitled to claim one would fail.
    """
    b = K.buildable()
    present = b["preconditions"]["compiler"]
    match = b["preconditions"]["compiler_matches_kernel"]
    assert present["version"], "no compiler version was read"
    assert match["kernel_built_with"], "the kernel's own build compiler was not read"
    assert match["blocking"] is False
    assert present["blocking"] is True
    if not match["ok"]:
        assert match["default"] != match["kernel_built_with"]
        assert "compiler_matches_kernel" in b["warnings"]
        assert "compiler_matches_kernel" not in b["blocked_on"]


def test_the_kernels_own_build_compiler_is_read_from_the_kernel():
    r = K.running()
    assert r["release"] == os.uname().release
    assert r["version"] == os.uname().version
    assert r["built_with"] and r["built_with"]["version"], \
        "the kernel records the compiler that produced it and it was not read"
    assert r["built_with"]["version"] in r["proc_version"]


def test_buildable_refuses_a_kernel_that_is_not_here():
    with pytest.raises(K.KernelError, match="no module tree for"):
        K.buildable("0.0.0-not-a-kernel")


# --- this unit reads; it never changes kernel state ---------------------------------------------

def test_no_subprocess_call_can_change_kernel_state():
    tree = ast.parse(inspect.getsource(K))
    calls = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run":
            assert n.args and isinstance(n.args[0], ast.List), \
                "an argument vector that is not a literal list cannot be read here"
            calls.append([e.value for e in n.args[0].elts if isinstance(e, ast.Constant)])
            for kw in n.keywords:
                assert kw.arg != "shell", "shell=True turns an argument into a command"
    assert calls, "no subprocess call found — this test would pass on an empty file"
    banned = {"install", "build", "autoinstall", "remove", "uninstall", "add", "unbuild",
              "mkdriverdisk", "modprobe", "insmod", "rmmod", "depmod"}
    for argv in calls:
        assert not (set(argv) & banned), f"a state-changing verb in {argv}"


def test_nothing_here_writes_to_a_system_path():
    src = inspect.getsource(K)
    for forbidden in (".write_text(", ".write_bytes(", ".mkdir(", ".unlink(", ".rmdir(",
                      "os.remove(", "os.rename(", "shutil.copy", "shutil.move", "shell=True"):
        assert forbidden not in src, f"{forbidden} in a unit that is supposed to only read"


# --- over http -----------------------------------------------------------------------------------

def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    """Off-loopback the bind is reachable, so the token is required and an unset one closes the
    unit: becoming reachable through a config change must not make it public through that same
    change. The host is set before the reload so the guard is in its off-loopback mode."""
    monkeypatch.setenv("SYM_KERNEL_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_KERNEL_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonkernel/health").status_code == 200
    assert c.get("/api/symonkernel/running").status_code == 503
    assert c.get("/api/symonkernel/coverage").status_code == 503


def test_loopback_needs_no_token(monkeypatch):
    """The other half of the contract: on the loopback default no token is asked for, because a
    token on a 127.0.0.1 bind defends only against a caller who could already read the token."""
    monkeypatch.delenv("SYM_KERNEL_HOST", raising=False)
    monkeypatch.delenv("SYM_KERNEL_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonkernel/health").status_code == 200
    assert c.get("/api/symonkernel/running").status_code == 200, \
        "a loopback bind must not refuse a caller over a token it cannot justify asking for"


def test_a_wrong_token_off_loopback_is_refused(client):
    r = client.get("/api/symonkernel/running", headers={"Authorization": "Bearer not-the-token"})
    assert r.status_code == 401


def test_coverage_is_reachable_and_carries_its_verdict(client):
    r = client.get("/api/symonkernel/coverage", headers=auth())
    assert r.status_code == 200
    b = r.json()
    assert set(b) >= {"kernels", "covered", "uncovered", "index_only", "complete", "running"}
    assert b["complete"] == (not b["uncovered"])
    if b["uncovered"]:
        assert all(k["would_need"] for k in b["kernels"] if k["release"] in b["uncovered"])


def test_an_unknown_release_over_http_is_a_refusal_not_an_empty_answer(client):
    r = client.get("/api/symonkernel/modules", params={"release": "0.0.0-not-a-kernel"},
                   headers=auth())
    assert r.status_code == 409
    assert "no module tree for" in r.json()["detail"]


def test_every_public_capability_is_routed_or_declared_unrouted():
    """The same rule the endpoints-current gate applies, asserted here so it fails in the tests
    first: a capability is reachable, or it says why it is not. Silence is the failure."""
    import service
    src = inspect.getsource(service)
    public = [n for n, f in inspect.getmembers(K, inspect.isfunction)
              if not n.startswith("_") and f.__module__ == K.__name__]
    assert public, "no public capability found — this test would pass on an empty module"
    for name in public:
        assert name in K.NOT_EXPOSED or f"{name}(" in src, \
            f"{name}() has no route and no NOT_EXPOSED entry"
    for name in K.NOT_EXPOSED:
        assert name in public, f"NOT_EXPOSED names {name}, which is not a public capability"
        assert len(K.NOT_EXPOSED[name]) > 40, f"{name} is declared unrouted with no real reason"


# --- §3.1b-iii: what DKMS will rebuild is asserted against the pin --------------------------
def test_every_dkms_registration_matches_the_recorded_pin():
    """The assertion §3.1b-iii requires, on the REBUILD side rather than the loaded side."""
    p = K.pinned()
    if p["pinned"] is None:
        pytest.skip(f"no pin on this host at {p['pin_file']}")
    assert p["registered"], "DKMS registered nothing; a new kernel would get no module"
    assert p["matches"] is True, p["why"]


def test_a_drifted_registration_is_reported_with_the_kernel_it_affects(monkeypatch, tmp_path):
    """A wrong pin must not pass, and must name WHICH kernel gets the unrecorded module."""
    import json
    f = tmp_path / "pin.json"
    f.write_text(json.dumps({"component": "open-gpu-kernel-modules",
                             "intended_tag_version": "0.0.0-not-this-one"}))
    monkeypatch.setattr(K, "PIN", str(f))
    p = K.pinned()
    assert p["matches"] is False
    assert p["drifted"], "a mismatch reported nothing as drifted"
    assert all(e["kernel"] for e in p["drifted"]), "drift must name the kernel it affects"


def test_a_missing_pin_is_named_not_treated_as_agreement(monkeypatch, tmp_path):
    """Silence is never consent — a missing pin is a gap, not a match."""
    monkeypatch.setattr(K, "PIN", str(tmp_path / "absent.json"))
    p = K.pinned()
    assert p["matches"] is None
    assert "no pin at" in p["why"]
