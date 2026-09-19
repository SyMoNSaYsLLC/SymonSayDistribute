# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symondriver tests.

The ones that matter are the mismatch tests. A consistency checker exercised only against a
host that agrees with itself has been exercised against nothing: it would pass identically if
`consistent()` returned `True` unconditionally. So the disagreement path is driven twice —
once through the injection point, once by replacing a real source — and both assert that the
disagreeing source is NAMED, not merely that a boolean flipped.

Run from the branch root: `python3 -m pytest tests/ -q`. The `-m` form is what puts the root on
`sys.path`, which is how `service` and `symondriver` are importable here.
"""
import importlib
import re
import shutil
import subprocess
import uuid

import pytest
from fastapi.testclient import TestClient

from symondriver import driver as R

TOKEN = uuid.uuid4().hex


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard. On a loopback
    # bind the guard returns before comparing anything, which would make every authenticated
    # test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_DRIVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_DRIVER_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- the loaded kernel module -----------------------------------------------------------------
def test_the_kernel_module_names_its_version_variant_build_and_compiler():
    k = R.kernel_module()
    if not k["loaded"]:
        pytest.skip(k["why"])
    assert re.match(r"^\d+\.\d+\.\d+$", k["version"] or ""), k["raw"]
    assert k["open_module"] in (True, False)
    assert k["variant"] in ("open", "proprietary")
    assert k["build_host"], "the module did not say what built it"
    assert k["built"], "the module did not say when it was built"
    assert k["compiler"], "the module did not say what compiled it"


def test_the_two_files_the_module_publishes_agree_with_each_other():
    """Two independent files. If they ever disagree, the module publishing one is not the
    module answering the other, and that is a different fault from a package mismatch."""
    k = R.kernel_module()
    if not k["loaded"] or not k["sysfs"]["present"]:
        pytest.skip("the module is not loaded, or publishes only one version file")
    assert k["sysfs"]["agrees"] is True, (k["version"], k["sysfs"]["version"])


def test_an_absent_proc_file_says_not_loaded_rather_than_returning_empty(monkeypatch, tmp_path):
    """The failure this guards against is a silent empty result. A module that is not loaded is
    a finding in its own right — nothing in userspace reaches the device until one is."""
    monkeypatch.setattr(R, "_PROC_VERSION", str(tmp_path / "no-such-version"))
    monkeypatch.setattr(R, "_SYS_VERSION", str(tmp_path / "no-such-sysfs"))
    k = R.kernel_module()
    assert k["loaded"] is False
    assert k["version"] is None
    assert "is not readable" in k["why"] and "no kernel module is loaded" in k["why"]
    assert str(tmp_path) in k["source"], "the answer did not name the file it looked at"


# --- userspace, by running the tool --------------------------------------------------------------
def test_userspace_is_obtained_by_running_the_tool_with_an_argument_vector():
    import inspect
    src = inspect.getsource(R.userspace)
    assert "shell=True" not in src
    u = R.userspace()
    assert isinstance(u["argv"], list), "the tool must be invoked as an argument vector"
    assert u["argv"][0] == u["tool"]
    assert u["returncode"] == 0
    assert re.match(r"^\d+\.\d+\.\d+$", u["version"] or ""), u["stdout"]


def test_no_module_path_ever_reaches_a_shell():
    """An inspector that lets its input reach a shell is an execution surface, not an inspector."""
    import inspect
    src = inspect.getsource(R)
    assert "shell=True" not in src
    assert "os.system" not in src


# --- the libraries on disk -----------------------------------------------------------------------
def test_every_installed_architecture_is_read_not_just_the_native_one():
    libs = R.libraries()
    assert libs["count"] > 0
    assert libs["architectures"], "no architecture directory was found at all"
    for arch, group in libs["by_arch"].items():
        assert group["count"] > 0, f"{arch} was listed with nothing in it"


def test_a_versioned_library_carries_its_version_and_resolves_to_a_real_file():
    libs = R.libraries()
    versioned = [lib for g in libs["by_arch"].values() for lib in g["libraries"]
                 if lib["driver_version"]]
    assert versioned, "no library on this host carries a driver version in its filename"
    for lib in versioned:
        assert lib["resolves"] is True, f"{lib['path']} points at nothing"
        assert lib["driver_version"] in lib["real"] or lib["driver_version"] in lib["file"]


def test_a_library_on_another_version_series_is_returned_with_the_reason_not_hidden():
    """A filter nobody can see is indistinguishable from a bug. Whatever is set aside is still
    returned, carrying why."""
    libs = R.libraries()
    for entry in libs["other_series"]:
        assert entry["why"], f"{entry['file']} was set aside with no reason given"
        assert entry["why"].startswith("not compared because")


def test_a_soname_link_is_credited_with_the_version_of_what_it_resolves_to():
    """`libcuda.so.1` carries the ABI number, not the driver version. Filing it under "another
    version series" would be false — it is the driver, reached through its soname."""
    libs = R.libraries()
    links = [lib for g in libs["by_arch"].values() for lib in g["libraries"]
             if lib["symlink"] and lib["version_from"] == "resolved link target"]
    if not links:
        pytest.skip("no soname links on this host")
    for lib in links:
        assert lib["series"] == "driver"
        assert lib["driver_version"] in lib["real"]
        assert "why_not_compared" not in lib


@pytest.mark.skipif(not shutil.which("readelf"), reason="readelf is not installed")
def test_the_soname_parser_agrees_with_an_independent_reader():
    """This tests the ELF parser, not this module's own output read back at itself. Both object
    widths are covered, because assuming 64-bit would misparse a third of the files here and
    return a plausible wrong answer."""
    libs = R.libraries()
    checked = 0
    for arch, group in libs["by_arch"].items():
        for lib in group["libraries"]:
            if not lib["resolves"] or not lib["soname"]:
                continue
            r = subprocess.run(["readelf", "-d", lib["real"]],
                               capture_output=True, text=True, timeout=30)
            assert r.returncode == 0, r.stderr
            m = re.search(r"SONAME.*?\[([^\]]+)\]", r.stdout)
            if not m:
                continue
            assert lib["soname"] == m.group(1), f"{lib['real']} in {arch}"
            checked += 1
            break                       # one per architecture is enough to catch a width bug
    assert checked >= 1, "no soname was cross-checked against readelf"


# --- the known programs ---------------------------------------------------------------------------
def test_the_known_programs_are_located_and_none_of_them_is_executed():
    import inspect
    src = inspect.getsource(R.binaries)
    assert "subprocess" not in src and "_run(" not in src, \
        "binaries() must locate the programs, never run them"
    b = R.binaries()
    assert b["count"] > 0
    for entry in b["present"]:
        assert entry["path"] and entry["real"]


def test_the_program_that_writes_an_archive_is_marked_never_to_be_run():
    b = R.binaries()
    marked = [e for e in b["present"] if e.get("never_run_here")]
    if not marked:
        pytest.skip("that program is not installed on this host")
    assert "archive" in marked[0]["never_run_here"]


# --- the installed packages -------------------------------------------------------------------------
def test_packages_are_read_with_an_argument_vector_and_split_by_series():
    p = R.packages()
    assert isinstance(p["argv"], list)
    assert p["matched"] > 0
    assert p["driver_family_count"] > 0
    for e in p["driver_family"]:
        assert re.match(p["driver_series"], e["upstream"]), e
    for e in p["other"]:
        assert not re.match(p["driver_series"], e["upstream"]), e
        assert e["why_not_compared"], f"{e['package']} was set aside with no reason"


def test_a_package_version_is_compared_on_its_upstream_part_not_its_debian_revision():
    """`615.71.09-2` and `615.71.09` are the same driver. Comparing them as strings would report
    every host as inconsistent, which turns the one finding that matters into noise."""
    assert R._upstream("615.71.09-2") == "615.71.09"
    assert R._upstream("1:1.0.6-1") == "1.0.6"
    assert R._upstream("13.4.92-1") == "13.4.92"
    assert R._upstream("615.71.09") == "615.71.09"


# --- consistency: the point of the unit --------------------------------------------------------------
def test_consistent_names_where_every_version_it_saw_came_from():
    c = R.consistent()
    assert c["versions"], "no source reported a version at all"
    for version, sources in c["sources"].items():
        assert sources, f"{version} was reported by nobody"
        for s in sources:
            assert s["source"] and s["where"], f"{version} came from an unnamed place"
    assert c["why"]


def test_consistent_detects_an_injected_mismatch_and_names_the_injected_source():
    """The happy path on this host proves nothing on its own — if `consistent()` returned True
    unconditionally, every other assertion here would still pass."""
    fake = "500.00.01"
    where = "a stale library directory supplied by this test"
    c = R.consistent(extra_sources={where: fake})
    assert c["consistent"] is False, "an injected second version was not detected"
    assert fake in c["versions"], c["versions"]
    assert any(s["where"] == where for s in c["sources"][fake]), c["sources"][fake]
    assert fake in c["why"] and where in c["why"], c["why"]
    assert any(d["version"] == fake and d["where"] == where for d in c["disagreements"]), \
        "the disagreeing source was not named in disagreements"


def test_consistent_detects_a_kernel_module_that_disagrees_with_the_rest(monkeypatch):
    """The real failure mode, driven by replacing a real source rather than adding one: a
    partial upgrade leaves the loaded module behind while userspace moves on."""
    stale = "470.00.02"
    monkeypatch.setattr(R, "kernel_module", lambda: {
        "loaded": True, "source": R._PROC_VERSION, "version": stale, "variant": "open",
        "sysfs": {"source": R._SYS_VERSION, "version": stale},
    })
    c = R.consistent()
    assert c["consistent"] is False
    assert stale in c["versions"]
    assert c["by_source"]["kernel module"] == stale
    assert any(d["source"] == "kernel module" for d in c["disagreements"]), \
        "the module that disagreed was not named"
    assert R._PROC_VERSION in c["why"] or "kernel module" in c["why"]


def test_the_agreement_path_renders_when_the_stale_package_is_taken_away(monkeypatch):
    """This host disagrees with itself, so the agreement branch would otherwise never execute —
    and the first time it ran would be the moment somebody removed the stale package and came
    here to confirm the fix had worked, which is the worst possible time to find a formatting
    bug. The stale entry is dropped and the verdict must flip cleanly."""
    real = R.packages()
    good = R.consistent()["majority"]
    monkeypatch.setattr(R, "packages", lambda: {
        **real,
        "packages_at": {good: real["packages_at"][good]},
        "versions": [good],
    })
    c = R.consistent()
    assert c["consistent"] is True, c["why"]
    assert c["versions"] == [good]
    assert c["disagreements"] == []
    assert c["unavailable"] == []
    assert good in c["why"] and "agrees" in c["why"], c["why"]
    assert "kernel module" in c["why"], "the agreement did not say who agreed"


def test_a_source_that_cannot_be_read_is_named_rather_than_dropped(monkeypatch):
    """Dropping an unreadable source lets the remaining ones agree with each other and report a
    consistency that was never established."""
    def boom():
        raise R.DriverError("the query tool is not on PATH")
    monkeypatch.setattr(R, "userspace", boom)
    c = R.consistent()
    assert c["consistent"] is False
    assert any(u["source"] == "userspace" for u in c["unavailable"]), c["unavailable"]
    assert "not on PATH" in c["why"]


# --- over http ---------------------------------------------------------------------------------------
def test_loopback_needs_no_token(monkeypatch):
    """On the loopback default no token is asked for, because a token on a 127.0.0.1 bind
    defends only against a caller who could already read the token."""
    monkeypatch.delenv("SYM_DRIVER_HOST", raising=False)
    monkeypatch.delenv("SYM_DRIVER_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symondriver/health").status_code == 200
    assert c.get("/api/symondriver/consistent").status_code == 200, \
        "a loopback bind must not refuse a caller over a token it cannot justify asking for"
    assert c.get("/api/symondriver/kernel-module").status_code == 200


def test_off_loopback_with_no_token_is_503_and_health_still_answers(monkeypatch):
    """Off-loopback the bind is reachable, so the token is required and an unset one closes the
    unit: becoming reachable through a config change must not make it public through that same
    change. The host is set before the reload so the guard is in its off-loopback mode."""
    monkeypatch.setenv("SYM_DRIVER_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_DRIVER_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symondriver/health").status_code == 200
    assert c.get("/api/symondriver/consistent").status_code == 503
    assert c.get("/api/symondriver/packages").status_code == 503


def test_off_loopback_a_wrong_token_is_401(client):
    assert client.get("/api/symondriver/consistent",
                      headers={"Authorization": "Bearer not-the-token"}).status_code == 401


def test_every_capability_has_a_route_and_consistent_answers_over_http(client):
    for path in ("kernel-module", "userspace", "libraries", "binaries", "packages", "consistent"):
        r = client.get(f"/api/symondriver/{path}", headers=auth())
        assert r.status_code == 200, (path, r.text[:200])
    body = client.get("/api/symondriver/consistent", headers=auth()).json()
    assert set(body) >= {"consistent", "versions", "sources", "unavailable", "why"}


# --- §3.1b-iii: the pin is asserted, not assumed -------------------------------------------
def test_the_loaded_module_matches_the_recorded_pin():
    """The assertion §3.1b-iii requires. If this fails, the driver moved or the pin did."""
    p = R.pinned()
    if p["pinned"] is None:
        pytest.skip(f"no pin on this host at {p['pin_file']}")
    assert p["observed"], "no version could be read from the loaded module"
    assert p["matches"] is True, p["why"]


def test_a_pin_that_disagrees_is_reported_as_a_mismatch(monkeypatch, tmp_path):
    """The half that proves the check is real: a wrong pin must NOT pass."""
    import json
    f = tmp_path / "pin.json"
    f.write_text(json.dumps({"component": "open-gpu-kernel-modules",
                             "intended_tag_version": "0.0.0-not-this-one",
                             "intended_revision": "deadbeef"}))
    monkeypatch.setattr(R, "PIN", str(f))
    p = R.pinned()
    assert p["matches"] is False
    assert "0.0.0-not-this-one" in p["why"]


def test_a_missing_pin_is_named_not_treated_as_agreement(monkeypatch, tmp_path):
    """Silence must never read as consent — a missing pin is a gap, not a match."""
    monkeypatch.setattr(R, "PIN", str(tmp_path / "absent.json"))
    p = R.pinned()
    assert p["matches"] is None, "a missing pin must not report a match either way"
    assert "no pin at" in p["why"]
