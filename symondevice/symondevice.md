# symondevice

`inventory.py` — the nine capabilities, and how each fact is obtained.

One module. Nine public functions, every one of them reachable over HTTP, and `NOT_EXPOSED` is
empty as a **decision** rather than as silence: nothing is withheld from the network. Every
helper that is not a capability is underscore-prefixed, which is the honest way to say "not a
capability" rather than listing it as one that was declined.

## The resolution that everything else rests on

`_driver_of()` answers "which driver is bound to this device", and it is written around one
specific trap.

`readlink -f` — and `os.path.realpath` — **canonicalise a path whose last component does not
exist and return it anyway**. So on a device with no binding, `realpath(dev + "/driver")` hands
back a path ending in `driver`, and `basename` of that is the literal string `driver`. An
implementation built that way reports every unbound device on the machine as bound to a driver
called `driver`, and the answer looks plausible enough to survive review.

Two paths on this host do exactly that, and neither exists:

    /sys/block/nvme0n1/device/driver
    /sys/bus/usb/devices/1-3.5:1.0/driver

So the order is fixed: `os.path.islink()` **first**, then `os.readlink()`, then `basename` of the
link's own target. A dangling link — a recorded binding whose target directory has gone — is
reported with its driver name and `driver_target_exists: false`, because the binding is still
what the kernel recorded. A constructed tree in the tests contains all three cases and asserts
that the middle one returns `None` and not the word `driver`.

`_bus_chain()` extends it upward. A block device is **not bound at its own level** — the binding
sits on the disk node, the controller, or the bus function beneath it — so the walk climbs
towards `/sys/devices` recording each level's subsystem and driver, and `driver_at` names the
level that answered. On this host `nvme0n1` finds its binding four levels up, at the PCI
function; `sda` finds it at the SCSI device.

## The nine

### `cpu()`

Counts, topology, frequency range and the flag list, from `/proc/cpuinfo`, cross-checked against
`/sys/devices/system/cpu`. Two independent sources agreeing is worth more than one source read
twice, and `crosscheck.agrees` is returned so a disagreement is visible rather than averaged
away.

**Two counts, and they are not the same question.** `logical` is what the machine has.
`schedulable_here` is what this process is permitted to run on — `len(os.sched_getaffinity(0))`,
which is what an affinity-respecting tool reports. Measured here: **20** and **8**. Sizing a
plan from the second under-provisions a machine two and a half times larger, and the two are
indistinguishable unless both are returned.

The frequency range comes from `cpufreq`'s `cpuinfo_min_freq` and `cpuinfo_max_freq` where they
exist, falling back to the instantaneous `cpu MHz` in `/proc/cpuinfo` — and `frequency_mhz.source`
says which, because the fallback is a **snapshot and not a range** and reading it as one is wrong.

The flag list is returned verbatim and sorted. It is the thing that decides what can **run** here:
an instruction-set extension a build was compiled against either appears in it or the binary dies
on first use.

### `memory()`

`/proc/meminfo`. The distinction this exists for: **free and available are different numbers and
the gap is usually enormous.** Measured here — 94.1 GiB total, **1.45 GiB free**, **77.67 GiB
available**. Reading the first as the second reports this machine as nearly exhausted when it is
nearly idle, and refuses work on a host with three quarters of its memory reclaimable.

`buffers`, `cached` and `sreclaimable` are broken out, `buff_cache_bytes` is their sum, and `why`
states the arithmetic in the response rather than leaving the reader to reconstruct it.

### `storage()`

Every entry in `/sys/block`. **Nothing is filtered, and `filtered` is returned as an empty list
so the policy is visible.**

A card reader with no card presents a block device reporting **zero bytes**. It is present, it is
bound, it is removable. Filtering by size is how a present device gets reported as absent, and
then somebody goes looking for a hardware fault that is not there — so a zero-size device is
returned carrying a `why` that says exactly that. This host has one.

Mounts are matched by **device number**, not by name: `/proc/mounts` sources are `stat`ed and
compared against each device's `dev` attribute. Matching by name fails the moment a mount is
recorded through a by-uuid path, a symlink or a mapper node, and a missing mount reads as an
unmounted disk.

No disk health tool is invoked. Its informational modes print the serial.

### `pci()`

Every entry in `/sys/bus/pci/devices`: address, `vendor:device`, subsystem pair, revision, class
code, IRQ, and **the driver bound or explicitly none**. Unbound functions appear in `devices`
*and* are collected into `unbound`; four do on this host.

`vendor:device` is lower-case hex without the `0x`, which is the form a bind rule, a modalias and
a udev rule are written against. It is not decoded into the name of whoever registered it.

### `usb()`

Sysfs lists devices and **interfaces** in the same directory — `2-7.1` is a device, `2-7.1:1.0` is
one of its interfaces — and the driver usually binds to the **interface**. Both are returned and
each interface carries its own binding. One interface on this host, `1-3.5:1.0`, has none.

**Topology is the finding.** `depth`, `parent`, `root_port`, `behind_hub` and `hub_chain` are on
every device, because a hub that drops takes everything beneath it with it and the symptom
surfaces **on the device, not on the hub** — so a storage device that vanished gets investigated
as a failing disk while the disk is fine.

`behind_hub` means behind an **external** hub, not the literal answer. Every device is behind a
hub literally: the controller's root hub is class `09` and is the parent of everything on its bus,
so answering literally marks all twelve devices here as at-risk and the field stops distinguishing
anything. Measured here: four devices behind two external hubs, and the system disk `sda` is one
of them, reached through `2-7`.

Class codes are read with an **explicit hex base**. The kernel prints them unprefixed —
`09`, `e0`, `ef` — and `int(x, 0)` raises on a leading zero while `int(x, 10)` silently turns
`10` into ten rather than sixteen. Read as decimal, every hub on this host reported as a non-hub.

### `network()`

`/sys/class/net`: state, carrier, MTU, driver, negotiated speed, duplex, and the PCI address
behind the interface where there is one. `lo` has no `device`, so it is reported as `virtual`
with no driver rather than as an unbound interface.

**The address is not returned.** `has_mac` says whether there is one; `mac_oui` returns three
octets, which name a registrant rather than a machine, and only when `has_mac` is true — an
all-zero address is the *absence* of one, and returning `00:00:00` as an OUI would put a
registrant prefix on an interface that has no hardware address.

`speed` is meaningful only on a link that is up; the kernel errors on a down interface, which is
reported as unknown with a `why` rather than as zero.

### `sensors()`

Every `<kind><n>_input` under `/sys/class/hwmon`, with the kernel's own `_label` byte-exact. The
label is the only thing that says which of eleven readings on one chip is the package and which
are individual cores; rewriting it into something prettier makes the reading unattributable.

Raw and scaled values are both returned — the hwmon interface fixes the scale, and returning only
the scaled figure asks the reader to trust arithmetic they cannot check.

Thermal zones and cooling devices are returned alongside, from `/sys/class/thermal`.

`controls_present` **lists** writable control attributes and this module writes none of them.
Changing a fan curve is not detection.

### `power()`

`/sys/class/power_supply`: type, status, present, online, capacity, technology, `model_name`, and
the micro-unit electrical readings where they exist. `scope` separates a supply that powers the
**machine** from one that powers a peripheral — both live in the same directory, and a battery at
an unknown charge is alarming if it is the machine's and unremarkable if it belongs to a detached
accessory. On this host there is exactly one entry and its scope is `Device`.

`serial_number` is present here and is never returned.

### `owned_by()`

The route that makes this a framework component. It calls the other capabilities, maps each
hardware class to the component that covers it, and returns what nothing covers.

`coverage: "inventory"` is not `coverage: "full"`. Inventorying a thing is not owning it: this
component can say what the fans are doing and nothing in the estate decides what they should do.
Recording that as coverage would make the map lie, so those classes are named in `unowned`
instead of being absorbed. `full_coverage` is `false` and a test asserts it.

## Interfaces

**Reads** — `/proc/cpuinfo`, `/proc/meminfo`, `/proc/mounts`, `/sys/devices/system/cpu`,
`/sys/block`, `/sys/bus/pci/devices`, `/sys/bus/usb/devices`, `/sys/class/net`,
`/sys/class/hwmon`, `/sys/class/thermal`, `/sys/class/power_supply`. Each is a module-level
constant so a test can redirect it at a constructed tree; the real path is never used as a
fallback when one is redirected, because a test that silently reads the live machine has tested
the live machine and not the code.

**Writes** — nothing. Every `open()` here is mode `r` and a test checks each one's mode.

**Imports** — `os`, `re`, `stat`. Nothing else, and no `subprocess`.

**Consumed by** — [`service.py`](../symondevice.md) at the branch root, as
`from symondevice import inventory`, one route per public function with the route handler named
after the function it calls.

**Raises** — `InventoryError` when a source the answer cannot be built without is unreadable;
`service.py` turns it into `409`. An unreadable *contributing* path is not an error: it is named
in `evidence.unreadable` and sets `rc` to 1.

## Where this leads

On to [`tests`](../tests/tests.md), which is where the claims on this page are checked.
