# symoncross

What this build host can target, measured on the host rather than recalled.

This page describes what is **built and tested**: 44 tests pass, and every verdict below was
produced by running the code on this machine, not by reading a note about it.

## This component cross-compiles nothing

It answers one question: **can the estate build for target X right now, with what, and what is
missing.** It compiles no estate component, fetches no layer, creates no build directory and
writes nothing outside its own worktree.

The distinction is the whole point of the component. A report claiming the estate "builds for
the mingw target" while nothing on this host can emit a PE binary would be a phantom completion
— the report exists, the artifact does not. So every answer carries the evidence it came from:
the path that was read, the argument vector that was run, and the exit code that came back.

## What `buildable` means, exactly

    buildable  = the toolchain on this host can emit an artifact for that target,
                 proven by emitting one.
    buildable != the estate has source that wants building for that target.

Conflating those two produces nonsense in both directions. This host has a working C compiler
and a C library, so `linux-native` is buildable — and the estate holds **zero** `.c` and `.cpp`
files, so nothing wants it. The second question is answered separately by `portability()`, and
for these components it is the one that matters.

Platform identifiers are used as the toolchains spell them — `linux`, `darwin`, and the family
name that appears in the triple `x86_64-w64-mingw32` — and as the layer directory is named,
`meta-mingw`. They are opaque identifiers here, required to configure and run the software, and
nothing in this component is about the parties that publish them.

## The verdicts, measured

Produced by `targets()` on this host. `blocked_by` is derived from the preconditions and
`buildable` is derived from `blocked_by`, so a false verdict structurally cannot arrive without
its reasons. A bare boolean is never returned.

| Target | buildable | blocked_by |
|---|---|---|
| `windows` | **false** | mingw cross compiler on PATH · meta-mingw layer acquired · build-and-integration tool on PATH · an OE build directory exists |
| `darwin` | **false** | compile probe for `x86_64-apple-macosx13.0` |
| `jvm` | true | — |
| `linux-native` | true | — |

## Three of the four are settled by compiling

Not by inspecting. Each target that has a toolchain gets a few lines of probe source written
into a fresh temporary directory, compiled with an argument vector and a timeout, and the
result is read back from the artifact's first four bytes:

- `linux-native` — a C program is compiled, run, and its output checked. ELF, `7f454c46`.
- `jvm` — a class is compiled and its magic checked. `cafebabe`.
- `darwin` — one line is compiled for the darwin triple against the SDK on disk.

The probes are the component's own source, never an estate or upstream tree, and a test proves
that by intercepting the compiler calls and asserting the file handed over sits inside the
temporary directory the probe just made. The directories are removed in a `finally`, and a test
asserts none is left behind.

**The SDK tree is read, never written.** The darwin compiler aborts on that SDK, which is the
kind of failure that leaves state behind, so it was checked rather than assumed: after every
probe run in this session, `find <bundle> -newermt '2026-09-19 17:00'` returns nothing. The same
check over the layer roots and the `meta-mingw` cache copy is also empty.

## The darwin finding, which contradicts what was expected

The SDK on disk was described as a real usable cross-target. **It is not, today.** Every
structural check passes and the compile still fails:

- the bundle is present, 3.2 GB, with `swift-sdk.json`, `toolset.json`,
  `darwin-sdk-version.txt` and `Developer/`;
- the manifest parses and declares five target triples;
- its `sdkRootPath` resolves through a symlink to a real 868 MB tree;
- the host compiler works — the same compiler builds a native binary with `rc=0`.

And the cross compile exits **1** with **719 errors**, the first of them inside the SDK's own
standard library interface, because the host compiler cannot parse syntax the SDK was built
with. The two are not a matched pair.

    swiftc -sdk <bundle>/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX26.5.sdk \
           -target x86_64-apple-macosx13.0 -o <probe>.bin <probe>.swift
    rc=1, 18.2s, no artifact
    ...x86_64-apple-macos.swiftinterface:12095:41: error: expected an identifier to name
       generic parameter

Separately, `swift sdk list` reports no SDKs installed: the bundle sits in the toolchain's
directory but is not registered with it. That does not by itself decide the question — the
probe passes `-sdk` directly and needs no registry — which is exactly why the probe exists.
Reading the manifest would have returned `buildable: true` and been wrong.

## `portability()` — the answer that actually decides this

`targets()` says what the toolchain could emit. `portability()` says why these components would
not run elsewhere anyway, and for a Python estate with no native code that is the real answer to
"make these run on another platform". Nothing here needs a cross-compiler. What is in the way is
written into the Python: absolute paths that exist only on this platform, and programs that ship
only on it.

As measured across `/mnt/SymonSayDistribute` on 2026-09-19, scanning 119 files: **44
platform-locked call sites in 13 files across 9 components**, each returned with its file and
line.

| Component | sites | what locks it |
|---|---|---|
| `symonkernel` | 15 | the module tool, `/lib/modules`, `/proc/modules`, `/proc/version` |
| `symonbuild` | 6 | six `/proc` reads |
| `symondriver` | 6 | the device query tool, the package query tool, `/proc/driver/...`, `/sys/module/...`, the multiarch library directory |
| `workflow` | 6 | the linker cache tool and the package database tool |
| `skills` | 4 | the package database tool, the linker cache tool, the kernel name tool |
| `board` | 3 | the device query tool, the socket tool, `/proc/<pid>/cmdline` |
| `symonscope` | 2 | the socket tool, `/proc/<pid>/cwd` |
| `symonimage` | 1 | the device query tool |
| `symonprobe` | 1 | the device query tool |

**That table is a reading, not a fixture.** The estate was being written to while it was taken —
the scan rose from 111 files to 119 and `symonbuild` from five sites to six during this
component's own construction. The route recomputes it on every call, and any figure quoted from
this page is as old as this page. Ask the route.

The scan reads the Python syntax tree, not the bytes. A regex matches the word in a comment and
in a sentence, and a finding that points at prose discredits every finding beside it — comments
are not in the tree at all, and docstrings are skipped explicitly. The detector was tightened
after a first run reported four such: a route path ending in a tool's name, and three error
messages that merely mention the tool they are about. Two tests hold that line, and a third
proves the detector is still alive rather than passing by finding nothing.

**Known gap, stated rather than papered over:** a program reached only through a variable
holding a computed name is not detected. A literal name is, wherever it appears — including
`exe = "/usr/bin/nvidia-smi"` followed by a run of `[exe, ...]`, and a program named in the
second stage of a shell pipeline.

**Declared exclusion:** this scanner and its tests name the programs they detect, so scanning
them would report the detector as the defect. Both files are returned in the record, under
`excluded`, with the reason. An exemption nobody can enumerate is a hole, and a test asserts the
record carries them.

That exclusion was matched by relative path suffix at first, which worked from the estate root
and **silently lapsed for any root at or below this component** — the one root where the scanner
is certainly in range. `GET …/portability?root=/mnt/SymonSayDistribute/symoncross` would have
reported the detector's own constant list as findings and returned an empty `excluded`. It is
now an absolute path comparison, and a test runs the scan from three roots including this
directory. That test fails against the old form.

## Layers: ACQUIRED is not the same as sitting on the disk

`layers()` draws one distinction and it is the point of the function.

**ACQUIRED** — the estate tracks this upstream under `/mnt/SymonSaySource` with a pin naming its
commit, so the same bytes can be fetched again and the choice defended later.

**PRESENT** — the bytes are on the disk and nothing records what they are.

The two are indistinguishable in a directory listing and are not remotely the same thing to a
build. Measured: **587 layers seen across four roots**, 23 reported, of which 13 are ACQUIRED
(the `openembedded-core` and `meta-openembedded` sublayers, pinned at
`fe7a24bc…` and `43b79d8e…`) and 10 are PRESENT.

A download cache can never be ACQUIRED, whatever a pin might say, because a cache is a download
area and not a tree the estate owns. A test exercises that rule directly.

### Tracked is not the same as at-the-pinned-commit, and all thirteen have drifted

An ACQUIRED record originally repeated its pin's revision beside the directory, which reads as a
statement about the tree and was a statement about the estate's intent. Nothing had compared
them. So `layers()` now reads the checkout's commit with `git -C <repo> rev-parse HEAD` and says
whether it matches.

**It does not. All 13 ACQUIRED layers are at a commit their pin does not name:**

| Repository | pin says | checkout is at |
|---|---|---|
| `openembedded-core` (3 layers) | `fe7a24bc67118e7e184b5f5247258715e3904e7c` | `70dc15941dd33270a92d1001174efb3093e79bdf` |
| `meta-openembedded` (10 layers) | `43b79d8e372c4f69ebab6c85b39d97b41522080f` | `bec755063a8b5da65df626f5749496aadaa4f4bb` |

Both sit on the sandbox device. The record says so in words — *"the tree on disk is NOT the
pinned bytes"* — and `drifted_names` and `totals.acquired_but_drifted` carry it for a consumer.
This component reports the drift and does not resolve it: whether the pin or the checkout is
wrong is a decision about what the estate means to build from.

Enumerating 569 cache entries would bury the distinction, so outside a cache every layer is
listed individually and from a cache only the cross-target ones. The root summaries still carry
the true totals with the search depth they were reached at — a count from a search whose reach
is not stated is a number nobody can reproduce, and at depth 2 this same cache reported zero.

## Routes

    GET  /api/symoncross/health          public; answers before the unit is configured
    GET  /api/symoncross/hosts           os, arch, libc, native compiler, read at call time
    GET  /api/symoncross/layers          layers, ACQUIRED or PRESENT; ?name= selects
    GET  /api/symoncross/builders        every build system, every copy found, what is on PATH
    GET  /api/symoncross/targets         all four targets with preconditions and blocked_by
    GET  /api/symoncross/targets/{name}  one target; an unknown name is a 404 listing the rest
    GET  /api/symoncross/portability     every platform-locked site, with file and line

Health is public; the rest require `SYM_CROSS_TOKEN` **only off loopback**. On a loopback bind
there is no credential at all: a token there defends only against a caller who already has code
execution on this host, and such a caller can read the token. Off loopback the token is required
and an unset one returns 503, so a unit that becomes reachable through a configuration change
cannot become public through that same change. The bind address decides at runtime; it is not a
convention in prose.

`targets` is not fast — about twenty seconds, nearly all of it the darwin probe. That is the
cost of a measured answer instead of an inferred one. The probes are cached for the life of the
process and every record carries the time it was actually measured, so a repeated call says when
the measurement was taken rather than implying it was taken now.

`NOT_EXPOSED` is declared and **empty**: every public callable in `targets.py` carries a route.
The name is declared rather than omitted because an empty mapping is a decision on record, which
is a different statement from not having considered it.

## Interfaces

| Direction | Interface |
|---|---|
| Listens | `SYM_CROSS_HOST` (default `127.0.0.1`), `SYM_CROSS_PORT` (default `8827`) |
| Credential | `SYM_CROSS_TOKEN`, required off loopback only, unprovisioned |
| Reads | `/mnt/SymonSaySource/*/pins/*.json` — the pins that decide ACQUIRED |
| Reads | `/mnt/SymonSayDistribute` — every `*.py`, for `portability()` and the source census |
| Reads | the four layer roots, to the depth each record states |
| Reads | `/home/google/.swiftpm/swift-sdks/darwin.artifactbundle` — SDK manifest and root |
| Runs | `cc`, `javac`, `java`, `swiftc`, `cmake`, `ninja`, `make`, `cargo`, `go`, `ldd`, `uname`, `dpkg-query` — argument vectors, never a shell string, always with a timeout |
| Never runs | the build-and-integration tool. Starting one is a build, and this does not build. |
| Writes | nothing outside this worktree; probe sources go to a fresh `mkdtemp` and are removed |
| Overrides | `SYM_CROSS_DIST_ROOT`, `SYM_CROSS_SOURCE_ROOT`, `SYM_CROSS_DARWIN_BUNDLE` |

## Placement

    placement-triage prospect symoncross --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License 1.0

**Built from:** the Python standard library (PSF-2.0) and FastAPI (MIT), with Pydantic (MIT),
Starlette (BSD-3-Clause) and uvicorn (BSD-3-Clause) beneath it, and pytest (MIT) for the tests.
Those are the sources, and the sources decide the licence. Proprietary is the default here, not
a fallback.

**Inspecting a copyleft toolchain does not make this copyleft.** This component reads the paths
of a build-and-integration tool distributed under a copyleft licence, and reports layer
directories from trees carrying their own. It links none of them, imports none of them and
executes none of them. A component belongs in the open tree when its **output** is copyleft and
would reach a shipped artifact — placing by consequence, not by resemblance. Nothing copyleft
reaches this artifact, which contains no compiled code at all.

The programs it *does* run — the compilers behind the probes — are invoked as programs and read
as data, never linked or imported, the same reasoning that places the units whose runtimes are
programs they run rather than libraries they link. What those compilers emit is a probe that is
deleted seconds later and is never shipped.

**Not corroborated by the ship gate, and saying so matters.** No census has been run against
this branch. The claim above is reasoned from how the code works, not confirmed by a gate that
looked. Silence from a gate is not agreement from it.

## Barriers

Raised, not worked around. Each carries the evidence it was read from.

**1. No PE binary can be produced on this host today, by any route.** Four independent
blockers, all measured:

| Blocker | Evidence |
|---|---|
| No cross compiler | `shutil.which` returns `None` for `x86_64-w64-mingw32-gcc`, `x86_64-w64-mingw32-g++` and `i686-w64-mingw32-gcc`; the package query returns rc=1 with nothing installed |
| The build-and-integration tool is not on PATH | `which` returns `None`. Four copies exist on disk and are reported; three of them sit on the sandbox device |
| No build directory | `/yocto` exists, is root-owned and holds **zero** entries |
| `meta-mingw` is PRESENT, not ACQUIRED | Two copies, both under `~/.cache/oematch/layers`, both with `conf/layer.conf`, both dated 2026-08-21. No pin under `/mnt/SymonSaySource` names it: 108 pins searched, none matched | <!-- gate-allow: no-august — a measured mtime read off disk, quoted as the reason the material is refused, not material built from -->

A cache is not a tree the estate owns. Nothing is built from one, and the dating puts both
copies in material that is not to be used. Acquiring `meta-mingw` — recording its commit, its
licence file checksum and its copyright line as a pin — is the first step if this target is ever
wanted, and it has not been taken.

**2. The darwin SDK and the host compiler are not a matched pair.** Detailed above: rc=1, 719
errors, no artifact, while the same compiler builds natively with rc=0. This is a barrier
because the briefing this component was built from recorded the SDK as usable, and a probe
disagreed with it.

**3. There is nothing here to cross-compile.** The estate's components are Python: **121 `.py`
files and zero `.c`, `.cpp`, `.rs`, `.go`, `.swift`, `.java` or `.kt` files** across
`/mnt/SymonSayDistribute`. A cross-toolchain would have nothing to consume. What actually stops
these components running on another platform is the 44 sites in `portability()`, and none of
them is a build problem.

**4. Three of the four build-tool copies sit on the sandbox device.** They are reported because
they exist, not because they are usable from here.

## Testing

44 tests, and most assert a negative, because the failure this component exists to prevent is a
cheerful one. The mingw target is asserted **not** buildable and the missing compiler asserted
**named**; a false `buildable` is asserted to always carry a non-empty `blocked_by`, and the set
of names in it asserted equal to the set of unmet preconditions; the darwin verdict is asserted
to follow the probe rather than the SDK read; every layer is asserted to be one of ACQUIRED or
PRESENT with both classes actually occurring; every ACQUIRED record's commit is re-read from the
checkout with git and compared to what the record reported; every `portability()` finding is
re-read from its file to confirm the line really contains what was reported.

**Every one was shown red against the defect it claims to catch before it was accepted.** Eight
mutations were applied and reverted: forcing `buildable` true, forcing the darwin probe to pass,
forcing every layer PRESENT, forcing `matches_pin` true, inventing the checkout's commit from
the pin instead of reading it, emptying the detector's program set, restoring the relative-suffix
self-exclusion, and removing the loopback branch from the credential check. Each turned exactly
the tests that name it red, and the suite returned to green when it was reverted. The
`endpoints-current` gate was checked the same way — a public callable with no route was added,
the gate returned 1 and named it, and the callable was removed.

    python3 -m pytest tests/ -q

## Releases

Tagged `symoncross/v<version>`.

## Status

**Built and tested; not running.** No process listens on 8827 — this unit has not been started,
registered on the board, or wired into the fabric. `SYM_CROSS_TOKEN` is unprovisioned, which on
a loopback bind is the correct state and requires nothing: there is no credential on loopback by
design. Provisioning is only needed if the bind is ever moved off loopback.

## Where this leads

The `portability()` output is the input to any work on making these components run elsewhere,
and it points at the components that own those call sites: `symonkernel`, `symondriver`,
`workflow`, `symonbuild`, `skills`, `board`, `symonscope`, `symonimage` and `symonprobe`, each
documented in its own directory beside this one. The acquisition question raised by
`meta-mingw` leads to `/mnt/SymonSaySource`, where a pin would have to be recorded first.

The flow ends here for this branch. This component reports and does not act: it names what is
missing and stops, because acquiring a layer, installing a toolchain and editing another
component's call sites are each somebody's decision, not a consequence of having measured them.

## Adjacent, named and not built

- A census that reads programs invoked through a computed name, closing the known gap above.
- Acquiring `meta-mingw` into `/mnt/SymonSaySource` with a pin.
- Reconciling the thirteen drifted layers: either the pins are stale or the checkouts moved, and
  which one is wrong is a decision about what the estate builds from, not a measurement.
- Registering the darwin SDK with the toolchain, and pairing it with a compiler that can read
  it — a toolchain acquisition question, not a code change.
- Repairing the 44 call sites `portability()` found. Each belongs to the component that owns it.

## One wording question, recorded not decided

`windows` is this component's own API key, renamed from `windows-mingw` on Garrett's ruling of
2026-09-19: a target key names a PLATFORM FAMILY, and the toolchain that would serve it is
metadata beside it (`TARGET_TOOLCHAIN`) rather than baked into the public identifier. A key
that names one toolchain has to be renamed the day a second one can serve the same platform.
`windows-mingw` is accepted on input as a deprecated alias and never returned.
Rules section 3.11 pre-clears a target triple
and a layer name as technical identifiers that stay byte-exact, and `x86_64-w64-mingw32` and
`meta-mingw` are both covered by that. The route key is neither: it is a name this component
chose. It is used here because it was specified, it names the platform family exactly as every
toolchain triple does, and it sits beside `darwin` and `linux-native`, which are the same kind
of name. Recorded for Garrett rather than changed unasked.
