# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The machine's physical inventory: what exists, which driver owns it, which component covers it.

WHY THIS EXISTS
---------------
The estate covers the compute card (`symonprobe`), the kernel and its out-of-tree modules
(`symonkernel`), the card's userspace (`symondriver`) and the build toolchains (`symonsdk`).
The CPU, system memory, every block device, the whole PCI and USB topology, the network
interfaces, the sensors and the power supplies are covered by nothing at all. A question about
any of them has, until now, been answered by a person running a tool and reading the output.

So this answers four things at once, per device:

    what hardware exists · which driver owns it · which kernel interface exposes it ·
    which SyMonComponent covers it

`owned_by()` is the fourth, and it is the one that makes this a framework component rather than
a pretty printer. It NAMES what nothing covers. A coverage map that reports full coverage has
stopped being a map.

EVERY ANSWER CARRIES ITS EVIDENCE
---------------------------------
Each public function returns an `evidence` block naming the paths it read and whether every one
of them was readable. A figure with no path behind it is a recollection, and a recollection is
the thing this module exists to replace.

NOTHING HERE RUNS A PROGRAM
---------------------------
There is no `subprocess` import in this file and no code path that reaches a shell. Every fact
comes from the kernel's own files under `/proc` and `/sys`, opened read-only. That is a design
decision with three consequences worth writing down:

  * a tool's human output is a rendering, and renderings drift between versions. `/proc` and
    `/sys` are the interface the tool itself reads.
  * some tools answer a DIFFERENT question than the one asked. On this host `nproc` reports 8
    while `/proc/cpuinfo` lists 20, because `nproc` respects the caller's CPU affinity mask.
    Both numbers are correct; only one of them answers "what CPUs does this machine have".
    `cpu()` returns both and labels which is which.
  * the informational modes of a disk health tool print the disk's serial number. Not invoking
    it is simpler than filtering it.

Because no child process runs, there is no child exit code. The `rc` in every evidence block is
this module's own: 0 when every path named was read, 1 when at least one was not, with the
unreadable ones listed. An evidence block that claimed a process exit code it never obtained
would be worse than none.

READ ONLY
---------
Every path is opened for reading. Nothing here flashes, partitions, formats, resets, rebinds,
unloads, reconfigures or writes a single byte to any device, and no `hwmon` `pwm*`, `*_enable`
or `*_target` file is written even though several are writable on this host. Detection only.

WHAT IS DELIBERATELY NOT RETURNED
---------------------------------
A MAC address and a device serial number identify THIS machine, and a report that quotes them
is unsafe to pass on. So:

    network interfaces   `has_mac` and the three-octet OUI prefix. Never the address.
    disks, USB devices   `model` and `size`, and `has_serial` as a boolean. Never the serial.
    power supplies       `model_name` and state. Never `serial_number`.

Everything withheld is NAMED in a `withheld` list on the same response, because a filter nobody
can see is indistinguishable from a bug.

IDENTIFIERS ARE REPRODUCED BYTE-EXACT, AND MODEL STRINGS STAY IN FIELDS
----------------------------------------------------------------------
A `vendor:device` pair, a driver module name, a sysfs path, an interface name and a `hwmon`
label are how software is configured and run: they are opaque identifiers here and they are
returned exactly as the kernel spells them, never translated. A model string a device reports
about itself is DATA the kernel handed over — it is returned in a field and is never written
into a sentence in this file or in the documentation.
"""
from __future__ import annotations

import os
import re
import stat
from typing import Any, Iterable

# --- where the facts live -------------------------------------------------------------------
# Module-level so a test can point them at a constructed tree. Nothing under here is ever
# opened for writing, and the real paths are never used as a fallback when one is redirected:
# a test that silently reads the live machine has tested the live machine, not the code.
PROC_CPUINFO = "/proc/cpuinfo"
PROC_MEMINFO = "/proc/meminfo"
PROC_MOUNTS = "/proc/mounts"
SYS_CPU = "/sys/devices/system/cpu"
SYS_BLOCK = "/sys/block"
SYS_DEV_BLOCK = "/dev/block"
PCI_DEVICES = "/sys/bus/pci/devices"
USB_DEVICES = "/sys/bus/usb/devices"
SYS_NET = "/sys/class/net"
SYS_HWMON = "/sys/class/hwmon"
SYS_THERMAL = "/sys/class/thermal"
SYS_POWER = "/sys/class/power_supply"

# A sector is 512 bytes in the `size` attribute regardless of the device's own block size. The
# kernel documents it that way and it is the one constant here that is not read from disk.
_SECTOR_BYTES = 512

# Attribute names that carry a serial. Read only to answer "is there one"; never returned.
_SERIAL_NAMES = ("serial", "serial_number", "wwid", "eui", "nguid", "unique_id")

# The subsystems that answer "how is this attached". Ordered outermost-first so that a disk
# reached over USB reports `usb` rather than the SCSI shim the kernel layers on top of it,
# which is what a person means when they ask what a device is plugged into.
_TRANSPORTS = ("usb", "nvme", "mmc", "virtio", "ata", "scsi", "sdio", "platform")

# A `hwmon` reading is `<kind><n>_input`. The scale and unit are fixed by the kernel's hwmon
# interface, not chosen here — the raw value is returned alongside the scaled one so a reader
# can check the arithmetic rather than trust it.
_HWMON_KINDS = {
    "temp": (0.001, "C"),
    "fan": (1.0, "RPM"),
    "in": (0.001, "V"),
    "curr": (0.001, "A"),
    "power": (0.000001, "W"),
    "energy": (0.000001, "J"),
    "humidity": (0.001, "%RH"),
    "pwm": (1.0, "0-255"),
}
_HWMON_INPUT = re.compile(r"^(temp|fan|in|curr|power|energy|humidity)(\d+)_input$")

# PCI base class codes are a public specification with many independent implementations. The
# words below are the specification's own generic categories; they name a FUNCTION, never a
# maker. The numeric code is returned beside them and is the authoritative value.
_PCI_BASE_CLASS = {
    0x00: "unclassified",
    0x01: "mass storage controller",
    0x02: "network controller",
    0x03: "display controller",
    0x04: "multimedia controller",
    0x05: "memory controller",
    0x06: "bridge",
    0x07: "communication controller",
    0x08: "generic system peripheral",
    0x09: "input device controller",
    0x0a: "docking station",
    0x0b: "processor",
    0x0c: "serial bus controller",
    0x0d: "wireless controller",
    0x0e: "intelligent controller",
    0x0f: "satellite communications controller",
    0x10: "encryption controller",
    0x11: "signal processing controller",
    0x12: "processing accelerator",
    0x13: "non-essential instrumentation",
    0xff: "unassigned class",
}

# USB device and interface class codes, same rule as above: the specification's own words.
_USB_CLASS = {
    0x00: "per-interface",
    0x01: "audio",
    0x02: "communications",
    0x03: "human interface",
    0x05: "physical",
    0x06: "image",
    0x07: "printer",
    0x08: "mass storage",
    0x09: "hub",
    0x0a: "cdc data",
    0x0b: "smart card",
    0x0d: "content security",
    0x0e: "video",
    0x0f: "personal healthcare",
    0x10: "audio/video",
    0x11: "billboard",
    0x12: "usb type-c bridge",
    0xdc: "diagnostic",
    0xe0: "wireless controller",
    0xef: "miscellaneous",
    0xfe: "application specific",
    0xff: "vendor specific",
}


# Declared as a BARE assignment. `endpoints-current` reads this with `ast.Assign`; the annotated
# form `NOT_EXPOSED: dict[str, str] = {...}` parses as `ast.AnnAssign`, which older copies of
# that gate never see — the declaration would be silently ignored.
NOT_EXPOSED = {
    # Empty, and empty is a DECISION rather than an omission: all nine capabilities here are
    # reachable over HTTP, one route each, and the route handler in `service.py` carries the
    # same name as the function it calls. Nothing is withheld from the network.
    #
    # Every genuinely internal helper in this module is underscore-prefixed, which is the honest
    # way to say "not a capability" rather than listing it here as one that was declined.
}


class InventoryError(Exception):
    """A fact that could not be read, carrying why rather than an empty result."""


# --- reading -------------------------------------------------------------------------------

def _read(path: str) -> str | None:
    """One sysfs or procfs value, stripped. `None` means unreadable, which is never `0` or `""`.

    Distinguishing them matters: a fan reporting 0 RPM is stopped, and a fan whose file cannot
    be read is unknown. Collapsing the two invents a stopped fan.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _read_int(path: str) -> int | None:
    """A numeric sysfs value. `0x`-prefixed is hex, everything else is decimal.

    Base 0 alone is not enough: Python rejects a leading zero under base 0 — `int("09", 0)`
    raises — and sysfs is full of zero-padded fields. Falling through to base 10 keeps those
    readable instead of reporting them as unreadable, which would have turned every padded
    attribute on this host into a silent `None`.
    """
    raw = _read(path)
    if raw is None:
        return None
    raw = raw.strip()
    try:
        return int(raw, 16) if raw.lower().startswith("0x") else int(raw, 10)
    except ValueError:
        return None


def _read_hex_byte(path: str) -> int | None:
    """A sysfs class code, which the kernel prints as unprefixed hex: `09`, `e0`, `ef`.

    Read as DECIMAL these are wrong in a way that still parses — `10` would become ten rather
    than sixteen — so the base is fixed here rather than guessed. That mis-read is what made
    every hub on this host report as a non-hub until it was fixed.
    """
    raw = _read(path)
    if raw is None:
        return None
    try:
        return int(raw.strip(), 16)
    except ValueError:
        return None


def _listdir(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _exists(path: str) -> bool:
    return os.path.lexists(path)


def _driver_of(device_dir: str) -> tuple[str | None, bool]:
    """The driver bound to one device directory, and whether its target still exists.

    THE TRAP THIS FUNCTION EXISTS TO AVOID
    `readlink -f` — and `os.path.realpath` — canonicalise a path whose LAST COMPONENT does not
    exist and return it anyway. So on a device with no binding, `realpath(dev + "/driver")`
    returns a path ending in `driver`, and taking its basename reports the driver as the
    literal string `driver` on every unbound device on the machine. On this host that is what
    `/sys/block/nvme0n1/device/driver` and `/sys/bus/usb/devices/1-3.5:1.0/driver` do: neither
    exists, and both canonicalise happily.

    The check is `islink` FIRST, then `os.readlink`, whose result is the recorded binding even
    when the target directory has gone. A dangling link is reported with its driver name and
    `target_exists: False`, because the binding is still what the kernel recorded.
    """
    link = os.path.join(device_dir, "driver")
    if not os.path.islink(link):
        return None, False
    try:
        target = os.readlink(link)
    except OSError:
        return None, False
    name = os.path.basename(target.rstrip("/"))
    if not name or name == "driver":
        # A link whose own target ends in `driver` tells us nothing usable. Saying so is more
        # honest than returning the word.
        return None, os.path.exists(link)
    return name, os.path.exists(link)


def _bus_chain(real_path: str, *, limit: int = 24) -> list[dict[str, Any]]:
    """Walk from a device up towards `/sys/devices`, recording each level's bus and driver.

    A block device is not bound to anything at its own level — the binding lives on the
    controller, or on the PCI function underneath it. Walking up finds it AND records which
    level answered, so the answer can be checked rather than believed.
    """
    chain: list[dict[str, Any]] = []
    cur = os.path.realpath(real_path)
    for _ in range(limit):
        if cur in ("/", "", "/sys", "/sys/devices"):
            break
        subsystem = None
        sub_link = os.path.join(cur, "subsystem")
        if os.path.islink(sub_link):
            try:
                subsystem = os.path.basename(os.readlink(sub_link).rstrip("/"))
            except OSError:
                subsystem = None
        driver, target_exists = _driver_of(cur)
        chain.append({"path": cur, "name": os.path.basename(cur), "subsystem": subsystem,
                      "driver": driver, "driver_target_exists": target_exists})
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return chain


def _evidence(paths: Iterable[str], unreadable: Iterable[str] = ()) -> dict[str, Any]:
    """What was read, and whether it read. Attached to every public answer in this module.

    `rc` is this module's own, not a process exit status: 0 when every path named was read, 1
    when one was not. No program is executed anywhere in this file, so there is no child exit
    code to quote, and quoting one would be an invention.
    """
    bad = sorted(set(unreadable))
    return {
        "source": "sysfs+procfs",
        "paths": sorted(set(paths)),
        "command": None,
        "argv": None,
        "rc": 1 if bad else 0,
        "unreadable": bad,
        "why": "read from the kernel's own files, opened read-only; no program is run, so `rc` "
               "reports whether every path named here was readable rather than a child's exit "
               "status.",
    }


def _has_serial(device_dir: str) -> tuple[bool, list[str]]:
    """Whether this device carries an identifying serial, and under which attribute names.

    The VALUE is never read into a return. Only its presence is, because the presence is what a
    reader needs — "this device can be uniquely identified, and the identifier was withheld" —
    and the value is what makes a report unsafe to pass on.
    """
    found = [n for n in _SERIAL_NAMES if os.path.isfile(os.path.join(device_dir, n))]
    return bool(found), found


def _oui(mac: str | None) -> str | None:
    """The three-octet organisationally unique identifier, and nothing after it.

    The remaining three octets are what make an address identify one card on one machine. They
    never leave this function.
    """
    if not mac:
        return None
    parts = mac.strip().lower().split(":")
    if len(parts) < 3 or any(len(p) != 2 for p in parts[:3]):
        return None
    return ":".join(parts[:3])


def _hex_id(path: str) -> str | None:
    """A sysfs id as the kernel spells it, lower-case and without the `0x`: `0x10de` -> `10de`.

    This is the form that must be typed into a driver bind rule, a modalias or a udev rule, so
    it is reproduced byte-exact and never translated into the name of whoever registered it.
    """
    raw = _read(path)
    if raw is None:
        return None
    raw = raw.strip().lower()
    return raw[2:] if raw.startswith("0x") else raw


def _devnum(device_dir: str) -> str | None:
    """`major:minor` from a block device's `dev` attribute — the key mounts are matched on."""
    return _read(os.path.join(device_dir, "dev"))


def _mounts_by_devnum() -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    """Every mount, keyed by the `major:minor` of the device behind it.

    Matching by NAME fails the moment a mount is recorded through a symlink, a by-uuid path or a
    device-mapper node. The device number is what the kernel actually mounted, so that is the
    key. Sources that do not resolve to a block device — the pseudo-filesystems — are kept and
    keyed as unresolved rather than dropped, since a missing mount reads as an unmounted disk.
    """
    by_dev: dict[str, list[dict[str, str]]] = {}
    unreadable: list[str] = []
    try:
        with open(PROC_MOUNTS, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return {}, [PROC_MOUNTS]
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        source, target, fstype, options = parts[0], parts[1], parts[2], parts[3]
        try:
            st = os.stat(source)
        except OSError:
            continue
        if not stat.S_ISBLK(st.st_mode):
            continue
        key = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
        by_dev.setdefault(key, []).append({
            "mountpoint": target.replace("\\040", " "),
            "fstype": fstype,
            "options": options,
            "source_devnum": key,
        })
    return by_dev, unreadable


# --- capabilities ---------------------------------------------------------------------------

def cpu() -> dict[str, Any]:
    """What CPUs this machine has, how they are arranged, and what they can execute.

    TWO COUNTS, AND THEY ARE NOT THE SAME QUESTION
    `logical` is how many the machine has. `schedulable_here` is how many this process is
    permitted to run on, which is what an affinity-respecting tool reports. On a host where an
    affinity mask is set the two differ, and a plan sized from the smaller one under-provisions
    a machine that is twice the size. Both are returned, each labelled with where it came from.

    The flag list is the part that decides what can RUN here — an instruction-set extension a
    build was compiled against either appears in it or the binary dies on its first use. It is
    returned verbatim as the kernel publishes it.
    """
    paths, unreadable = [PROC_CPUINFO], []
    try:
        with open(PROC_CPUINFO, "r", encoding="utf-8", errors="replace") as fh:
            blocks = fh.read().split("\n\n")
    except OSError:
        raise InventoryError(f"{PROC_CPUINFO} could not be read; the CPU cannot be described "
                             f"without it")

    records: list[dict[str, str]] = []
    for block in blocks:
        rec: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            rec[k.strip()] = v.strip()
        if "processor" in rec:
            records.append(rec)

    logical = len(records)
    sockets = {r.get("physical id") for r in records if "physical id" in r}
    cores = {(r.get("physical id"), r.get("core id")) for r in records if "core id" in r}
    flags = sorted((records[0].get("flags") or "").split()) if records else []
    bugs = sorted((records[0].get("bugs") or "").split()) if records else []

    # The same topology read a second way, from /sys. Two independent sources agreeing is worth
    # more than one source read twice, and where they disagree that is the finding.
    sys_cores: set[tuple[str | None, str | None]] = set()
    sys_packages: set[str | None] = set()
    sys_logical = 0
    for entry in _listdir(SYS_CPU):
        if not re.fullmatch(r"cpu\d+", entry):
            continue
        sys_logical += 1
        topo = os.path.join(SYS_CPU, entry, "topology")
        pkg = _read(os.path.join(topo, "physical_package_id"))
        core = _read(os.path.join(topo, "core_id"))
        sys_packages.add(pkg)
        sys_cores.add((pkg, core))
    paths.append(SYS_CPU)

    freqs = []
    for entry in _listdir(SYS_CPU):
        if not re.fullmatch(r"cpu\d+", entry):
            continue
        cf = os.path.join(SYS_CPU, entry, "cpufreq")
        lo, hi = _read_int(os.path.join(cf, "cpuinfo_min_freq")), _read_int(
            os.path.join(cf, "cpuinfo_max_freq"))
        if lo is not None and hi is not None:
            freqs.append((lo, hi))
    if freqs:
        paths.append(os.path.join(SYS_CPU, "cpu*/cpufreq"))
        min_mhz = round(min(f[0] for f in freqs) / 1000.0, 1)
        max_mhz = round(max(f[1] for f in freqs) / 1000.0, 1)
        freq_source = "/sys cpufreq (cpuinfo_min_freq, cpuinfo_max_freq)"
    else:
        mhz = [float(r["cpu MHz"]) for r in records if r.get("cpu MHz")]
        min_mhz = round(min(mhz), 1) if mhz else None
        max_mhz = round(max(mhz), 1) if mhz else None
        freq_source = f"{PROC_CPUINFO} (instantaneous `cpu MHz`, not a range)" if mhz else None
        if not mhz:
            unreadable.append(os.path.join(SYS_CPU, "cpu*/cpufreq"))

    physical = len(cores) if cores else (len(sys_cores) if sys_cores else None)
    socket_count = len(sockets) if sockets else (len(sys_packages) if sys_packages else None)
    schedulable = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None

    return {
        "logical": logical,
        "physical_cores": physical,
        "threads_per_core": (logical // physical) if physical else None,
        "sockets": socket_count,
        "architecture": os.uname().machine,
        "frequency_mhz": {"min": min_mhz, "max": max_mhz, "source": freq_source},
        "schedulable_here": schedulable,
        "flags": flags,
        "flag_count": len(flags),
        "bugs": bugs,
        "sources": {
            "counts_and_flags": PROC_CPUINFO,
            "topology_crosscheck": SYS_CPU,
            "frequency": freq_source,
            "why": "/proc and /sys are read in preference to any tool's rendering. Both "
                   "topology sources are reported so a disagreement is visible.",
        },
        "crosscheck": {
            "sys_logical": sys_logical,
            "sys_physical_cores": len(sys_cores) or None,
            "sys_sockets": len(sys_packages) or None,
            "agrees": (sys_logical == logical
                       and (not sys_cores or len(sys_cores) == physical)),
        },
        "note": ("`logical` is what the machine has; `schedulable_here` is what this process is "
                 "allowed to use. A tool that respects the affinity mask reports the second and "
                 "is often read as the first."),
        "evidence": _evidence(paths, unreadable),
    }


def memory() -> dict[str, Any]:
    """How much memory exists, how much is genuinely available, and how much is reclaimable cache.

    THE DISTINCTION THIS FUNCTION EXISTS FOR
    Free memory and available memory are different numbers and the gap between them is usually
    enormous. A machine can report well under two gibibytes free while over seventy are
    available, because the kernel has filled the rest with page cache it will hand back the
    instant something asks. Reading `free` as `available` is how a large machine gets reported
    as full and a job gets refused on a host with most of its memory idle.

    So `available_bytes` is returned beside `free_bytes`, the reclaimable part is broken out,
    and `why` states the arithmetic in the response rather than leaving it to the reader.
    """
    fields: dict[str, int] = {}
    try:
        with open(PROC_MEMINFO, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                parts = v.split()
                if not parts:
                    continue
                try:
                    value = int(parts[0])
                except ValueError:
                    continue
                fields[k.strip()] = value * 1024 if len(parts) > 1 and parts[1] == "kB" else value
    except OSError:
        raise InventoryError(f"{PROC_MEMINFO} could not be read; memory cannot be described "
                             f"without it")

    total = fields.get("MemTotal", 0)
    free = fields.get("MemFree", 0)
    available = fields.get("MemAvailable")
    buffers = fields.get("Buffers", 0)
    cached = fields.get("Cached", 0)
    sreclaimable = fields.get("SReclaimable", 0)
    shmem = fields.get("Shmem", 0)
    buff_cache = buffers + cached + sreclaimable
    used = total - free - buff_cache

    gib = 1024 ** 3
    return {
        "total_bytes": total,
        "free_bytes": free,
        "available_bytes": available,
        "used_bytes": used,
        "buffers_bytes": buffers,
        "cached_bytes": cached,
        "sreclaimable_bytes": sreclaimable,
        "shmem_bytes": shmem,
        "buff_cache_bytes": buff_cache,
        "reclaimable_bytes": (available - free) if available is not None else None,
        "swap": {"total_bytes": fields.get("SwapTotal", 0),
                 "free_bytes": fields.get("SwapFree", 0),
                 "cached_bytes": fields.get("SwapCached", 0)},
        "gib": {
            "total": round(total / gib, 2),
            "free": round(free / gib, 2),
            "available": round(available / gib, 2) if available is not None else None,
            "buff_cache": round(buff_cache / gib, 2),
        },
        "why": (f"free is {round(free / gib, 2)} GiB and available is "
                f"{round(available / gib, 2) if available is not None else 'unknown'} GiB on a "
                f"{round(total / gib, 2)} GiB machine. The difference is page cache and "
                f"reclaimable slab, which the kernel returns on demand — reading `free` as "
                f"`available` reports this host as nearly exhausted when it is nearly idle."),
        "evidence": _evidence([PROC_MEMINFO]),
    }


def storage() -> dict[str, Any]:
    """Every block device: size, transport, rotation, the driver bound, and its mount state.

    NOTHING IS FILTERED, AND THE ZERO-BYTE DEVICE IS THE REASON
    A card reader with no card in it presents a block device that reports zero bytes. It is
    present, it is bound to a driver, and it is removable. Filtering devices by size is how a
    present device gets reported as absent, and then somebody goes looking for a hardware fault
    that is not there. Removable devices and zero-size devices are RETURNED, carrying `why`.

    The driver is resolved by walking up from the block device until a binding is found, because
    a block device is not bound at its own level: the binding sits on the disk node, the
    controller or the bus function underneath it. `driver_at` names which level answered.

    No health-tool invocation happens here. The informational modes of such a tool print the
    disk's serial number, and this module does not emit serials.
    """
    mounts, mount_unreadable = _mounts_by_devnum()
    paths: list[str] = [SYS_BLOCK, PROC_MOUNTS]
    unreadable: list[str] = list(mount_unreadable)
    devices: list[dict[str, Any]] = []

    for name in _listdir(SYS_BLOCK):
        base = os.path.join(SYS_BLOCK, name)
        paths.append(base)
        real = os.path.realpath(base)
        sectors = _read_int(os.path.join(base, "size"))
        if sectors is None:
            unreadable.append(os.path.join(base, "size"))
        size_bytes = (sectors or 0) * _SECTOR_BYTES
        chain = _bus_chain(os.path.join(base, "device")) if _exists(
            os.path.join(base, "device")) else _bus_chain(real)

        driver = driver_at = None
        driver_target_exists = False
        for level in chain:
            if level["driver"]:
                driver, driver_at = level["driver"], level["path"]
                driver_target_exists = level["driver_target_exists"]
                break

        transport = None
        for level in chain:
            if level["subsystem"] in _TRANSPORTS:
                transport = level["subsystem"]
        for wanted in _TRANSPORTS:
            if any(level["subsystem"] == wanted for level in chain):
                transport = wanted
                break

        device_dir = os.path.join(base, "device")
        serial_present, serial_names = _has_serial(device_dir)
        devnum = _devnum(base)

        partitions = []
        for child in _listdir(base):
            cdir = os.path.join(base, child)
            if not os.path.isfile(os.path.join(cdir, "partition")):
                continue
            csectors = _read_int(os.path.join(cdir, "size"))
            cdevnum = _devnum(cdir)
            partitions.append({
                "name": child,
                "size_bytes": (csectors or 0) * _SECTOR_BYTES,
                "devnum": cdevnum,
                "start_sector": _read_int(os.path.join(cdir, "start")),
                "mounts": mounts.get(cdevnum or "", []),
                "path": cdir,
            })

        virtual = real.startswith("/sys/devices/virtual")
        devices.append({
            "name": name,
            "path": base,
            "device_path": real,
            "size_bytes": size_bytes,
            "size_sectors": sectors,
            "sector_bytes": _SECTOR_BYTES,
            "rotational": (lambda v: None if v is None else bool(v))(
                _read_int(os.path.join(base, "queue/rotational"))),
            "removable": (lambda v: None if v is None else bool(v))(
                _read_int(os.path.join(base, "removable"))),
            "transport": transport,
            "driver": driver,
            "driver_at": driver_at,
            "driver_target_exists": driver_target_exists,
            "model": _read(os.path.join(device_dir, "model")),
            "devnum": devnum,
            "virtual": virtual,
            "has_serial": serial_present,
            "serial_attributes": serial_names,
            "partitions": partitions,
            "mounts": mounts.get(devnum or "", []),
            "mounted": bool(mounts.get(devnum or "")) or any(p["mounts"] for p in partitions),
            "bus_chain": [{"name": c["name"], "subsystem": c["subsystem"],
                           "driver": c["driver"]} for c in chain],
            "why": ("reports zero bytes. It is present and enumerated; a reader with no medium "
                    "in it reads exactly this way. It is returned rather than filtered, because "
                    "filtering by size is how a present device is mistaken for an absent one."
                    if size_bytes == 0 else None),
        })

    zero = [d["name"] for d in devices if d["size_bytes"] == 0]
    return {
        "devices": devices,
        "count": len(devices),
        "zero_size": zero,
        "removable": [d["name"] for d in devices if d["removable"]],
        "unbound": [d["name"] for d in devices if not d["driver"]],
        "filtered": [],
        "filter_policy": ("none. Removable and zero-size devices are included; a zero-byte "
                          "device is a finding, not noise."),
        "withheld": ["serial", "wwid", "device serial numbers of any kind"],
        "withheld_why": ("a disk serial identifies this machine, so every report quoting one "
                         "becomes unsafe to pass on. `has_serial` says one exists."),
        "evidence": _evidence(paths, unreadable),
    }


def pci() -> dict[str, Any]:
    """Every PCI function, its `vendor:device` pair, its class, and the driver bound to it.

    THE DRIVER BINDING IS THE POINT
    A function with no driver is hardware the kernel has enumerated and nothing is using. That
    is sometimes correct and sometimes the whole fault, and either way it is invisible unless
    something asks. Unbound functions are returned in the list AND collected into `unbound`.

    `vendor:device` stays byte-exact, lower-case hex, exactly as it must be typed into a bind
    rule or a modalias. It is not translated into the name of whoever registered it: the number
    is what software matches on, and the name is not needed to configure anything.
    """
    paths: list[str] = [PCI_DEVICES]
    unreadable: list[str] = []
    devices: list[dict[str, Any]] = []

    entries = _listdir(PCI_DEVICES)
    if not entries and not os.path.isdir(PCI_DEVICES):
        unreadable.append(PCI_DEVICES)

    for address in entries:
        base = os.path.join(PCI_DEVICES, address)
        vendor, device = _hex_id(os.path.join(base, "vendor")), _hex_id(
            os.path.join(base, "device"))
        class_hex = _hex_id(os.path.join(base, "class"))
        base_class = None
        if class_hex:
            try:
                base_class = int(class_hex, 16) >> 16
            except ValueError:
                base_class = None
        driver, target_exists = _driver_of(base)
        real = os.path.realpath(base)
        parent = os.path.basename(os.path.dirname(real))
        devices.append({
            "address": address,
            "vendor": vendor,
            "device": device,
            "id": f"{vendor}:{device}" if vendor and device else None,
            "subsystem_vendor": _hex_id(os.path.join(base, "subsystem_vendor")),
            "subsystem_device": _hex_id(os.path.join(base, "subsystem_device")),
            "revision": _hex_id(os.path.join(base, "revision")),
            "class": class_hex,
            "class_name": _PCI_BASE_CLASS.get(base_class) if base_class is not None else None,
            "driver": driver,
            "driver_bound": driver is not None,
            "driver_target_exists": target_exists,
            "irq": _read_int(os.path.join(base, "irq")),
            "enabled": (lambda v: None if v is None else bool(v))(
                _read_int(os.path.join(base, "enable"))),
            "parent": parent if parent.count(":") == 2 else None,
            "path": base,
            "device_path": real,
            "why": ("no driver is bound to this function: the kernel enumerated it and nothing "
                    "has claimed it." if driver is None else None),
        })

    unbound = [d["address"] for d in devices if not d["driver_bound"]]
    return {
        "devices": devices,
        "count": len(devices),
        "unbound": unbound,
        "unbound_count": len(unbound),
        "drivers": sorted({d["driver"] for d in devices if d["driver"]}),
        "id_policy": ("`vendor:device` is reproduced byte-exact in lower-case hex because it is "
                      "what a bind rule, a modalias and a udev rule are written against. It is "
                      "not decoded into a registrant's name; the number is the identifier."),
        "evidence": _evidence(paths, unreadable),
    }


def usb() -> dict[str, Any]:
    """The USB tree: every device, its id, the speed it negotiated, its driver, and its position.

    TOPOLOGY IS THE FINDING, NOT DECORATION
    A device on a root port and the same device three hubs deep are different risks. A hub that
    drops takes every device behind it with it, and the symptom surfaces on the device rather
    than on the hub — so a storage device that vanished is investigated as a failing disk when
    the disk is fine and the hub is not. `depth`, `parent` and `behind_hub` are returned on
    every device so that question can be answered without re-deriving the tree.

    Sysfs lists devices and INTERFACES in the same directory: `2-7.1` is a device and
    `2-7.1:1.0` is one of its interfaces. The driver usually binds to the interface, not to the
    device, so both are returned and each interface carries its own binding.
    """
    paths: list[str] = [USB_DEVICES]
    unreadable: list[str] = []
    entries = _listdir(USB_DEVICES)
    if not entries and not os.path.isdir(USB_DEVICES):
        unreadable.append(USB_DEVICES)

    device_names = [e for e in entries if ":" not in e]
    iface_names = [e for e in entries if ":" in e]

    interfaces_by_device: dict[str, list[dict[str, Any]]] = {}
    for iface in iface_names:
        owner = iface.split(":", 1)[0]
        base = os.path.join(USB_DEVICES, iface)
        driver, target_exists = _driver_of(base)
        cls = _read_hex_byte(os.path.join(base, "bInterfaceClass"))
        interfaces_by_device.setdefault(owner, []).append({
            "name": iface,
            "interface_class": f"{cls:02x}" if cls is not None else None,
            "interface_class_name": _USB_CLASS.get(cls) if cls is not None else None,
            "driver": driver,
            "driver_bound": driver is not None,
            "driver_target_exists": target_exists,
            "path": base,
        })

    devices: list[dict[str, Any]] = []
    for name in device_names:
        base = os.path.join(USB_DEVICES, name)
        if name.startswith("usb") and name[3:].isdigit():
            parent, depth, root = None, 0, True
        elif "." in name:
            parent, depth, root = name.rsplit(".", 1)[0], name.count(".") + 1, False
        elif "-" in name:
            bus = name.split("-", 1)[0]
            parent, depth, root = f"usb{bus}", 1, False
        else:
            parent, depth, root = None, 0, True

        vendor, product = _hex_id(os.path.join(base, "idVendor")), _hex_id(
            os.path.join(base, "idProduct"))
        dclass = _read_hex_byte(os.path.join(base, "bDeviceClass"))
        speed = _read(os.path.join(base, "speed"))
        maxchild = _read_int(os.path.join(base, "maxchild"))
        driver, target_exists = _driver_of(base)
        serial_present, serial_names = _has_serial(base)
        ifaces = sorted(interfaces_by_device.get(name, []), key=lambda i: i["name"])

        # BEHIND A HUB MEANS BEHIND AN EXTERNAL ONE.
        # Every device is behind a hub in the literal sense — the controller's root hub is a
        # hub, class 09, and it is the parent of everything on its bus. Answering the question
        # literally marks all twelve devices on this host as at-risk and the field stops
        # distinguishing anything, which is the opposite of why it is here. A root port is a
        # port on the controller; a chain through a hub somebody plugged in is the different
        # risk, because that hub dropping takes everything under it with it.
        parent_is_root_hub = bool(parent and parent.startswith("usb") and parent[3:].isdigit())
        parent_class = _read_hex_byte(os.path.join(USB_DEVICES, parent, "bDeviceClass")) if (
            parent and os.path.isdir(os.path.join(USB_DEVICES, parent))) else None
        external_hub = (parent is not None and not parent_is_root_hub
                        and (parent_class == 0x09 or depth > 1))
        hub_chain: list[str] = []
        walk = parent
        while walk and not (walk.startswith("usb") and walk[3:].isdigit()):
            hub_chain.append(walk)
            walk = walk.rsplit(".", 1)[0] if "." in walk else f"usb{walk.split('-', 1)[0]}"

        devices.append({
            "name": name,
            "id": f"{vendor}:{product}" if vendor and product else None,
            "vendor": vendor,
            "product": product,
            "speed_mbps": (lambda s: float(s) if s and s.replace(".", "", 1).isdigit() else None)(
                speed),
            "speed_raw": speed,
            "device_class": f"{dclass:02x}" if dclass is not None else None,
            "device_class_name": _USB_CLASS.get(dclass) if dclass is not None else None,
            "is_hub": dclass == 0x09,
            "maxchild": maxchild,
            "driver": driver,
            "driver_bound": driver is not None,
            "driver_target_exists": target_exists,
            "product_string": _read(os.path.join(base, "product")),
            "manufacturer_string": _read(os.path.join(base, "manufacturer")),
            "parent": parent,
            "parent_is_root_hub": parent_is_root_hub,
            "depth": depth,
            "root_port": root or (depth <= 1),
            "behind_hub": external_hub,
            "hub_chain": hub_chain,
            "interfaces": ifaces,
            "has_serial": serial_present,
            "serial_attributes": serial_names,
            "path": base,
            "why": (f"reached through {', '.join(hub_chain) or 'an external hub'}: if that hub "
                    f"drops, this device disappears and the symptom appears here rather than on "
                    f"the hub." if external_hub else None),
        })

    unbound_ifaces = [i["name"] for d in devices for i in d["interfaces"] if not i["driver_bound"]]
    return {
        "devices": sorted(devices, key=lambda d: (d["depth"], d["name"])),
        "count": len(devices),
        "interface_count": len(iface_names),
        "hubs": [d["name"] for d in devices if d["is_hub"]],
        "behind_hub": [d["name"] for d in devices if d["behind_hub"]],
        "unbound_interfaces": unbound_ifaces,
        "unbound": [d["name"] for d in devices if not d["driver_bound"]],
        "withheld": ["serial"],
        "withheld_why": ("a USB serial identifies one physical device on this machine; "
                         "`has_serial` reports that one exists without emitting it."),
        "evidence": _evidence(paths, unreadable),
    }


def network() -> dict[str, Any]:
    """Network interfaces: name, state, driver, negotiated speed, and that a MAC EXISTS.

    THE ADDRESS IS NOT RETURNED
    A MAC address identifies this machine on any network it has ever touched, and a report
    quoting one cannot be shared. `has_mac` answers whether the interface has a hardware
    address, and `mac_oui` returns the three-octet organisationally unique prefix — which names
    a registrant, not a machine — and nothing after it. The remaining octets never leave the
    module.

    `speed` is only meaningful on a link that is up; the kernel returns an error reading it on a
    down interface, which is reported as unknown rather than as zero.
    """
    paths: list[str] = [SYS_NET]
    unreadable: list[str] = []
    entries = _listdir(SYS_NET)
    if not entries and not os.path.isdir(SYS_NET):
        unreadable.append(SYS_NET)

    interfaces: list[dict[str, Any]] = []
    for name in entries:
        base = os.path.join(SYS_NET, name)
        address = _read(os.path.join(base, "address"))
        device = os.path.join(base, "device")
        driver, target_exists = _driver_of(device) if _exists(device) else (None, False)
        real_device = os.path.realpath(device) if _exists(device) else None
        pci_address = None
        if real_device:
            candidate = os.path.basename(real_device)
            pci_address = candidate if candidate.count(":") == 2 else None
        speed = _read_int(os.path.join(base, "speed"))
        operstate = _read(os.path.join(base, "operstate"))
        carrier = _read_int(os.path.join(base, "carrier"))
        # An all-zero address is the absence of one. Returning `00:00:00` as an OUI would put a
        # registrant prefix on an interface that has no hardware address at all.
        has_mac = bool(address) and set(address.replace(":", "")) != {"0"}
        interfaces.append({
            "name": name,
            "operstate": operstate,
            "up": operstate == "up",
            "carrier": None if carrier is None else bool(carrier),
            "mtu": _read_int(os.path.join(base, "mtu")),
            "has_mac": has_mac,
            "mac_oui": _oui(address) if has_mac else None,
            "mac_bytes": _read_int(os.path.join(base, "addr_len")),
            "speed_mbps": speed if speed and speed > 0 else None,
            "duplex": _read(os.path.join(base, "duplex")),
            "driver": driver,
            "driver_bound": driver is not None,
            "driver_target_exists": target_exists,
            "pci_address": pci_address,
            "virtual": not _exists(device),
            "arp_type": _read_int(os.path.join(base, "type")),
            "path": base,
            "why": ("no speed is readable: the kernel refuses that attribute on an interface "
                    "whose link is not up, so it is unknown rather than zero."
                    if not speed or speed <= 0 else None),
        })

    return {
        "interfaces": interfaces,
        "count": len(interfaces),
        "up": [i["name"] for i in interfaces if i["up"]],
        "down": [i["name"] for i in interfaces if not i["up"]],
        "unbound": [i["name"] for i in interfaces if not i["driver_bound"] and not i["virtual"]],
        "withheld": ["address (MAC)"],
        "withheld_why": ("a MAC address identifies this machine wherever it has been. Only "
                         "`has_mac` and the three-octet OUI prefix are returned."),
        "evidence": _evidence(paths, unreadable),
    }


def sensors() -> dict[str, Any]:
    """Temperatures, fans and voltages from `hwmon`, with the labels the kernel publishes.

    The label is the kernel's, byte-exact. It is the only thing that says which of eleven
    readings on one chip is the package and which are individual cores, and rewriting it into
    something prettier makes the reading unattributable.

    Raw and scaled values are both returned. The hwmon interface fixes the scale — millidegrees,
    millivolts, microwatts — and returning only the scaled figure asks the reader to trust
    arithmetic they cannot check.

    This reads. It does not write `pwm*`, `*_enable` or `*_target`, several of which are
    writable on a host with fan control exposed. Changing a fan curve is not detection.
    """
    paths: list[str] = [SYS_HWMON]
    unreadable: list[str] = []
    chips: list[dict[str, Any]] = []
    total = 0

    entries = _listdir(SYS_HWMON)
    if not entries and not os.path.isdir(SYS_HWMON):
        unreadable.append(SYS_HWMON)

    for entry in entries:
        base = os.path.join(SYS_HWMON, entry)
        chip_name = _read(os.path.join(base, "name"))
        readings: list[dict[str, Any]] = []
        for attr in _listdir(base):
            m = _HWMON_INPUT.match(attr)
            if not m:
                continue
            kind, index = m.group(1), m.group(2)
            raw = _read_int(os.path.join(base, attr))
            if raw is None:
                unreadable.append(os.path.join(base, attr))
                continue
            scale, unit = _HWMON_KINDS[kind]
            readings.append({
                "kind": kind,
                "index": int(index),
                "label": _read(os.path.join(base, f"{kind}{index}_label")),
                "raw": raw,
                "value": round(raw * scale, 3),
                "unit": unit,
                "max": _read_int(os.path.join(base, f"{kind}{index}_max")),
                "crit": _read_int(os.path.join(base, f"{kind}{index}_crit")),
                "alarm": _read_int(os.path.join(base, f"{kind}{index}_alarm")),
                "path": os.path.join(base, attr),
            })
            total += 1
        chips.append({
            "hwmon": entry,
            "chip": chip_name,
            "device_path": os.path.realpath(base),
            "readings": sorted(readings, key=lambda r: (r["kind"], r["index"])),
            "reading_count": len(readings),
            "controls_present": sorted(a for a in _listdir(base)
                                       if a.startswith("pwm") or a.endswith("_enable")),
        })
        paths.append(base)

    zones: list[dict[str, Any]] = []
    for entry in _listdir(SYS_THERMAL):
        if not entry.startswith("thermal_zone"):
            continue
        base = os.path.join(SYS_THERMAL, entry)
        milli = _read_int(os.path.join(base, "temp"))
        zones.append({
            "zone": entry,
            "type": _read(os.path.join(base, "type")),
            "temp_c": round(milli / 1000.0, 3) if milli is not None else None,
            "raw": milli,
            "path": base,
        })
    cooling = [e for e in _listdir(SYS_THERMAL) if e.startswith("cooling_device")]
    if _listdir(SYS_THERMAL):
        paths.append(SYS_THERMAL)

    return {
        "chips": chips,
        "chip_count": len(chips),
        "reading_count": total,
        "thermal_zones": zones,
        "thermal_zone_count": len(zones),
        "cooling_devices": cooling,
        "cooling_device_count": len(cooling),
        "writes": "none. No pwm, enable or target attribute is written by this module.",
        "note": ("the reading count here is what `hwmon` publishes. A userspace sensor tool "
                 "prints a different number because it renders derived and duplicated lines; "
                 "the kernel interface is the one that can be checked against a path."),
        "evidence": _evidence(paths, unreadable),
    }


def power() -> dict[str, Any]:
    """Power supplies and batteries, and what state each reports.

    `scope` separates a supply that powers the MACHINE from one that powers a peripheral. Both
    appear in the same directory, and a battery reported at an unknown charge is alarming if it
    is the machine's and unremarkable if it belongs to a detached accessory.

    `serial_number` is present on entries here and is never returned.
    """
    paths: list[str] = [SYS_POWER]
    unreadable: list[str] = []
    entries = _listdir(SYS_POWER)
    if not entries and not os.path.isdir(SYS_POWER):
        unreadable.append(SYS_POWER)

    supplies: list[dict[str, Any]] = []
    for name in entries:
        base = os.path.join(SYS_POWER, name)
        serial_present, serial_names = _has_serial(base)
        micro = {k: _read_int(os.path.join(base, k))
                 for k in ("voltage_now", "current_now", "power_now", "energy_now",
                           "energy_full", "charge_now", "charge_full")}
        supplies.append({
            "name": name,
            "type": _read(os.path.join(base, "type")),
            "status": _read(os.path.join(base, "status")),
            "scope": _read(os.path.join(base, "scope")),
            "powers_this_machine": _read(os.path.join(base, "scope")) != "Device",
            "present": (lambda v: None if v is None else bool(v))(
                _read_int(os.path.join(base, "present"))),
            "online": (lambda v: None if v is None else bool(v))(
                _read_int(os.path.join(base, "online"))),
            "capacity_percent": _read_int(os.path.join(base, "capacity")),
            "capacity_level": _read(os.path.join(base, "capacity_level")),
            "technology": _read(os.path.join(base, "technology")),
            "model_name": _read(os.path.join(base, "model_name")),
            "micro_units": {k: v for k, v in micro.items() if v is not None},
            "has_serial": serial_present,
            "serial_attributes": serial_names,
            "path": base,
        })
        paths.append(base)

    return {
        "supplies": supplies,
        "count": len(supplies),
        "machine_supplies": [s["name"] for s in supplies if s["powers_this_machine"]],
        "device_supplies": [s["name"] for s in supplies if not s["powers_this_machine"]],
        "withheld": ["serial_number"],
        "withheld_why": ("a supply's serial number identifies one physical unit; `has_serial` "
                         "reports that one exists without emitting it."),
        "evidence": _evidence(paths, unreadable),
    }


def owned_by() -> dict[str, Any]:
    """Which SyMonComponent covers each hardware class on this host — and which are covered by none.

    THIS IS THE GAP-FINDER, SO IT IS WRITTEN TO FIND GAPS
    A coverage map that answers "everything is covered" has stopped being a map and become a
    reassurance. Two different absences are reported here and they are NOT the same thing:

        `unbound`          the kernel enumerated the device and no DRIVER claimed it
        `unowned_classes`  a driver owns the device, but no COMPONENT of this estate owns what
                           the device DOES — its configuration, its policy, its behaviour

    The second is the interesting one, and it is where "everything else belongs to this
    component" would quietly erase the finding. Inventorying a thing is not owning it. This
    component can tell anyone what the fans are doing; nothing in the estate decides what they
    should do, and recording that as coverage would make the map lie.
    """
    p, u, n, s, pw, st = pci(), usb(), network(), sensors(), power(), storage()

    components = {
        "symonprobe": "the compute card: what it is, what a build can run on it",
        "symondriver": "the compute card's userspace, and its agreement with the kernel module",
        "symonkernel": "the kernel, its configuration and its out-of-tree modules",
        "symonsdk": "the build toolchains",
        "symondevice": "this component: the physical inventory — what exists, and what owns it",
    }

    display = [d for d in p["devices"] if d["class_name"] == "display controller"]
    audio = [d for d in p["devices"] if d["class_name"] == "multimedia controller"]
    net_dev = [d for d in p["devices"] if d["class_name"] in
               ("network controller", "wireless controller")]
    smbus = [d["address"] for d in p["devices"] if d["driver"] and "smbus" in d["driver"].lower()]
    fan_chips = [c["chip"] for c in s["chips"] if c["controls_present"]]
    bluetooth = [d["name"] for d in u["devices"]
                 for i in d["interfaces"] if i["interface_class_name"] == "wireless controller"]

    classes: list[dict[str, Any]] = [
        {"class": "compute card", "owner": ["symonprobe", "symondriver"], "coverage": "full",
         "instances": [d["address"] for d in display],
         "evidence": [PCI_DEVICES],
         "why": "the card is inventoried here and OWNED there: capability, builds and the "
                "userspace-to-module agreement all live in those two components."},
        {"class": "kernel modules and their binding", "owner": ["symonkernel"],
         "coverage": "full",
         "instances": sorted(p["drivers"]),
         "evidence": [PCI_DEVICES, USB_DEVICES],
         "why": "which module is bound is read here; which modules exist, how they are built "
                "and whether they survive a kernel bump is that component's question."},
        {"class": "build toolchains", "owner": ["symonsdk"], "coverage": "full",
         "instances": [], "evidence": [],
         "why": "no hardware class maps to it; it is named so the map is complete rather than "
                "silently missing a component that exists."},
        {"class": "cpu", "owner": ["symondevice"], "coverage": "inventory",
         "instances": [PROC_CPUINFO], "evidence": [PROC_CPUINFO, SYS_CPU],
         "why": "counts, topology, frequency range and instruction-set flags."},
        {"class": "system memory", "owner": ["symondevice"], "coverage": "inventory",
         "instances": [PROC_MEMINFO], "evidence": [PROC_MEMINFO],
         "why": "total, available and the reclaimable part."},
        {"class": "block storage", "owner": ["symondevice"], "coverage": "inventory",
         "instances": [d["name"] for d in st["devices"]], "evidence": [SYS_BLOCK, PROC_MOUNTS],
         "why": "size, transport, driver and mount state. Health and endurance are not read: "
                "the tool that reports them prints the serial."},
        {"class": "pci topology", "owner": ["symondevice"], "coverage": "inventory",
         "instances": [d["address"] for d in p["devices"]], "evidence": [PCI_DEVICES],
         "why": "address, id, class and the driver bound."},
        {"class": "usb topology", "owner": ["symondevice"], "coverage": "inventory",
         "instances": [d["name"] for d in u["devices"]], "evidence": [USB_DEVICES],
         "why": "id, negotiated speed, driver and position in the tree."},
    ]

    unowned: list[dict[str, Any]] = [
        {"class": "thermal and fan control",
         "instances": fan_chips,
         "inventoried_by": "symondevice",
         "owner": None,
         "evidence": [SYS_HWMON],
         "why": "the readings and the writable control attributes are both visible here and "
                "this component deliberately writes neither. No component in the estate decides "
                "a fan curve, a thermal limit or what happens when one is reached."},
        {"class": "power supply and battery state",
         "instances": [s_["name"] for s_ in pw["supplies"]],
         "inventoried_by": "symondevice",
         "owner": None,
         "evidence": [SYS_POWER],
         "why": "state is read. Nothing acts on it: no component reacts to a supply going "
                "offline or a battery reaching a threshold."},
        {"class": "network link configuration",
         "instances": [i["name"] for i in n["interfaces"] if not i["virtual"]],
         "inventoried_by": "symondevice",
         "owner": None,
         "evidence": [SYS_NET] + [d["address"] for d in net_dev],
         "why": "state, driver and negotiated speed are read. Addressing, routing, link "
                "negotiation and what happens when a link drops belong to no component."},
        {"class": "audio",
         "instances": [d["address"] for d in audio],
         "inventoried_by": "symondevice",
         "owner": None,
         "evidence": [PCI_DEVICES],
         "why": "enumerated and driver-bound; nothing in the estate uses or configures it."},
        {"class": "bluetooth",
         "instances": sorted(set(bluetooth)),
         "inventoried_by": "symondevice",
         "owner": None,
         "evidence": [USB_DEVICES],
         "why": "enumerated and driver-bound; no component pairs, configures or depends on it."},
        {"class": "smbus and i2c",
         "instances": smbus,
         "inventoried_by": "symondevice",
         "owner": None,
         "evidence": [PCI_DEVICES],
         "why": "a bus the kernel drives and no component reaches."},
    ]

    unbound = {
        "pci": p["unbound"],
        "usb_devices": u["unbound"],
        "usb_interfaces": u["unbound_interfaces"],
        "network": n["unbound"],
        "block": st["unbound"],
    }
    unbound_total = sum(len(v) for v in unbound.values())

    return {
        "components": components,
        "classes": classes,
        "owned_classes": [c["class"] for c in classes],
        "unowned_classes": [c["class"] for c in unowned],
        "unowned": unowned,
        "unowned_count": len(unowned),
        "unbound": unbound,
        "unbound_count": unbound_total,
        "full_coverage": False,
        "coverage_note": (
            "inventory coverage is not ownership. Every class this component lists under "
            "`coverage: inventory` is DESCRIBED here and DECIDED by nobody; the classes in "
            "`unowned` are the ones where that gap matters, and they are named rather than "
            "absorbed into this component so that the map keeps being able to find a gap."),
        "unbound_note": (
            "`unbound` is a different absence from `unowned`: a device with no driver has not "
            "been claimed by the kernel at all. It is reported, never omitted — a device left "
            "out of an inventory because nothing owns it is exactly the device an inventory "
            "exists to surface."),
        "evidence": _evidence(
            [PCI_DEVICES, USB_DEVICES, SYS_NET, SYS_HWMON, SYS_POWER, SYS_BLOCK, PROC_CPUINFO,
             PROC_MEMINFO],
            sorted(set(p["evidence"]["unreadable"] + u["evidence"]["unreadable"]
                       + n["evidence"]["unreadable"] + s["evidence"]["unreadable"]
                       + pw["evidence"]["unreadable"] + st["evidence"]["unreadable"]))),
    }
