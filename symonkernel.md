# symonkernel

The host kernel, and whether a kernel module can still be built for it.

This page describes what is **built and tested**: 36 tests pass against this host's real
kernels, and every figure quoted below was read off disk while writing it. It is not running as
a service — see **Status** at the end.

## The failure this unit exists to catch

A kernel upgrade lands. The out-of-tree module was built against the kernel that is running,
and nothing rebuilt it for the new one.

Nothing looks wrong. The old modules are still on disk. The driver is still loaded. Every
probe answers, every service is up, and no log line mentions it. The card comes up with no
driver at the next boot, and that is the first moment anybody finds out — which is also the
worst moment, because the reboot was usually for something else and now there are two faults to
tell apart.

`coverage()` is that question asked while it is still cheap to answer.

## What it found on this host, 2026-09-19

    complete : True   — every kernel with a module tree has its module built and placed

    6.12.107+deb13-amd64   covered   headers yes   5/5 files placed
    7.1.13+deb14-amd64     covered   headers yes   5/5 files placed   (running)

    index only, not a gap: 6.12.95+deb13-amd64, 6.12.100+deb13-amd64, 6.12.101+deb13-amd64

Two findings came out of building it, neither of which is visible from the module manager's own
output:

**There are five kernel directories under `/lib/modules`, not two.** Three of them
(`6.12.95+deb13-amd64`, `6.12.100+deb13-amd64`, `6.12.101+deb13-amd64`) hold only the
`modules.*` index files: no `kernel/` tree, no `.ko` file of any kind, no `build` link, and no
header tree in `/usr/src`. They are what a removed kernel package leaves behind. They are
listed, because filtering them out silently is how a stale directory stays invisible — and they
are bucketed separately from the verdict, because holding a module manager to account for a
kernel whose image is gone produces three loud findings on a host where nothing is wrong, and a
report whose first three lines are false is a report nobody reads the fourth line of.

**The compiler that built this kernel is not the compiler a build would reach for.**
`/proc/version` records `15.3.0`; `/usr/bin/cc` on this host is `14.2.0`. A compiler at `15.3.0`
is installed, but only under its fully qualified name, `/usr/bin/x86_64-linux-gnu-gcc-15` —
there is no `gcc-15` on `PATH` at all. So "a compiler is present" and "the compiler this kernel
was built with is present" are different answers here, and only the second one describes the
build that would actually happen.

That is reported as its own precondition and **does not flip the verdict**. This unit does not
run a build, so it is not entitled to claim one would fail. What a build system does with a
mismatched compiler is a fact about that build system; what is installed on this host is the
fact this unit is entitled to report.

## Where the tools are, and why that is not a detail

The module manager is at `/usr/sbin/dkms`. That directory is **not on this user's PATH**:

    command -v dkms            -> rc=1
    /usr/sbin/dkms --version   -> dkms-3.4.3

A unit that asked `PATH` would report the manager absent on a host where it is installed and
working. That is the most expensive kind of wrong answer, because an absent module manager and
a quiet one produce the same empty list and only one of them is good news. So the binary is
found by looking at a list of paths, `PATH` is the last resort rather than the first, and the
`PATH` answer is reported beside it as its own fact. A test fails if the locator is ever
simplified back to `PATH`.

For the same reason the loaded-module table is read from `/proc/modules` rather than by running
a formatter over it. That is the same data from the same kernel, with one fewer program on a
`PATH` that has already proved unreliable here.

## The difference is only an answer after the names are normalised

A module is spelled with hyphens on disk and with underscores in the loaded table:
`nvidia-uvm.ko.xz` against `nvidia_uvm`. Compare the raw strings and every such module lands in
**both** halves of the difference at once — built-but-not-loaded *and* loaded-with-no-file — so
the one output the function exists to produce becomes noise, with a real finding somewhere
inside it. `_module_name()` strips the compression suffix and maps `-` to `_` on both sides
before anything is compared, and a test asserts the two spellings genuinely differ on this host
so that it cannot pass on a raw comparison.

The measured difference for the running kernel:

    out-of-tree placed : nvidia, nvidia_drm, nvidia_modeset, nvidia_peermem, nvidia_uvm
    built, not loaded  : nvidia_peermem
    loaded, no file    : (none)

The in-tree modules are **counted, not listed**. This kernel ships 4,230 module files and 187
are loaded; listing the remainder as "built but not loaded" is four thousand lines of nothing
wrong wrapped around anything that matters.

A kernel that is not the running one gets **no difference at all**, only its file listing. The
loaded table describes the running kernel and only the running kernel, so diffing it against
another kernel's files is a comparison between two kernels presented as a finding about one.

## Nothing here changes kernel state

This unit reads. It never builds, installs, loads or unloads anything, and it never writes
under `/usr/src` or `/lib/modules`.

`coverage()` reports the argument vector an operator would run to close a gap — as **data**,
never executed. Reporting a command and running one are different acts and only one of them
belongs in a status unit. A test walks every `subprocess` call in the module with `ast`, requires
each argument vector to be a literal list it can read, and fails on any state-changing verb or
on `shell=True`. A second test fails on any write, create, rename or delete call appearing in
the module at all.

## Where the module names come from

Not from this file. The manager reports which packages it has, and each package declares the
modules it builds; those declarations are read from
`/usr/src/<package>-<version>/dkms.conf`. A list written down here would be right until the
day the driver adds a module, and wrong in silence afterwards. A test fails if any module name
the package declares also appears as a literal in `kernel.py`.

## Routes

    GET /api/symonkernel/health      public; answers before the unit is configured
    GET /api/symonkernel/running     the running kernel, and the compiler that built it
    GET /api/symonkernel/kernels     every kernel directory here, and whether each has headers
    GET /api/symonkernel/dkms        what the module manager reports; absent is never empty
    GET /api/symonkernel/modules     files on disk against what is loaded — and the difference
    GET /api/symonkernel/coverage    is the module built for every kernel that has a tree
    GET /api/symonkernel/buildable   can a module be built now, precondition by precondition

`?release=<kernel>` selects a kernel for `modules` and `buildable`; the running one is the
default. An unknown release is a `409` naming the kernels that are here, never an empty answer.

Health is public; the rest need `SYM_KERNEL_TOKEN` **only when the bind is off loopback**. On a
loopback bind no token is asked for, because a token there defends only against a caller who
already has code execution on this host and could read the token. Off loopback the token is
required and an unset one returns `503`: a unit that becomes reachable through a configuration
change must not become public through that same change. The bind address decides this at
runtime, in `_open_on_loopback()`, rather than by convention.

One public callable carries no route and says so in `NOT_EXPOSED`: `compilers` is served inside
`GET /api/symonkernel/buildable`, because which compilers exist is not an answer on its own —
the question is always whether one of them matches the kernel about to be built for, and
splitting them into two routes invites a caller to read "a compiler is present" and act on it.

## Interfaces

| Direction | What | Where |
|---|---|---|
| reads | the running kernel and its build compiler | `os.uname()`, `/proc/version` |
| reads | what is loaded right now | `/proc/modules` |
| reads | kernel module trees, `build` links, module files | `/lib/modules/<release>/` |
| reads | header trees and their declared release | `/usr/src/linux-headers-<release>/`, `include/generated/utsrelease.h` |
| reads | what each managed package builds | `/usr/src/<package>-<version>/dkms.conf` |
| runs | the module manager, read-only | `/usr/sbin/dkms status` |
| runs | each compiler, to read its version | `<compiler> -dumpfullversion` |
| serves | seven routes | `127.0.0.1:8824`, `/api/symonkernel/` |

| Variable | Default | What it does |
|---|---|---|
| `SYM_KERNEL_HOST` | `127.0.0.1` | the bind address, and therefore whether a token is required at all |
| `SYM_KERNEL_PORT` | `8824` | the port |
| `SYM_KERNEL_TOKEN` | unset | required only off loopback; unset off loopback closes the unit |

**Recorded and not acted on:** these three names are not in the estate's configuration contract
(`symoneural-learn.env.example`), so the `contract-declared` gate skips this branch for want of
a contract file rather than passing it. Declaring them is work in another branch and is named
here rather than done here.

## Placement

    placement-triage prospect symonkernel --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

The sources this component is **built from** are two, and they are the only two:

| Source | Licence | How it is used |
|---|---|---|
| python standard library | PSF-2.0 | `os`, `re`, `shutil`, `subprocess`, `pathlib`, `ipaddress`, `hmac` |
| fastapi | MIT | the HTTP surface in `service.py` |

Both are permissive. Nothing copyleft is imported, linked or vendored, so the default applies
and this branch carries the proprietary licence.

**What this component READS is not what it is BUILT FROM, and the distinction is the whole
answer.** This unit reads the metadata of kernel module files, and a kernel module is licensed
under the GPL. That does not reach this code, for three separate reasons, any one of which
would be sufficient:

1. **It reads paths, not contents.** What is read is the existence, the name and the location
   of a file. No byte of any module is loaded into this process, linked against it, or copied
   into it.
2. **Nothing is derived.** A copyleft obligation attaches to a derivative work. A listing of
   filenames in a directory is not a derivative of the files, any more than `ls` is a
   derivative of everything it has ever printed.
3. **The module manager is reached across an exec boundary.** `/usr/sbin/dkms status` is run as
   a separate program with an argument vector and its standard output is parsed. That is
   invocation, not linkage — the same reasoning by which the ship gate classes bash and
   coreutils `INVOKED_NOT_LINKED` rather than letting their licence reach code that merely
   executes them.

Reading a GPL-licensed file does not make the reader GPL. If it did, every file manager on the
system would be copyleft. A component belongs in the open tree when its **output** is copyleft
and would reach a shipped artifact; this component's output is a JSON document describing what
is on a disk.

The kernels, the headers and the modules themselves are the host's, installed by the host's
package manager, and are not components of this artifact under any of the four trees.

## Testing

36 tests. Most assert a **refusal** or the **shape** of an answer, because the way this unit
fails is not by crashing — it is by answering "nothing to report" when it could not ask the
question. An empty list, a missing kernel and a driver with no build each have a truthful form
and a comfortable one, and the comfortable one is indistinguishable from healthy in every
report it appears in.

What is asserted: an absent module manager is named with where it looked and never returns a
bare empty list; both spellings of a manager status line parse to the same fields; a status of
`installed` is not taken as proof the files are placed; out-of-tree modules with no manager
accounting for them are a gap rather than a clean result; an index-only directory is bucketed
and is neither covered nor a gap; a kernel that is not running gets no difference invented; an
unknown release is refused and the refusal names the kernels that are here; a missing `build`
link names *itself* rather than only saying no; a header tree that states another kernel's
release is caught; both compiler versions are reported and the mismatch is not blocking; and
every public capability is routed or declared unrouted.

Each test was checked against a deliberately broken version of the code. Eight mutations were
run — dropping the name normalisation, dropping the compression-suffix strip, binding the
manager lookup to `PATH`, holding index-only directories to account, bucketing every directory
as index-only, dropping what a gap would need, trusting a reported state over the files, and
diffing a non-running kernel anyway — and each is killed by a named test.

That harness found two tests that were not tests, which is the reason for running it:

- The index-only test asserted only that the bucket did not **overlap** the gaps, which passes
  when the bucket is empty — so the mutation that emptied it survived. It now asserts the
  bucket's identity, and a second test builds a synthetic tree so the rule holds on a host with
  no stale kernel directory.
- The both-halves test built its fixture by calling the very function being mutated, so
  breaking that function made the test **skip** rather than fail. It now spells the expected
  mapping out itself, independent of the code under test.

A test that can only pass, or that skips itself when the code breaks, looks exactly like a
working test in every report it appears in.

    python3 -m pytest tests/ -q

Run it from this directory with `python3 -m`, which is what puts the directory on the import
path for `service` and `symonkernel`.

## Where this sits

[symondriver](../symondriver/symondriver.md) asks whether the driver's userspace agrees with
the module that is **loaded**. This asks whether a module exists for every kernel that could be
**booted**, and whether another could be built. Neither answer implies the other: a perfectly
consistent running stack is exactly what a host looks like the day before an uncovered kernel
boots.

[symonprobe](../symonprobe/symonprobe.md) owns the card and reports on it while it is serving.
It is not asked anything here, deliberately: a coverage check that needs another service to be
up fails open exactly when the estate is degraded.

The gate that requires every capability on this branch to carry a route lives on
[gates](../gates/gates.md) — `endpoints-current`, written after a release shipped with its
whole arithmetic unreachable over HTTP.

The flow ends here. Nothing consumes this unit yet: it is not registered on the board, not
wired into the fabric and not exposed as an agent tool, so there is no next document to follow.
That is a status, not a design — see below.

## Releases

Tagged `symonkernel/v<version>`.

## Status

**Built and tested, not running.** 36 tests pass and every function was exercised against this
host's real kernels, headers, module manager and compilers. Nothing is serving on `8824`, the
unit is not registered on the board, and no consumer has called it. `SYM_KERNEL_TOKEN` is
unprovisioned, which is the correct state for a loopback bind and would close the unit the
moment the bind moved off loopback.
