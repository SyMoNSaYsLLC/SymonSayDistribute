# symonsdk

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

The answer to "what can be built on this machine, with what, and is it actually usable" —
measured, on request, so that symon can help customise and build with the toolchains that are
here instead of guessing at them.

This page describes what is **built and tested**: 24 tests pass, and every figure quoted below
was produced by this code reading this disk. It is not yet running as a service — see
**Status** at the end.

## The distinction the whole unit is built on

**Installed and usable are different, and only one of them builds anything.**

A name on PATH proves a directory entry exists. It does not prove the program runs, that its
headers are installed, or that the interpreter a virtualenv points at still exists. So nothing
here is read from a table or recalled. Every answer carries its evidence: the resolved path,
the argument vector, the exit code it returned, and what it printed. `usable` is derived from
that exit code and from nothing else.

That is not a stylistic preference. It is what makes the failures below detectable at all —
and two of them were found by this code, in this branch, before it was finished.

## The version probe is per tool

`go --version` exits 2:

    flag provided but not defined: -version

The correct form is `go version`. A probe that assumes `--version` reports a present, working
toolchain as broken — which is exactly the class of mistake this unit exists to catch, so the
argument vector lives in the registry beside each tool rather than being assumed:

    "go":   (("version",),  ...)      # `--version` exits 2
    "java": (("-version",), ...)      # one dash, and it writes to stderr

`java` is the second case and needs no special handling beyond capturing both streams, which
the probe does for every tool.

`go` is additionally given `GOTOOLCHAIN=local`, and every probe runs with cwd `/`. Nothing in
this unit is allowed to download, and `auto` lets the go command fetch a different toolchain
when it is run inside a project directory that asks for one.

## A shim is invoked by the name that was looked for

**Found by this code, and fixed before it shipped.** The first implementation resolved each
tool's symlink with `realpath` before running it. Two things then went wrong at once, because
a shim decides which tool it is from `argv[0]`:

| Tool | What it reported with the link resolved | What it reports now |
|---|---|---|
| `rustc` | `rustup 1.29.0` — the installer's version, not the compiler's | `rustc 1.97.1 (8bab26f4f 2026-07-14)` |
| `cargo` | `rustup 1.29.0` | `cargo 1.97.1 (c980f4866 2026-06-30)` |
| `swift` | **unusable** — the driver behind it fails under the wrong name | `Swift version 6.0.3 (swift-6.0.3-RELEASE)` |
| `swiftc` | **unusable** | `Swift version 6.0.3 (swift-6.0.3-RELEASE)` |

Two wrong versions and two working toolchains reported broken. The unit now invokes the path
that was resolved — the one a build would actually invoke — and reports the link target
separately, as evidence, in `real_path`. A test pins this: `rustc` must report a version
beginning with `rustc`, and every on-PATH tool's `argv[0]` must equal what `which` returned.

## What a "no" has to say

`can_build` is the route symon will actually use, and it names **every precondition
separately** — compiler, build tool, package manager, headers, SDK tree — so that a refusal is
actionable. Not "node is unavailable", but:

    can_build node   False   cannot build node: missing npm
      runtime          node   met    v24.19.0 at /usr/local/bin/node
      package manager  npm    NOT    absent: 'npm' is on no PATH entry

A runtime that is present and a package manager that is absent are a different problem with a
different fix, and a caller told only "no" would have to go and find that out for itself.

## Routes

    GET /api/symonsdk/health      public; answers before the unit is configured
    GET /api/symonsdk/toolchains  every known toolchain, versioned by RUNNING it
    GET /api/symonsdk/venvs       every virtualenv, and whether its interpreter still runs
    GET /api/symonsdk/sdks        the non-python SDK trees: present, size, versions on disk
    GET /api/symonsdk/sources     source trees to build from, with git status and manifest
    GET /api/symonsdk/pinned      every usable toolchain against the pin SymonSaySource records
    GET /api/symonsdk/can-build   ?ecosystem=<name> — yes, or which part is missing

Health is public; the rest need `SYM_SDK_TOKEN` **only off loopback**, and an unset token then
closes the unit. On a loopback bind there is no token at all: a key defends against a caller
who already has code execution on this host, and such a caller can read the key. The bind
address decides that at runtime, not a convention in prose (rules §3.2a).

An unknown ecosystem is a `400` carrying the list of names this host does know, because a
caller that guessed wrong needs the vocabulary, not a refusal.

`NOT_EXPOSED` is declared and **empty**: all six capabilities carry a route. It is declared
rather than omitted so the question `endpoints-current` asks is answered rather than unasked.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `SYM_SDK_HOST` | `127.0.0.1` | bind address, and the thing that decides whether a token is required |
| `SYM_SDK_PORT` | `8826` | bind port |
| `SYM_SDK_TOKEN` | unset | required off loopback; unset off loopback is a `503` |
| `SYM_VENV_ROOT` | `~/.venvs` | where `venvs()` looks |

No other variable is read. The source roots (`~/src`, `~/Desktop`) are in the module, not in
the environment, so this unit adds nothing to the configuration contract beyond the four above.

## What it found on this host, 2026-09-19

Measured by this code, not recalled. 23 toolchains known, 21 usable.

**Usable:** `cargo` 1.97.1 · `cc` 14.2.0 · `cmake` 3.31.6 · `dotnet` 10.0.302 · `g++` 14.2.0 ·
`gcc` 14.2.0 · `git` 2.47.3 · `go` 1.24.4 · `java` 21.0.12.1 · `javac` 21.0.12.1 · `make` 4.4.1 ·
`ninja` 1.13.0 · `node` 24.19.0 · `perl` 5.40.1 · `pip3` 25.1.1 · `pkg-config` 1.8.1 ·
`python3` 3.13.5 · `ruby` 3.3.8 · `rustc` 1.97.1 · `swift` 6.0.3 · `swiftc` 6.0.3

**Absent:** `npm`, `php`.

**Present but not on PATH:** `dotnet`. It runs, at `/home/google/.dotnet/dotnet`, and anything
invoking it by name will not find it. That is reported as its own state — `off_path` — rather
than flattened into either "installed" or "absent", because it is neither.

**SDK trees:** `dotnet` 1.1G offering `10.0.302`, `9.0.100` · `swift` 2.9G offering
`darwin.artifactbundle` · `rust` 3.4G (`~/.cargo` and `~/.rustup`) offering
`stable-x86_64-unknown-linux-gnu` · `go` 1.7G holding three fetched toolchains ·
`nuget` present and **empty**: `~/.nuget/packages` holds nothing, so the tree offers nothing to
build with. A tree that is present and useless is the same shape of finding as a tool that is
present and broken, and it is said rather than implied by a size.

**Virtualenvs:** five under `~/.venvs`, all five usable — `coreml` (3.13.5, 136 distributions),
`symoneural` (3.13.5, 34), `symoneural-hybrid` (3.12.13, 130), `vllm` (3.12.13, 432),
`vllm-0271-cu130` (3.12.13, 394). Distribution counts come from **directory names only**;
nothing inside a virtualenv is opened, because some of them hold credentials.

**Source trees:** `~/src/quickshell` (git, `CMakeLists.txt`) ·
`~/Desktop/aistore-1.5.0` (not git, `go.mod` and `Makefile`) ·
`~/Desktop/antigravity-sdk-python-main` (not git, `pyproject.toml`).

A directory counts as a source tree when it carries a **build manifest**, not merely a `.git`.
Every stakeholder folder on this Desktop is a git repository, and reporting those as things to
build from would bury the three that are.

**Buildable now:** `c`, `c++`, `cmake`, `go`, `java`, `python`, `ruby`, `rust`, `swift`.
**Not:** `node` (missing `npm`), `dotnet` (missing `dotnet` on PATH), `php` (missing `php`).

## Toolchains against their pins (§3.1b-iii)

`pinned()` and `GET /api/symonsdk/pinned` already do what §3.1b-iii asks: every toolchain this
unit runs is compared to the pin `SymonSaySource` records for it, and four tests cover the
classifier — including one that injects a fake pin and requires `DRIFTED` to come back naming
both versions.

**This unit was counted as having nothing on 2026-09-20, and that count was wrong.** The
measurement grepped for files containing the literal string `pins/`. This code never contains
it: `PIN_ROOT` is `/mnt/SymonSaySource` and the registry is found with `rglob("*.json")`
filtered on `"pin" in path`. A grep artifact, not a gap — recorded here because a false zero in
a compliance count is worse than a true one, and somebody will run that grep again.

Live state, read from this code on 2026-09-20: **108 pins available, 21 usable toolchains
checked, 0 MATCHES.**

| State | Toolchains |
|---|---|
| `DRIFTED`, recorded | `ninja` (pin 1.13.2, host 1.13.0) |
| `UNRESOLVED-PIN` | `node` (pin records `UNRESOLVED`, host 24.19.0) |
| `UNRECORDED` | cargo, cc, cmake, dotnet, g++, gcc, git, go, java, javac, make, perl, pip3, pkg-config, python3, ruby, rustc, swift, swiftc — **19 of 21** |

**The gap this unit still has, named and not closed here.** Nineteen of the twenty-one build
tools that work on this host have no pin in `SymonSaySource`, so nineteen of them can move
underneath the estate with nothing to notice. `pinned()` reports each as `UNRECORDED`, which is
the honest answer, but reporting a gap is not closing it — closing it is nineteen pins, and a
pin is a provenance record (upstream, full SHA, declared licence with its checksum, acquisition
date), not something a test can invent.

**Drift is now recorded, so a new movement fails.** Until 2026-09-20 none of the tests went red
on the estate's *real* state — they exercised the classifier against injected pins, and the live
`DRIFTED` row for `ninja` was asserted by nothing. `pinned()` now carries the same `KNOWN_DRIFT`
table `board`, `symonengine` and `symonprobe` use: today's disagreement recorded with its date,
so that tomorrow's *new* movement fails.

The assertion is `new_drift == []`, not "no drift". Demanding zero drift would demand the rule
be broken — pin/checkout drift is preserved, never reconciled, and no pin was edited nor any
host moved. What must hold is that every movement has been looked at.

A green result there would prove nothing on its own, so a partner test removes the `ninja` entry
and requires the same host to come back naming `ninja` with both versions in the reason.

**`node` is no longer counted as drift.** Its pin file exists but records no version, so nothing
was compared; calling that "drifted" claimed knowledge this unit does not have. It now appears
in `unresolved`, and a test asserts the two lists never overlap.

    matched []  ·  drifted ['ninja']  ·  recorded_drift ['ninja']  ·  new_drift []
    unresolved ['node']  ·  unrecorded 19

## Placement

    placement-triage prospect symonsdk --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

**This unit is built from the python standard library (PSF-2.0) and fastapi (MIT).** That is
the whole list, and it is what decides the licence (§3.1b-i: name the sources, then read the
licence off them). Proprietary is the default and nothing forced it off.

**What it inspects does not place it.** This unit runs `gcc --version` and `go version` and
reads the directory names under `~/.rustup/toolchains`. Some of those toolchains are copyleft.
That does not reach this artifact, and the reasoning is §3.1b-i's distinction between placing
by consequence and placing by tidiness:

- A component belongs in the open tree when its **output** is copyleft and would reach a
  shipped artifact. Linking a copyleft library does that.
- **Building with — or merely running, or merely naming — a copyleft tool does not.** Every
  toolchain here is reached across an `exec` boundary, as a program invoked with an argument
  vector, and what comes back is a version string and an exit code. Nothing is linked, nothing
  is imported, and no code from any of them enters this artifact.
- Placing this in the open tree because the word "GPL" appears somewhere in what it reports
  would be placement by resemblance. A tree that collects components for resembling each other
  stops meaning anything, and the one question it is supposed to answer — can this ship — stops
  having an answer.

The same reasoning the ship gate spells `INVOKED_NOT_LINKED`.

## Testing

28 tests, and the ones that matter are paired: each asserts the right answer, and its partner
asserts that the wrong implementation would have produced a different one. A test that passes
whether or not the code is right has gated nothing.

- **The `go` probe.** It asserts `go` comes back present, usable and versioned — *and* first
  asserts that `go --version` still exits non-zero on this host, so that if the trap ever
  disappears the test says so instead of passing quietly. Its partner wires `--version` in
  deliberately and requires the same working toolchain to be reported **unusable**, which is
  what proves `usable` is derived from the exit code rather than from resolution.
- **A virtualenv whose interpreter is gone.** Two fake virtualenvs are built under `tmp_path` —
  never in `~/.venvs` — one pointing at the running interpreter and one at a deleted path. The
  broken one must come back `usable: false` naming the missing interpreter and its link target;
  the good one must come back usable, or the test proves only that the function says no to
  everything.
- **`can_build` names what is missing.** With `PATH` emptied, `rust` must come back false with
  `rustc` and `cargo` named individually; with the real `PATH`, something on this host must
  build, or "cannot build" means only that the function always refuses.
- **The shim regression**, both halves, as described above.
- Loopback needs no token; off loopback with no token is `503`; and — so that the first of
  those means something — off loopback with a token set, a wrong token is `401` and the right
  one is `200`.
- Every probe is bounded: `_run` is given a 0.2s timeout against a 5s sleep and must come back
  with no exit code and "timed out".

<!-- -->

    python3 -m pytest tests/ -q

## Releases

Tagged `symonsdk/v<version>`.

## Status

**Built and tested; never started as a process.** Its 28 tests pass and every figure in *What
it found on this host* came out of this code on 2026-09-19. Each line below was probed, not
recalled:

| Claim | How it was checked | Result |
|---|---|---|
| nothing is serving this unit | `ss -ltn` for 8826 | no listener |
| 8826 is this unit's to take | every `SYM_*_PORT` default across the tree's `service.py` files | claimed by no other branch |
| the fabric already expects it | `wiring.py:68` on `adaptive-fabric` | `{"prefix": "/api/symonsdk", "token_env": "SYM_SDK_TOKEN"}` — already there, and it matches this unit's prefix and variable exactly |
| the board does not name it | grep of the `board` branch | absent; `/models/control.board` does not exist on this host either |

So the surface is wired in the fabric's table and has nothing behind it yet. Starting it and
naming it on the board is the step that changes that, and it is not taken here.

Adjacent and deliberately not built here: registering the unit on the board and starting it
under supervision; a route for a single named toolchain; a per-directory document for
`symonsdk/` and `tests/` under §3.7, which no component on this tree currently carries.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonsdk`](symonsdk/symonsdk.md) | the capability this unit provides — `toolchains.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where the flow ends

Two chains meet in this heading and they end in different places, so both are said.

**The document chain does not end here.** Inside this branch it goes on into
[`symonsdk`](symonsdk/symonsdk.md), the capability, and then
[`tests`](tests/tests.md), what proves it — in that order, because that is the order the code
runs. Those two documents are the last in the branch.

**The component chain does end here.** It ends here, and that is the whole chain. This branch is one component: the capability
(`symonsdk/toolchains.py`), the surface over it (`service.py`), and its tests. Nothing in this
branch hands off to another document, because nothing in this branch calls another component —
every answer it gives is read from this host directly, on purpose. `symonsdk` deliberately does
not ask another service for any of it: a report on what is usable that needs a second service to
be up would go dark exactly when the estate is degraded and somebody needs to know what still
builds.
