# symondriver

The GPU driver's userspace surface, and whether it is **consistent** with the kernel module.

This page describes what is **built and tested**: 23 tests pass against this host's real driver,
and the disagreement this unit exists to find was found on the first run. It is not yet running
as a service — see **Status** at the end.

## The failure this unit exists to catch

A partial package upgrade leaves the userspace libraries at one version and the loaded kernel
module at another. Nothing announces it. The first symptom is a compute call into the driver
failing with an error that names neither version, so the message sends an operator to look at
the application while the fault is in the installation.

There is no single place to read the answer, because there is no single place the version is
kept. It is kept in four:

| Source | Read from | Why it is not the same question as the others |
|---|---|---|
| the loaded kernel module | `/proc/driver/nvidia/version`, cross-checked against `/sys/module/nvidia/version` | what is **running** — the only one that can differ from everything installed |
| userspace | by **running** `nvidia-smi --query-gpu=driver_version --format=csv,noheader` | what a caller actually gets back. A file describing what userspace would say is not userspace saying it |
| the libraries | `/usr/lib/x86_64-linux-gnu` and `/usr/lib/i386-linux-gnu` | what a process will **link**, in every architecture installed |
| the packages | `dpkg-query` | what the package manager believes it put there |

`consistent()` is the point of the unit and every other function feeds it.

## What it found on this host, 2026-09-19

    consistent: False
    versions  : 550.163.01, 615.71.09

    kernel module                  615.71.09   /proc/driver/nvidia/version
    kernel module (sysfs)          615.71.09   /sys/module/nvidia/version
    userspace                      615.71.09   /usr/bin/nvidia-smi --query-gpu=driver_version
    libraries (x86_64-linux-gnu)   615.71.09   43 versioned files
    libraries (i386-linux-gnu)     615.71.09   15 versioned files
    packages                       615.71.09   61 packages
    packages                       550.163.01    1 package: nvidia-open-kernel-source

76 library files are found in total; 58 of them carry a driver version, directly or through the
soname they resolve to, and those are the 43 and the 15 above. The other 18 report no version
to compare and are listed with that reason — see the next section.

**The running stack is coherent; one installed package is not.** The loaded module, userspace
and every versioned library agree at `615.71.09`. A single package, `nvidia-open-kernel-source`, sits
at `550.163.01-2` from source package `nvidia-open-gpu-kernel-modules` — a second, older copy
of the same kernel-module source, left behind while `nvidia-kernel-open-dkms` (source package
`nvidia-kmod-open`) moved to `615.71.09-2`.

That distinction is reported rather than collapsed, because the two possible readings have
opposite consequences. "The driver is inconsistent" implies the running stack is suspect; it is
not. What is stale is installed and not loaded, and `running_stack.consistent` says so in the
same result.

The loaded module reports itself as the **open** variant, built on `symon` — this host — on
Thu Sep 17 2026 at 08:37:56 PM EDT with compiler `15.3.0`. It was compiled here from source
rather than installed as a prebuilt binary, and `built_here` establishes that by comparing the
stamp against this host's name rather than by assuming it.

## Two version series share one filename space

Several files matching `libnvidia*` and several packages matching the same pattern come from
source packages that have never tracked the driver and never will — they sit on their own
series entirely. Counting them as disagreement would report every host as permanently
inconsistent, which is the same as reporting nothing.

They are separated by one pattern, `^\d{3}\.\d+\.\d+$`, which is read off the estate's own data
rather than invented: it admits the running `615.71.09` and the stale `550.163.01` and rejects
the toolkit at `13.4.x` and the unrelated libraries at `1.0.2`, `1.0.6` and `1.1.4`.

**Everything set aside is still returned, each entry carrying the reason it was not compared.**
A filter nobody can see is indistinguishable from a bug. The pattern itself is in every result
that uses it, so a reader can check the partition instead of trusting it.

A soname link is not a set-aside. `libcuda.so.1` carries the ABI number, not the driver
version, so the link is followed and the entry is credited with the version of the file it
resolves to, saying in `version_from` which name that came from. Filing it under "another
version series" would have been false: it is the driver, reached through its soname.

## Nothing here writes, loads or installs

Every path is opened read-only. Exactly two programs are ever executed — the query tool in
`userspace()` and `dpkg-query` in `packages()` — both as argument vectors, never through a
shell, and a test asserts against the module source that no shell is invoked anywhere.

`binaries()` **locates** the known driver programs and runs none of them. One of them writes a
large archive as its entire purpose; an inspector that executed what it found would produce a
file every time somebody asked it a question. That program is returned with a
`never_run_here` field carrying the reason, so the restriction travels with the list instead of
living in somebody's memory.

Sonames are read from each file's own ELF dynamic section, not inferred from its name — a
filename is a convention, `DT_SONAME` is what the loader goes by, and the two disagreeing would
itself be worth seeing. The class byte decides the struct layout, because 23 of the 76
libraries here are 32-bit and assuming 64-bit would misparse a third of them and return a
plausible wrong answer. A test cross-checks the parser against `readelf -d` rather than
asserting this unit's output back at itself.

## Routes

    GET /api/symondriver/health          public; answers before the unit is configured
    GET /api/symondriver/kernel-module   the loaded module: version, variant, build host, date, compiler
    GET /api/symondriver/userspace       the version userspace reports, by running the query tool
    GET /api/symondriver/libraries       every driver library, grouped by architecture, with sonames
    GET /api/symondriver/binaries        which known driver programs exist; none is executed
    GET /api/symondriver/packages        the installed package family, split by version series
    GET /api/symondriver/consistent      every version seen and where each one came from

`consistent` returns **200 with the sources named** when they disagree. A mismatch is the
deliverable, not an error: an operator can read a 200 body and cannot read a 500.

## Interfaces

| Interface | Value | Notes |
|---|---|---|
| `SYM_DRIVER_HOST` | default `127.0.0.1` | decides whether a token is required, at runtime |
| `SYM_DRIVER_PORT` | default `8825` | free on this host and claimed by no other unit |
| `SYM_DRIVER_TOKEN` | unset | required only off-loopback; unset off-loopback closes the unit |
| files read | `/proc/driver/nvidia/version`, `/sys/module/nvidia/version`, `/usr/lib/x86_64-linux-gnu`, `/usr/lib/i386-linux-gnu` | read-only, always |
| programs run | `nvidia-smi`, `dpkg-query` | argument vectors only |
| consumed by | nothing yet | it is built, not wired — see **Status** |

Health is public. The rest follow the estate's bind-address rule: **the bind address decides,
not a convention in prose.** On loopback no token is asked for, because a token on a `127.0.0.1`
bind defends only against a caller who already has code execution on this host and can
therefore read the token. Off-loopback the token is required and an unset one returns 503 — a
unit that becomes reachable through a configuration change must not become public through that
same change. Both halves of that contract have a test.

Every public callable has a route, so `NOT_EXPOSED` is present and empty. Empty is a decision
rather than silence: nothing is withheld. The internal helpers — version normalisation, the ELF
reader, the filename parser — are underscore-prefixed, which is the honest way to say "not a
capability" instead of listing them as capabilities that were declined.

## Placement

    placement-triage prospect symondriver --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License 1.0

**This component is built from the Python standard library (PSF-2.0) and FastAPI (MIT). That
is the whole list, and it is what decides the licence.**

The driver this unit inspects is dual-licensed `MIT OR GPL-2.0-only`. That is not a guess: the
recipes for it in the open tree declare it, and can be read —

    /mnt/SymonSayOpen/recipes-platform/recipes/symoneural-nvidia-open-kernel/
        symoneural-nvidia-open-kernel.inc                     LICENSE = "MIT OR GPL-2.0-only"
        symoneural-nvidia-open-kernel_615.71.09.bb            LICENSE = "MIT OR GPL-2.0-only"
        symoneural-nvidia-open-kernel-debian_615.71.09.bb     LICENSE = "MIT OR GPL-2.0-only"

**Reading it does not make this component copyleft, and that reasoning is the point of writing
this section down.** §3.1b-i calls the distinction *placing by consequence versus placing by
tidiness*. A component belongs in the open tree when its **output** is copyleft and would reach
a shipped artifact. This component links nothing from the driver and imports nothing from it.
It opens text files the driver publishes, reads filenames out of two directories, parses ELF
headers it does not load, and runs two programs as subprocesses reading their standard output.
None of those is linking, and none of them propagates an obligation.

Placing this in the open tree because it is *about* something copyleft would be placing by
resemblance. That is the failure §3.1b-i names: a tree whose members got there by resemblance
stops meaning anything, and the whole value of the split is that membership in the open tree is
a claim someone was forced to make.

So: **proprietary, `SymonSayDistribute`, SymonSaysLLC Proprietary License 1.0** — the default
under §3.1b, reached because nothing forced anything else.

Recorded and deliberately **not** acted on here, because it is adjacent work and §3.5 says name
it and stop: the ship gate's component census would not corroborate the claim above, for the
same reason it did not corroborate `symonimage`'s — it detects interpreters and Python imports,
not files read through `open()` or programs reached through `subprocess`. Silence from a gate is
not agreement from it.

## Testing

    python3 -m pytest tests/ -q

23 tests. The `-m` form is load-bearing: it puts the branch root on `sys.path`, which is how
`service` and `symondriver` are importable. A bare `pytest` run failing on imports is that, not
a broken suite.

The tests that matter are the mismatch tests. A consistency checker exercised only against a
host that agrees with itself has been exercised against nothing — it would pass identically if
`consistent()` returned `True` unconditionally. So the disagreement path is driven twice, and
both assert that the disagreeing source is **named**, not merely that a boolean flipped:

- an injected source through `extra_sources`, asserting the injected version, its origin string
  and its entry in `disagreements`;
- a replaced real source — `kernel_module` monkeypatched to a stale version — asserting
  `by_source["kernel module"]` and that the module is named in `disagreements`.

A third drives the opposite failure: a source that raises is listed in `unavailable` and named
in `why`, and `consistent` is `False`. Dropping an unreadable source would let the rest agree
with each other and report a consistency that was never established.

A fourth drives the **agreement** path, which on this host would otherwise never execute at
all — and the first time it ran would be the moment somebody removed the stale package and came
back to confirm the fix had worked, which is the worst possible time to meet a formatting bug.
The stale entry is dropped and the verdict must flip to `True` with a rendered `why` that names
who agreed.

The remainder read the real thing: the module names its version, variant, build host, date and
compiler; the two files it publishes agree with each other; an absent `/proc` file answers *not
loaded* rather than returning empty; both architectures are found; a versioned library resolves
to a real file; the ELF parser agrees with `readelf`; the known programs are located and
`binaries()` contains no subprocess call at all; package versions compare on their upstream part
so that `615.71.09-2` and `615.71.09` are one version and not two.

## Releases

Tagged `symondriver/v<version>`.

## Status

**Built and tested, not running.** Nothing listens on 8825, the unit is registered with no
control board, and no component consumes it. `SYM_DRIVER_TOKEN` is unprovisioned, which on the
loopback default is not a blocker — the unit answers every route without one.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symondriver`](symondriver/symondriver.md) | the capability this unit provides — `driver.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symondriver`](symondriver/symondriver.md), [`tests`](tests/tests.md).

The flow continues at [symonprobe](../symonprobe/symonprobe.md), and the split between the two
is deliberate: this unit answers what the **driver software** is and whether its four sources
agree; symonprobe answers what the **device** is and whether a given build can run on it. A
driver stack that agrees with itself can still be paired with a build compiled for an
architecture the device does not have, and that is symonprobe's question, not this one's.

The gates that check both are on [gates](../gates/gates.md) — `endpoints-current`, which refuses
a capability no route reaches, and `no-divergent-copy`, which refuses the same module name
existing twice with different contents.
