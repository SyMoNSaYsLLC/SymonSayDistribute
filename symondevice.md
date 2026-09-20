# symondevice

What hardware exists, which driver owns it, which kernel interface exposes it, and which
SyMonComponent covers it.

This page describes what is **on disk and exercised**: 43 tests pass against this host's real
hardware, the unit was run on `127.0.0.1:8832` and answered, and every figure quoted below was
measured on this host on 2026-09-19 rather than recalled. Where a figure came from a tool rather
than from `/proc` or `/sys`, it is labelled as such — that difference is itself one of the
findings below.

## The gap this fills

Four components already cover a slice of the machine:

| Component | Covers |
|---|---|
| `symonprobe` | the compute card: what it is, what a build can run on it |
| `symondriver` | that card's userspace, and its agreement with the loaded kernel module |
| `symonkernel` | the kernel, its configuration and its out-of-tree modules |
| `symonsdk` | the build toolchains |

The CPU, system memory, every block device, the entire PCI and USB topology, the network
interfaces, the sensors and the power supplies were covered by **nothing**. Every question about
any of them was answered by a person running a tool and reading its output, which is a method
with no evidence attached and no way to be wrong out loud.

## `owned_by` is the route that makes this a framework component

The other eight routes describe hardware. That one describes the **estate**: it maps each
hardware class to the component that covers it, and **names the classes covered by nothing**.

Measured on this host, it reports six unowned classes:

    thermal and fan control          the readings and the writable controls are both visible;
                                     nothing decides a fan curve or what happens at a limit
    power supply and battery state   state is read; nothing acts on it
    network link configuration       state, driver and negotiated speed are read; addressing,
                                     routing and link recovery belong to no component
    audio                            enumerated and driver-bound; nothing uses it
    bluetooth                        enumerated and driver-bound; nothing depends on it
    smbus and i2c                    a bus the kernel drives and no component reaches

and five unbound devices — four PCI functions and one USB interface that the kernel enumerated
and no driver claimed.

**Two different absences, deliberately not merged.** `unbound` means no *driver* claimed the
device. `unowned` means a driver owns it but no *component* owns what it does. Collapsing them
would let "everything else belongs to symondevice" absorb the second, and the map would then
report full coverage of a machine nothing configures. `full_coverage` is returned as `false` and
a test asserts it, because a gap-finder that never finds a gap has become a reassurance.

## Every answer carries its evidence

Each function returns an `evidence` block: the paths read, which of them were unreadable, and
`rc` — `0` when every path named was read, `1` when one was not.

`rc` is **this module's own**, not a process exit status. Nothing here runs a program, so there
is no child exit code, and quoting one would be an invention. `command` and `argv` are returned
as `null` on every response and a test asserts it.

On this host `sensors` returns `rc: 1`, naming `/sys/class/hwmon/hwmon4/temp1_input` — the
wireless chip's thermal sensor errors while its radio is down. That is the evidence block doing
its job rather than a defect: of 24 readings attempted, **23 are returned** and the one that was
not is named. A module that returned 23 silently would be indistinguishable from a host with 23
sensors.

## Nothing here runs a program, and that is a design decision

There is no `subprocess` import in the capability module and no path to a shell. Three
consequences worth stating:

- **A tool's human output is a rendering.** Renderings drift between versions; `/proc` and
  `/sys` are the interface the tool itself reads.
- **Some tools answer a different question.** On this host `nproc` reports **8** while
  `/proc/cpuinfo` lists **20**, because `nproc` respects the caller's CPU affinity mask. Both
  are right. Only one answers "how big is this machine". `cpu()` returns both, as `logical` and
  `schedulable_here`, and a test asserts they are not collapsed.
- **The informational modes of a disk health tool print the serial.** Not invoking it is
  simpler than filtering it.

## No MAC address and no serial number leaves this component

A MAC address and a device serial identify **this machine**, and any report quoting one becomes
unsafe to pass on — which makes every downstream report unsafe too.

| Returned | Never returned |
|---|---|
| `has_mac`, and `mac_oui` — three octets, which name a registrant and not a machine | the hardware address |
| `model`, `size_bytes`, and `has_serial` with the attribute names that hold it | any serial, wwid, eui or nguid value |
| a supply's `model_name` and state | `serial_number` |

Everything withheld is named in a `withheld` list on the same response, because a filter nobody
can see is indistinguishable from a bug.

**The tests on this are built so they can fail.** The MAC test first proves its own pattern
matches a MAC-shaped string and does *not* match the three-octet prefix this component returns —
a pattern that matches nothing passes forever. The serial test reads the six real serial values
this host publishes and asserts those exact strings appear in no response; a serial has no shape,
so a pattern could never have found one. Neither test prints a value it reads.

## The §3.11 line this component draws

This component is a hardware inventory, so §3.11 is the hard part of it. The line runs between
**an identifier software is configured with** and **a name written for a person to read**.

**Kept byte-exact, because software is configured and run with them** — §3.11 class 3:

| Kind | Measured here |
|---|---|
| PCI `vendor:device` | `8086:9b33`, `10ec:3000` — lower-case hex, no `0x`, exactly as a bind rule or modalias is written |
| driver module names | `xhci_hcd`, `nvme`, `ahci`, `pcieport`, `r8169`, `iwlwifi`, `snd_hda_intel`, `i801_smbus`, `intel_pch_thermal`, `intel-lpss`, `skl_uncore`, `mei_me`, `nvidia`, `uas`, `usb-storage`, `usbhid`, `btusb`, `hub`, `sd` |
| sysfs and procfs paths | `/sys/bus/pci/devices`, `/sys/class/hwmon`, `/proc/meminfo` |
| interface names | `lo`, `enp3s0`, `wlp4s0` |
| `hwmon` chip names and kernel labels | `coretemp`, `acpitz`, `nvme`, `pch_cometlake`, `dell_smm`, `iwlwifi_1`; labels `Package id 0`, `Core 0`, `Composite`, `Processor Fan` |
| specification class codes and their generic words | `030000` / `display controller`, `09` / `hub` — the public specification's own categories, which name a function |

None of these is optional. A driver name that has been prettied up cannot be matched against
`/sys/bus/pci/drivers`, and an identifier that has been translated is no longer the identifier.

**Deliberately absent:**

- **No marketing model string in prose.** Where a device reports one — a disk, a USB peripheral,
  a battery — it is **data the kernel handed over**, and it is returned in a field
  (`model`, `product_string`, `manufacturer_string`, `model_name`) and never written into a
  sentence in this document, a docstring or a comment. No test asserts against one either: those
  strings are host-specific, so a test matching one would fail on any other machine as well as
  breaking the rule.
- **No vendor decoding.** `vendor:device` is returned as the number. It is not looked up in a
  vendor database and turned into a company name, which is precisely what `lspci` would have
  supplied for free had a tool been invoked. The number is what software matches on; the name is
  needed to configure nothing.
- **No brand in a docstring, a comment, a field name or a route.** The capability module and the
  service name hardware by capability and by kernel identifier throughout.

## Read only, and structurally so

No flashing, no repartitioning, no formatting, no boot or Secure Boot change, no driver
unload or reload, no PCI reset, no voltage, fan or clock change, no destructive SMART or NVMe
operation, no persistent network reconfiguration. Detection only.

This is enforced rather than promised: every `open()` in the capability module is checked by a
test for its mode, and `hwmon` control attributes are **listed** in `controls_present` and never
written — this host exposes `pwm1`–`pwm3` and `pwm1_enable`–`pwm3_enable`, all writable, all
untouched.

## Interfaces

**Serves** — FastAPI, ten routes under `/api/symondevice/`, one per capability plus `health`.
Bind from `SYM_DEVICE_HOST` (default `127.0.0.1`), port from `SYM_DEVICE_PORT` (default `8832`).

| Route | Answers |
|---|---|
| `GET /api/symondevice/health` | public; process alive, and which side of the bind it is on |
| `GET /api/symondevice/cpu` | counts, topology, frequency range, instruction-set flags |
| `GET /api/symondevice/memory` | total, available, and the reclaimable part |
| `GET /api/symondevice/storage` | every block device, including removable and zero-size |
| `GET /api/symondevice/pci` | every function, its id, its class, its driver or none |
| `GET /api/symondevice/usb` | the tree, with negotiated speed and position |
| `GET /api/symondevice/network` | interfaces, state, driver, speed — never the address |
| `GET /api/symondevice/sensors` | temperatures, fans and voltages with kernel labels |
| `GET /api/symondevice/power` | supplies and their state |
| `GET /api/symondevice/owned_by` | which component covers what, and what nothing covers |

**Reads** — `/proc/cpuinfo`, `/proc/meminfo`, `/proc/mounts`, `/sys/devices/system/cpu`,
`/sys/block`, `/sys/bus/pci/devices`, `/sys/bus/usb/devices`, `/sys/class/net`,
`/sys/class/hwmon`, `/sys/class/thermal`, `/sys/class/power_supply`. All read-only.

**Environment** — `SYM_DEVICE_HOST`, `SYM_DEVICE_PORT`, `SYM_DEVICE_TOKEN`.

**Authentication** — §3.2a. The **bind address decides**, at runtime, not a convention in prose.
On loopback there is no credential: a token there defends only against a caller who already has
code execution on this host, and such a caller can read the token. Off-loopback
`SYM_DEVICE_TOKEN` is required, and an **unset** one returns `503` rather than opening the unit —
a unit that becomes reachable through a configuration change must not become public through the
same change. `health` stays public on both sides so the unit can answer before it is configured.

**Consumed by** — nothing yet. This component is new; when something reads it, that consumer is
named here.

## Placement

Built from the Python standard library (PSF-2.0) and FastAPI (MIT). Both are permissive; neither
is copyleft, and nothing copyleft is linked, imported or invoked — no program is invoked at all.

Reading a device does not make this component a driver, a kernel module or anything derived from
one. `/proc` and `/sys` are the kernel's **stable userspace interface**, and reading a file the
kernel publishes creates no derivative of the kernel. Nothing here is compiled against a kernel
header, links a kernel symbol, or ships kernel code.

By §3.1b-i: the sources are named, their licences are permissive, and proprietary is the
default. This belongs on the `symondevice` branch of `SymonSayDistribute` under the SymonSaysLLC
Proprietary License 1.0, which is the `LICENSE` at this root.

By §3.1b-iii, this component is **on-disk and pinned at the bottom of the scale by
construction**: it invokes no external program, so there is no upstream version to drift under
it and no pin to assert. Its only runtime dependency beyond the standard library is the serving
framework, and the capability module imports nothing at all beyond `os`, `re` and `stat`.

## Directories

| Directory | Holds |
|---|---|
| [`symondevice`](symondevice/symondevice.md) | `inventory.py` — the nine capabilities and how each is read |
| [`tests`](tests/tests.md) | what proves it, and which of the tests can actually fail |

## Where this leads

Into [`symondevice`](symondevice/symondevice.md), which is how each fact is obtained, and then
on to [`tests`](tests/tests.md), where the chain ends.
