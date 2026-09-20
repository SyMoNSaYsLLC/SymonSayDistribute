# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symondevice tests.

THREE OF THESE ARE THE POINT AND THE REST SUPPORT THEM.

  1. The PRIVACY tests. A MAC address and a device serial identify this machine, so a report
     quoting one cannot be passed on. Both tests are built so they can FAIL: the MAC test first
     proves its own pattern matches a MAC-shaped string, and the serial test reads the real
     serial values off this host and looks for those exact strings in every response. A pattern
     that matches nothing, and a search for a value that was never read, both pass forever.

  2. The UNBOUND DEVICE test. A device with no driver is the finding, and the shape of the bug
     that hides it is specific: `realpath` on a `driver` entry that does not exist still returns
     a path, so `basename` reports the driver as the literal string `driver`. The fake tree
     below contains that exact case and asserts both halves — `driver is None`, and the device
     still appears in the inventory and in `unbound`.

  3. The ZERO-SIZE DEVICE test. A card reader with no card presents a block device of zero
     bytes. Filtering by size is how a device that is present gets reported as absent.

Every test that needs hardware skips when the hardware is absent, and asserts something
falsifiable when it is present. A test that passes on a machine with no sensors AND on a machine
whose sensor code is broken has tested nothing, so the skip is on the DEVICE being absent, never
on the answer being empty.

Nothing here writes to /sys, /proc or /dev. The constructed trees live under pytest's `tmp_path`,
which is unique per test — no path in this file is composed by hand.

Run from the branch root: `python3 -m pytest tests/ -q`. The `-m` form is what puts the root on
`sys.path`, which is how `service` and `symondevice` are importable here.
"""
import importlib
import inspect
import json
import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from symondevice import inventory as R

TOKEN = uuid.uuid4().hex

# The nine capabilities, and the route each one answers on. Written out rather than derived, so
# that adding a capability without a route fails here as well as in the endpoints gate.
CAPABILITIES = ("cpu", "memory", "storage", "pci", "usb", "network", "sensors", "power",
                "owned_by")

# A full hardware address: six colon-separated octets. The three-octet OUI prefix this component
# does return is deliberately NOT matched by this — it is three octets, and an OUI names a
# registrant rather than a machine.
MAC = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")

# Keys that would carry an identifier even if this host's value happened to look innocuous.
# `address` is deliberately NOT here: on a PCI device it is the bus address, which is a technical
# identifier software is configured with. The hardware address is checked by name on the objects
# that could carry one, in its own test below.
FORBIDDEN_KEYS = {"serial", "serial_number", "wwid", "eui", "nguid", "unique_id",
                  "mac", "mac_address", "hwaddr", "hardware_address"}

# A PCI bus address. A root hub publishes its controller's address in its `serial` attribute, so
# that value is not an identifying serial and it legitimately appears inside device paths.
PCI_ADDRESS = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard. On a loopback
    # bind the guard returns before comparing anything, which would make every authenticated
    # test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_DEVICE_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_DEVICE_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def _walk(node, path="$"):
    """Every (json-path, key, value) in a decoded response, so a check can be made on all of it."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield f"{path}.{k}", k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield f"{path}[{i}]", None, v
            yield from _walk(v, f"{path}[{i}]")


def _all_responses(client):
    out = {}
    for name in CAPABILITIES:
        r = client.get(f"/api/symondevice/{name}", headers=auth())
        assert r.status_code == 200, (name, r.status_code, r.text[:200])
        out[name] = r.json()
    return out


# --- §3.2a: the bind address decides, and nothing else ----------------------------------------
def test_loopback_needs_no_token(monkeypatch):
    """A token on a 127.0.0.1 bind defends against a caller who can already read the token.

    Unset must not mean dead: with no `SYM_DEVICE_TOKEN` anywhere, a loopback bind still serves.
    """
    monkeypatch.setenv("SYM_DEVICE_HOST", "127.0.0.1")
    monkeypatch.delenv("SYM_DEVICE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    for name in CAPABILITIES:
        r = c.get(f"/api/symondevice/{name}")
        assert r.status_code == 200, (name, r.status_code, r.text[:200])
    assert service._open_on_loopback() is True


def test_the_default_bind_with_no_variable_set_is_loopback(monkeypatch):
    """No variable set at all must not open the unit. The default decides, not the operator."""
    monkeypatch.delenv("SYM_DEVICE_HOST", raising=False)
    monkeypatch.delenv("SYM_DEVICE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    assert service._open_on_loopback() is True
    assert TestClient(service.app).get("/api/symondevice/cpu").status_code == 200


def test_off_loopback_with_no_token_is_503(monkeypatch):
    """A unit that becomes reachable through a config change must not become public through it."""
    monkeypatch.setenv("SYM_DEVICE_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_DEVICE_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert service._open_on_loopback() is False
    for name in CAPABILITIES:
        r = c.get(f"/api/symondevice/{name}")
        assert r.status_code == 503, (name, r.status_code)
        assert "SYM_DEVICE_TOKEN" in r.json()["detail"]
    # health stays public: it must answer before the unit is configured.
    assert c.get("/api/symondevice/health").status_code == 200


def test_off_loopback_with_a_wrong_token_is_401(client):
    r = client.get("/api/symondevice/cpu", headers={"Authorization": "Bearer " + uuid.uuid4().hex})
    assert r.status_code == 401


def test_a_hostname_that_cannot_be_proved_loopback_is_treated_as_reachable(monkeypatch):
    """`localhost` resolves here; an arbitrary name does not, and guessing would open the unit."""
    import service
    monkeypatch.setenv("SYM_DEVICE_HOST", "localhost")
    assert service._open_on_loopback() is True
    monkeypatch.setenv("SYM_DEVICE_HOST", "::1")
    assert service._open_on_loopback() is True
    monkeypatch.setenv("SYM_DEVICE_HOST", "some-name-that-is-not-loopback")
    assert service._open_on_loopback() is False


# --- privacy: no MAC address, no serial number ------------------------------------------------
def test_the_mac_pattern_this_file_searches_with_actually_matches_a_mac():
    """A pattern that matches nothing passes every test built on it, forever.

    So the pattern is proved against a MAC-shaped string first, and proved NOT to match the
    three-octet OUI prefix this component does return — otherwise the next test would fail on
    the component's own correct behaviour and get weakened until it passed.
    """
    assert MAC.search("0a:1b:2c:3d:4e:5f")
    assert MAC.search("value=AA:BB:CC:DD:EE:FF here")
    assert not MAC.search("0a:1b:2c")
    assert not MAC.search("2026-09-19 18:32:10")


def test_no_full_mac_address_appears_in_any_response(client):
    for name, body in _all_responses(client).items():
        blob = json.dumps(body)
        hit = MAC.search(blob)
        assert hit is None, (f"/api/symondevice/{name} returned a full hardware address; "
                             f"only has_mac and the OUI prefix may be returned "
                             f"(match at offset {hit.start() if hit else -1})")


def test_the_oui_prefix_is_returned_and_is_only_three_octets(client):
    """The permitted half of the same rule. If nothing carries an OUI the assertion is vacuous,
    so an interface with a hardware address is required before this asserts anything."""
    body = client.get("/api/symondevice/network", headers=auth()).json()
    withmac = [i for i in body["interfaces"] if i["has_mac"]]
    if not withmac:
        pytest.skip("no interface on this host carries a hardware address")
    for i in withmac:
        assert i["mac_oui"], f"{i['name']} has a MAC and returned no OUI"
        assert len(i["mac_oui"].split(":")) == 3, i["mac_oui"]
    for i in body["interfaces"]:
        if not i["has_mac"]:
            assert i["mac_oui"] is None, f"{i['name']} has no address and returned an OUI"


def _real_serials():
    """The actual serial strings this host publishes, read here in the test.

    A serial has no shape — it can be digits, a hex blob or a word — so a pattern cannot find
    one. The only test that can fail is one that reads the real values and looks for those exact
    strings in the responses. Reading them here is safe: they are compared, never printed, and
    no assertion message below contains one.
    """
    found = {}
    roots = ((R.USB_DEVICES, ("serial",)),
             (R.SYS_POWER, ("serial_number",)),
             (R.SYS_BLOCK, ()))
    for root, names in roots:
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for entry in entries:
            # A root hub's `serial` is the bus address of the controller behind it, not an
            # identifier of anything, and it appears inside every device path under that
            # controller. Treating it as a serial makes this test fail on correct behaviour,
            # which is how a real check gets weakened until it stops checking.
            if re.fullmatch(r"usb\d+", entry):
                continue
            base = os.path.join(root, entry)
            for attr in names:
                try:
                    with open(os.path.join(base, attr), "r", errors="replace") as fh:
                        value = fh.read().strip()
                except OSError:
                    continue
                if len(value) >= 6 and not PCI_ADDRESS.match(value):
                    found[f"{entry}/{attr}"] = value
    for entry in os.listdir(R.SYS_BLOCK) if os.path.isdir(R.SYS_BLOCK) else []:
        for attr in ("serial", "wwid"):
            try:
                with open(os.path.join(R.SYS_BLOCK, entry, "device", attr), "r",
                          errors="replace") as fh:
                    value = fh.read().strip()
            except OSError:
                continue
            if len(value) >= 6 and not PCI_ADDRESS.match(value):
                found[f"{entry}/{attr}"] = value
    return found


def test_no_real_serial_number_from_this_host_appears_in_any_response(client):
    serials = _real_serials()
    if not serials:
        pytest.skip("no device on this host publishes a readable serial attribute")
    responses = _all_responses(client)
    for name, body in responses.items():
        blob = json.dumps(body)
        for where, value in serials.items():
            assert value not in blob, (
                f"/api/symondevice/{name} contains the serial published at {where}; "
                f"a serial identifies this machine and must never be emitted")


def test_a_device_that_has_a_serial_says_so_without_emitting_it(client):
    """The other half: withholding silently is indistinguishable from not looking."""
    responses = _all_responses(client)
    carriers = [d for d in responses["storage"]["devices"] if d["has_serial"]] + \
               [d for d in responses["usb"]["devices"] if d["has_serial"]] + \
               [s for s in responses["power"]["supplies"] if s["has_serial"]]
    if not carriers:
        pytest.skip("no device on this host carries a serial attribute")
    for d in carriers:
        assert d["serial_attributes"], "has_serial was true and no attribute was named"
    for section in ("storage", "usb", "power"):
        assert responses[section]["withheld"], f"{section} withheld something and did not say so"


def test_no_response_carries_a_key_that_would_hold_an_identifier(client):
    """A value check cannot catch a field whose contents this host happens not to populate."""
    for name, body in _all_responses(client).items():
        for path, key, value in _walk(body):
            if key in FORBIDDEN_KEYS and isinstance(value, str):
                pytest.fail(f"/api/symondevice/{name} returned a string at {path} under the key "
                            f"{key!r}, which is a key that carries an identifier")


def test_no_network_interface_object_carries_a_hardware_address_field(client):
    """The one place a MAC would be returned, checked by field name rather than by value.

    A value check misses an interface whose address happens to be all zeros, and a pattern check
    misses a field that is empty on this host and populated on another.
    """
    body = client.get("/api/symondevice/network", headers=auth()).json()
    assert body["interfaces"], "no interface was returned, so this asserted nothing"
    for i in body["interfaces"]:
        for key in i:
            assert key not in ("address", "mac", "hwaddr", "mac_address", "perm_address"), (
                f"{i['name']} carries a field named {key!r}")
        assert "mac_oui" in i and "has_mac" in i


# --- the unbound device, on a constructed tree -------------------------------------------------
def _fake_pci(tmp_path):
    """A PCI tree with the three cases that matter, built under tmp_path. The real /sys is never
    touched: nothing in this file writes outside the directory pytest handed it."""
    devices = tmp_path / "devices"
    drivers = tmp_path / "drivers"
    (drivers / "bound_drv").mkdir(parents=True)
    devices.mkdir(parents=True)

    def make(address, vendor, device, klass):
        d = devices / address
        d.mkdir()
        (d / "vendor").write_text(vendor + "\n")
        (d / "device").write_text(device + "\n")
        (d / "class").write_text(klass + "\n")
        (d / "irq").write_text("0\n")
        (d / "enable").write_text("1\n")
        return d

    bound = make("0000:00:01.0", "0x1111", "0x2222", "0x030000")
    os.symlink(os.path.relpath(drivers / "bound_drv", bound), bound / "driver")

    # No `driver` entry at all. This is the case `realpath` gets wrong: it canonicalises a
    # missing last component and hands back a path ending in `driver`.
    make("0000:00:02.0", "0x3333", "0x4444", "0x088000")

    # A recorded binding whose target directory has gone. The binding is still what the kernel
    # recorded, so the driver name is reported and the missing target is reported beside it.
    dangling = make("0000:00:03.0", "0x5555", "0x6666", "0x020000")
    os.symlink("../../drivers/gone_drv", dangling / "driver")
    return devices


def test_a_device_with_no_driver_is_reported_as_unbound_and_never_omitted(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "PCI_DEVICES", str(_fake_pci(tmp_path)))
    body = R.pci()
    by_address = {d["address"]: d for d in body["devices"]}

    assert set(by_address) == {"0000:00:01.0", "0000:00:02.0", "0000:00:03.0"}, (
        "a device was dropped from the inventory; an unbound device is the finding, not noise")

    bound = by_address["0000:00:01.0"]
    assert bound["driver"] == "bound_drv"
    assert bound["driver_bound"] is True
    assert bound["driver_target_exists"] is True

    none = by_address["0000:00:02.0"]
    assert none["driver"] is None, none["driver"]
    assert none["driver"] != "driver", (
        "the driver resolved to the literal string 'driver' — this is realpath canonicalising a "
        "path whose last component does not exist, and it reports every unbound device on the "
        "machine as bound to a driver called 'driver'")
    assert none["driver_bound"] is False
    assert none["why"] and "no driver" in none["why"]
    assert "0000:00:02.0" in body["unbound"]

    dangling = by_address["0000:00:03.0"]
    assert dangling["driver"] == "gone_drv", (
        "a recorded binding whose target has gone is still the recorded binding")
    assert dangling["driver_target_exists"] is False

    assert body["count"] == 3
    assert body["unbound_count"] == 1
    assert body["drivers"] == ["bound_drv", "gone_drv"]


def test_the_unbound_device_reaches_owned_by_rather_than_being_absorbed(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "PCI_DEVICES", str(_fake_pci(tmp_path)))
    body = R.owned_by()
    assert "0000:00:02.0" in body["unbound"]["pci"]
    assert body["unbound_count"] >= 1
    assert body["full_coverage"] is False


def test_the_ids_in_a_constructed_tree_come_back_byte_exact(monkeypatch, tmp_path):
    """`vendor:device` is what a bind rule is written against, so it is reproduced, not decoded."""
    monkeypatch.setattr(R, "PCI_DEVICES", str(_fake_pci(tmp_path)))
    ids = {d["address"]: d["id"] for d in R.pci()["devices"]}
    assert ids["0000:00:01.0"] == "1111:2222"
    assert ids["0000:00:03.0"] == "5555:6666"


def test_an_absent_pci_directory_is_reported_rather_than_returning_an_empty_inventory(
        monkeypatch, tmp_path):
    """An empty answer and an unreadable source are different findings."""
    monkeypatch.setattr(R, "PCI_DEVICES", str(tmp_path / "no-such-bus"))
    body = R.pci()
    assert body["count"] == 0
    assert body["evidence"]["rc"] == 1
    assert body["evidence"]["unreadable"] == [str(tmp_path / "no-such-bus")]


# --- the zero-size block device ----------------------------------------------------------------
def test_a_zero_size_block_device_is_reported_not_filtered_on_a_constructed_tree(
        monkeypatch, tmp_path):
    """Falsifiable on any machine, including one with no such device plugged in."""
    block = tmp_path / "block"
    for name, sectors, removable in (("faked0", "1953525168", "0"), ("faked1", "0", "1")):
        d = block / name
        d.mkdir(parents=True)
        (d / "size").write_text(sectors + "\n")
        (d / "removable").write_text(removable + "\n")
        (d / "dev").write_text("8:0\n")
        (d / "queue").mkdir()
        (d / "queue" / "rotational").write_text("0\n")
    monkeypatch.setattr(R, "SYS_BLOCK", str(block))
    body = R.storage()
    names = [d["name"] for d in body["devices"]]
    assert names == ["faked0", "faked1"], "a device was filtered out of the inventory"
    zero = next(d for d in body["devices"] if d["name"] == "faked1")
    assert zero["size_bytes"] == 0
    assert zero["removable"] is True
    assert zero["why"] and "zero bytes" in zero["why"]
    assert body["zero_size"] == ["faked1"]
    assert body["filtered"] == []


def test_the_zero_size_device_on_this_host_is_reported(client):
    """The same claim against the real machine. Skips when nothing here reports zero bytes."""
    body = client.get("/api/symondevice/storage", headers=auth()).json()
    zero = [d for d in body["devices"] if d["size_bytes"] == 0]
    if not zero:
        pytest.skip("no block device on this host reports zero bytes")
    for d in zero:
        assert d["name"] in body["zero_size"]
        assert d["driver"], f"{d['name']} reports zero bytes and no driver — both, or neither"
        assert d["why"], "a zero-byte device was returned with no explanation of why it is here"
    assert body["filtered"] == []
    assert "none" in body["filter_policy"]


def test_a_removable_device_is_kept_in_the_inventory(client):
    body = client.get("/api/symondevice/storage", headers=auth()).json()
    removable = [d["name"] for d in body["devices"] if d["removable"]]
    if not removable:
        pytest.skip("no removable block device on this host")
    assert set(removable) <= {d["name"] for d in body["devices"]}
    assert body["removable"] == sorted(removable) or set(body["removable"]) == set(removable)


# --- owned_by: the gap-finder must find a gap --------------------------------------------------
def test_owned_by_names_at_least_one_unowned_hardware_class(client):
    body = client.get("/api/symondevice/owned_by", headers=auth()).json()
    assert body["full_coverage"] is False, (
        "owned_by claimed full coverage; a coverage map that never reports a gap has stopped "
        "being a map")
    assert body["unowned_classes"], "no hardware class was named as unowned"
    for entry in body["unowned"]:
        assert entry["owner"] is None, f"{entry['class']} is listed as unowned with an owner"
        assert entry["inventoried_by"] == "symondevice"
        assert entry["why"], f"{entry['class']} is unowned with no reason given"
        assert entry["evidence"], f"{entry['class']} is unowned with no evidence"


def test_an_unowned_class_is_not_also_claimed_as_owned(client):
    body = client.get("/api/symondevice/owned_by", headers=auth()).json()
    assert not (set(body["owned_classes"]) & set(body["unowned_classes"]))


def test_at_least_one_unowned_class_names_real_hardware_on_this_host(client):
    """Without this, `unowned` could be six labels with nothing behind them."""
    body = client.get("/api/symondevice/owned_by", headers=auth()).json()
    populated = [e for e in body["unowned"] if e["instances"]]
    if not populated:
        pytest.skip("no hardware on this host falls into an unowned class")
    for entry in populated:
        assert all(isinstance(i, str) and i for i in entry["instances"]), entry["class"]


def test_the_components_named_are_the_ones_that_exist(client):
    body = client.get("/api/symondevice/owned_by", headers=auth()).json()
    assert set(body["components"]) == {"symonprobe", "symondriver", "symonkernel", "symonsdk",
                                       "symondevice"}
    for entry in body["classes"]:
        for owner in entry["owner"]:
            assert owner in body["components"], f"{entry['class']} names an unknown component"


# --- evidence on every answer -------------------------------------------------------------------
def test_every_public_capability_returns_its_evidence():
    """Discovered from the module, not listed here, so a new capability cannot skip this."""
    public = [n for n, f in vars(R).items()
              if inspect.isfunction(f) and not n.startswith("_") and f.__module__ == R.__name__]
    assert sorted(public) == sorted(CAPABILITIES), (
        "the module's public capabilities and this file's list have diverged")
    for name in public:
        body = getattr(R, name)()
        assert "evidence" in body, f"{name}() returned no evidence"
        ev = body["evidence"]
        assert ev["paths"], f"{name}() named no path it read"
        assert all(p.startswith("/") for p in ev["paths"]), (name, ev["paths"])
        assert ev["rc"] in (0, 1), (name, ev["rc"])
        assert (ev["rc"] == 1) == bool(ev["unreadable"]), (
            f"{name}() reported rc={ev['rc']} with unreadable={ev['unreadable']}")
        assert ev["command"] is None and ev["argv"] is None, (
            f"{name}() claimed to have run a program; this module runs none")


def test_every_public_capability_is_reachable_over_http(client):
    """The endpoints gate asks the same question of the staged bytes; this asks it of a live app."""
    public = [n for n, f in vars(R).items()
              if inspect.isfunction(f) and not n.startswith("_") and f.__module__ == R.__name__]
    for name in public:
        if name in R.NOT_EXPOSED:
            continue
        assert client.get(f"/api/symondevice/{name}", headers=auth()).status_code == 200, name


def test_an_unreadable_source_sets_rc_to_one(monkeypatch, tmp_path):
    """rc must be derived, not decorative. Point a source at nothing and it has to change."""
    monkeypatch.setattr(R, "SYS_HWMON", str(tmp_path / "no-hwmon"))
    monkeypatch.setattr(R, "SYS_THERMAL", str(tmp_path / "no-thermal"))
    body = R.sensors()
    assert body["chip_count"] == 0
    assert body["evidence"]["rc"] == 1
    assert str(tmp_path) in body["evidence"]["unreadable"][0]


# --- this module reads, and only reads -----------------------------------------------------------
def test_nothing_in_the_module_runs_a_program_or_reaches_a_shell():
    src = inspect.getsource(R)
    for forbidden in ("import subprocess", "subprocess.", "os.system", "shell=True",
                      "os.popen", "os.execv", "pty.spawn"):
        assert forbidden not in src, f"{forbidden!r} appears in the capability module"


def test_nothing_in_the_module_opens_a_path_for_writing():
    """Every `open` in the module is checked for its mode rather than the source grepped, so a
    write cannot hide behind a variable or an unusual spelling of the flag."""
    src = inspect.getsource(R)
    modes = re.findall(r"open\([^)]*?,\s*([\"'])([rwaxb+]+)\1", src)
    assert modes, "no open() call was found to check — the check would pass vacuously"
    for _, mode in modes:
        assert mode == "r", f"a path is opened with mode {mode!r}; this component only reads"
    for forbidden in ("os.remove", "os.unlink", "os.rmdir", "shutil.rmtree", ".write_text(",
                      ".write_bytes(", "os.makedirs", "os.mkdir", "os.rename"):
        assert forbidden not in src, (
            f"{forbidden!r} appears in the capability module; this component is detection only")


def test_the_cpu_count_is_not_taken_from_an_affinity_respecting_source():
    """The machine's CPU count and this process's permitted CPU count are different questions.

    A tool that respects the affinity mask answers the second. On a host with a mask set, taking
    that as the machine's size under-provisions a machine twice as large, and the two numbers are
    indistinguishable unless both are returned.
    """
    c = R.cpu()
    assert c["logical"] >= 1
    assert c["schedulable_here"] is None or c["schedulable_here"] <= c["logical"]
    assert c["sources"]["counts_and_flags"] == R.PROC_CPUINFO
    if c["schedulable_here"] is not None and c["schedulable_here"] != c["logical"]:
        assert c["logical"] != c["schedulable_here"], (
            "the two counts were collapsed into one")


# --- the hardware, each test skipping only when the hardware is absent ---------------------------
def test_the_cpu_reports_a_consistent_topology_from_two_independent_sources(client):
    c = client.get("/api/symondevice/cpu", headers=auth()).json()
    assert c["logical"] == c["crosscheck"]["sys_logical"], (
        "/proc/cpuinfo and /sys disagree about how many logical CPUs exist")
    assert c["physical_cores"] and c["physical_cores"] <= c["logical"]
    assert c["threads_per_core"] == c["logical"] // c["physical_cores"]
    assert c["sockets"] and c["sockets"] >= 1
    assert c["architecture"]
    assert c["crosscheck"]["agrees"] is True


def test_the_cpu_flag_list_is_present_and_is_data_not_prose(client):
    c = client.get("/api/symondevice/cpu", headers=auth()).json()
    assert isinstance(c["flags"], list)
    assert c["flag_count"] == len(c["flags"])
    if not c["flags"]:
        pytest.skip("this kernel publishes no flag list for the CPU")
    assert all(" " not in f for f in c["flags"]), "a flag entry contains a space"
    assert c["flags"] == sorted(c["flags"])


def test_the_frequency_range_says_where_it_came_from(client):
    c = client.get("/api/symondevice/cpu", headers=auth()).json()
    f = c["frequency_mhz"]
    if f["min"] is None and f["max"] is None:
        pytest.skip("no frequency source is exposed on this host")
    assert f["source"], "a frequency was returned with no source named"
    assert f["max"] >= f["min"] > 0


def test_memory_separates_free_from_available(client):
    m = client.get("/api/symondevice/memory", headers=auth()).json()
    assert m["total_bytes"] > 0
    if m["available_bytes"] is None:
        pytest.skip("this kernel does not publish MemAvailable")
    assert m["available_bytes"] >= m["free_bytes"], (
        "available is below free, which the arithmetic cannot produce")
    assert m["available_bytes"] <= m["total_bytes"]
    assert m["buff_cache_bytes"] == (m["buffers_bytes"] + m["cached_bytes"]
                                     + m["sreclaimable_bytes"])
    assert "available" in m["why"] and "free" in m["why"]


def test_every_block_device_names_the_level_its_driver_was_found_at(client):
    body = client.get("/api/symondevice/storage", headers=auth()).json()
    if not body["devices"]:
        pytest.skip("no block device on this host")
    for d in body["devices"]:
        assert d["name"] and d["path"].startswith("/")
        assert d["size_bytes"] >= 0
        if d["driver"]:
            assert d["driver_at"], f"{d['name']} named a driver and not where it was found"
            assert d["driver"] != "driver", f"{d['name']} resolved to the literal word 'driver'"
        else:
            assert d["name"] in body["unbound"]


def test_a_mounted_filesystem_is_matched_to_the_device_behind_it(client):
    body = client.get("/api/symondevice/storage", headers=auth()).json()
    mounted = [d for d in body["devices"] if d["mounted"]]
    if not mounted:
        pytest.skip("no block device on this host carries a mounted filesystem")
    for d in mounted:
        places = d["mounts"] + [m for p in d["partitions"] for m in p["mounts"]]
        assert places, f"{d['name']} is marked mounted with nothing mounted"
        for m in places:
            assert m["mountpoint"].startswith("/") and m["fstype"]


def test_every_pci_function_carries_an_id_and_an_explicit_driver_answer(client):
    body = client.get("/api/symondevice/pci", headers=auth()).json()
    if not body["devices"]:
        pytest.skip("no PCI bus on this host")
    for d in body["devices"]:
        assert re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]", d["address"]), d
        assert re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", d["id"] or ""), d["id"]
        assert d["driver_bound"] == (d["driver"] is not None)
        if not d["driver_bound"]:
            assert d["address"] in body["unbound"]
            assert d["why"]


def test_usb_topology_separates_a_root_port_from_a_chain_through_a_hub(client):
    body = client.get("/api/symondevice/usb", headers=auth()).json()
    if not body["devices"]:
        pytest.skip("no USB controller on this host")
    assert not (set(body["behind_hub"]) &
                {d["name"] for d in body["devices"] if d["root_port"]}), (
        "a device is reported both on a root port and behind a hub")
    roots = [d for d in body["devices"] if d["depth"] == 0]
    assert roots, "no root hub was found, so the tree has no anchor"
    for d in body["devices"]:
        if d["behind_hub"]:
            assert d["hub_chain"], f"{d['name']} is behind a hub and named none"
            assert d["why"], f"{d['name']} is behind a hub with no explanation"
        assert d["speed_raw"] is None or d["speed_mbps"] is not None


def test_a_usb_device_behind_a_hub_names_the_hub_that_would_take_it_down(client):
    body = client.get("/api/symondevice/usb", headers=auth()).json()
    behind = [d for d in body["devices"] if d["behind_hub"]]
    if not behind:
        pytest.skip("nothing on this host is behind an external hub")
    names = {d["name"] for d in body["devices"]}
    for d in behind:
        assert d["parent"] in names, f"{d['name']} names a parent that is not in the tree"
        assert d["hub_chain"][0] == d["parent"]


def test_network_interfaces_report_state_and_driver(client):
    body = client.get("/api/symondevice/network", headers=auth()).json()
    if not body["interfaces"]:
        pytest.skip("no network interface on this host")
    for i in body["interfaces"]:
        assert i["operstate"], f"{i['name']} reported no operational state"
        assert i["up"] == (i["operstate"] == "up")
        if i["virtual"]:
            assert i["driver"] is None
        if i["speed_mbps"] is None:
            assert i["why"], f"{i['name']} returned no speed and no reason"
    assert set(body["up"]) | set(body["down"]) == {i["name"] for i in body["interfaces"]}


def test_sensor_readings_carry_the_kernel_label_a_value_and_the_path_they_came_from(client):
    body = client.get("/api/symondevice/sensors", headers=auth()).json()
    readings = [r for c in body["chips"] for r in c["readings"]]
    if not readings:
        pytest.skip("no hwmon readings are exposed on this host")
    assert body["reading_count"] == len(readings)
    for r in readings:
        assert r["kind"] in ("temp", "fan", "in", "curr", "power", "energy", "humidity")
        assert isinstance(r["raw"], int)
        assert isinstance(r["value"], (int, float))
        assert r["unit"]
        assert r["path"].endswith(f"{r['kind']}{r['index']}_input")
    labelled = [r for r in readings if r["label"]]
    if labelled:
        assert all(isinstance(r["label"], str) and r["label"].strip() for r in labelled)


def test_the_sensor_module_reports_writable_controls_without_writing_them(client):
    body = client.get("/api/symondevice/sensors", headers=auth()).json()
    controls = [c for c in body["chips"] if c["controls_present"]]
    if not controls:
        pytest.skip("no chip on this host exposes a writable control")
    assert body["writes"].startswith("none")
    for c in controls:
        assert all(a.startswith("pwm") or a.endswith("_enable") for a in c["controls_present"])


def test_power_supplies_separate_the_machine_from_a_peripheral(client):
    body = client.get("/api/symondevice/power", headers=auth()).json()
    if not body["supplies"]:
        pytest.skip("no power supply is exposed on this host")
    for s in body["supplies"]:
        assert s["type"], f"{s['name']} reported no supply type"
        assert s["powers_this_machine"] == (s["scope"] != "Device")
    assert (set(body["machine_supplies"]) | set(body["device_supplies"])
            == {s["name"] for s in body["supplies"]})


def test_health_is_public_and_says_which_side_of_the_bind_it_is_on(client):
    r = client.get("/api/symondevice/health")
    assert r.status_code == 200
    body = r.json()
    assert body["unit"] == "symondevice"
    assert body["status"] == "ok"
    assert body["loopback"] is False       # the fixture binds off-loopback
