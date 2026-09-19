# symonbuild

The estate's build capability, reported. Never exercised.

This page describes what is **built and tested**: 22 tests pass, and every figure below was
produced by this code reading this host on 2026-09-19. It is not yet running as a service — see
**Status** at the end.

## Why this exists

The estate is founded on the OpenEmbedded layering system, and **nothing owned it**. Where the
task executor lives, which copy the pins name, what the build configurations declare, whether
the layers they name exist, and whether a build could start at all were five questions with no
answer on disk and several different answers in documents.

So this component answers them by reading, every time it is asked. Each function returns its
evidence beside its answer: the paths read, the argument vector run, the exit code.

## It never starts a build

R2 forbids editing a recipe while a cooker is live. Anything about to edit one has to be able to
ask, at that moment, and get an answer read from the process table rather than remembered.

A component that could also launch a cooker could not be trusted to answer that question — it
would be a possible cause of the thing it reports on. So there is no code path here that invokes
the executor or sources a build environment, and a test proves it structurally: it parses this
module and asserts that every argument vector it could ever run begins with `df` or `git`, that
every subprocess call carries a timeout, and that none carries a shell.

## What is on disk: the task executor

`bitbakes()` on 2026-09-19:

    8 copies at 2 versions (2.19.1, 2.8.1) across 2 devices

    version  device      placement          revision      pin  path
    2.19.1   sda1        acquired-upstream  —                  …/Projects/SymonSayLearn/upstream/build/bitbake/bitbake/bin/bitbake
    2.19.1   sda1        sandbox            046a90b0e9b7  PIN  …/Projects/symoneural-bootstrap-master/bitbake/bin/bitbake
    2.8.1    sda1        sandbox            0880963fea4d       …/Projects/symoneural-devtool-bootstrap/bitbake/bin/bitbake
    2.19.1   sda1        sandbox            —                  …/Projects/symoneural-runtime-acquisition-github-769b4f3ae/Symoneural-Build/src/bitbake/source/bin/bitbake
    2.19.1   sda1        acquired-upstream  —                  …/Projects/symonsaylearn/upstream/build/bitbake/bitbake/bin/bitbake
    2.8.1    sda1        sandbox            cff3be6f664f       …/Projects/yocto/bitbake/bin/bitbake
    2.19.1   nvme0n1p3   sandbox            —                  …/symoneural-staging/symoneural-runtime-acquisition-github-769b4f3ae/Symoneural-Build/src/bitbake/source/bin/bitbake
    2.19.1   nvme0n1p3   acquired-upstream  —                  …/symonsaylearn/upstream/build/bitbake/bitbake/bin/bitbake

**Nothing is on PATH.** `shutil.which("bitbake")` returns `None`.

**The spread is the finding, not the list.** This is the shape that produced the
`no-divergent-copy` gate: the release gate existed at four paths, three of them stale, and
nothing reported it because each copy was individually fine.

**But the estate does have a recorded answer, and it is not "pick one".**
`/mnt/SymonSaySource/build/pins/bitbake.json` records `intended_revision`
`046a90b0e9b7b914b7a95aec579cdc3fc9c7617a`. Exactly one copy is at that revision, and it is
`symoneural-bootstrap-master`. Three copies are at revisions of their own; five are vendored
inside another repository and therefore have no revision of their own to compare. The pin is
what makes one of them canonical — version alone cannot, because two copies share a version and
not a commit.

The version is **read out of each file**, from its `__version__` assignment. A test re-reads
every reported file independently and fails if the two disagree, so a version inferred from a
directory name or carried forward from a note is a test failure rather than a surprise.

The revision is read with `git rev-parse --show-toplevel HEAD`, and reported **only when the
tree is itself the repository**. `git -C` walks up to the nearest repository, so a vendored tree
otherwise answers with its host's commit — somebody else's revision wearing this tree's name,
which would be compared against a pin and mean nothing.

## What is on disk: the rest of the tooling

`devtools()` — all four present, none on PATH:

    devtool            found  10 copies
    bitbake-layers     found   8 copies
    oe-init-build-env  found   8 copies
    recipetool         found  10 copies

Every tool in the set appears in the report whether or not it was found. A report that lists
only what it found reads identically to a report that found everything, which is how a missing
tool survives three status updates.

## What is on disk: the configurations

`configs()` — **12 configurations, 0 usable, 8 with a layer that does not exist.**

The sharpest case, because it is the most recent and it names the copy the pin makes canonical:

    /home/google/symonsaylearn/work/output/learn/build/devtool-master/conf/bblayers.conf
      -> /home/google/symoneural-bootstrap-master/openembedded-core/meta        : no such directory
      -> /home/google/symoneural-bootstrap-master/meta-openembedded/meta-oe      : no such directory
      -> /home/google/symoneural-bootstrap-master/meta-openembedded/meta-python  : no such directory
      -> ${SYMON_REPO}/work/recipes                                              : unresolved

Those three layers exist — at
`/home/google/SymonSaysLLC/Projects/symoneural-bootstrap-master/...`. The configuration names
them without the `SymonSaysLLC/Projects/` element, and `/home/google/symoneural-bootstrap-master`
does not exist at all. So the estate's newest build directory points at the right tree by the
wrong path, which is a repair, not an acquisition.

The oldest case, and the one the estate keeps four copies of:

    /home/google/symoneural-staging/yocto/build-audit/conf/bblayers.conf
      BBLAYERS ?= " /yocto/openembedded-core/meta "
      -> /yocto/openembedded-core/meta : no such directory

`/yocto` exists, is owned by root, is dated 25 August 2026, and is **empty**. It is a directory <!-- gate-allow: no-august — a measured mtime read off disk, quoted as a finding, not material built from -->
on `/dev/nvme0n1p2`, not a mount of its own. The build configuration points at a layer path that
is not there, so no build can run from it. The same declaration appears in three other
`build-audit` copies, and the eleven-layer `build-symoneural` configurations name eleven paths
under `/yocto`, none of which exist.

An entry still holding a variable reference — `${TOPDIR}/sources/meta-oe` in the four
`Antminer_firmware` configurations, `${SYMON_REPO}/work/recipes` above — is reported `exists: null`, not `false`. Expanding it needs
the executor, which is the thing being reported on. Recording an unread entry as a measured
absence would put it beside the `/yocto` finding under the same word and stop the real one
standing out.

## What is on disk: the layers

`layers()` — 93 layers declaring `conf/layer.conf`; 32 **ACQUIRED**, 61 **PRESENT**.

ACQUIRED is **component-level, not copy-level**: a pin exists in `/mnt/SymonSaySource` for the
component this layer belongs to. It does not say that *this copy* is at the pinned revision, and
on this host it usually is not — every copy of `meta-openembedded` on disk reports ACQUIRED while
the trees are at different commits. The executor gets the stronger test (`matches_pin`, revision
against revision) because the pin for it was the question being asked; extending that to each
layer is adjacent work and is not done here.

PRESENT means the layer is merely here — staging, a cache, the sandbox. That is not a criticism,
and it is not a provenance either. The estate's own `meta-symoneural` and `meta-symoneural-bsp`
are PRESENT: they declare their names and carry no pin. So are the fifteen layers under the
`work/` portals, which hold first-party recipes.

## Is a cooker live

`cooker_live()` iterates `/proc`, reads each `cmdline`, and matches on the **executable** — the
basename of the resolved `exe`, of `argv[0]`, or of `argv[1]` behind an interpreter — against
`bitbake`, `bitbake-server`, `bitbake-worker`, `bitbake-hashserv`, `bitbake-prserv` and
`bitbake-cookerdaemon`. This process and every ancestor of it are excluded by pid before any
matching happens.

Rules §3.3 forbids the two pattern-matching process utilities outright, because their pattern
matches the agent's own command line and has ended sessions on this host. That is not an
abstract hazard for this module in particular: a substring probe written while developing this
file returned exactly one hit, and the hit was the shell running the probe, because the probe's
own text contained the word it was searching for.

So the matcher was tested in both directions, and neither direction needed a build started. A
live decoy — `bash -c 'marker=bitbake-worker-oe-init-build-env; sleep 25; …'`, whose command
line literally contains the executor's name — is reported as **not** a cooker. Two real
invocation shapes, `…/bin/bitbake -c build …` and `python3 …/bin/bitbake-worker`, are both
matched.

On this host, right now: no cooker is running; 483 process entries were examined on the run
quoted here.

## Could a build run

`buildable()` — **no**, `blocked_by: ["config_with_every_layer_present"]`.

    MET  bitbake_on_path_or_resolvable     nothing on PATH, but the pin names one copy of eight
    NOT  config_with_every_layer_present   12 configurations, 0 with every declared layer on disk
    MET  build_directory                   12 conf directories hold both bblayers.conf and local.conf
    MET  oe_tooling                        devtool, bitbake-layers, oe-init-build-env, recipetool all present

A false answer always carries a non-empty `blocked_by`; a test asserts that, and a second test
points the search at an empty directory and requires every precondition to fail — so a green
result cannot mean "the check does not work".

Whether a cooker already holds a build directory is a separate question and is answered by
`cooker_live()`, not folded in here.

## Where it looks

`SYM_BUILD_ROOTS`, an `os.pathsep`-separated list, overrides the search roots in full. The
default is the five sanctioned locations under `/mnt` plus three sandbox roots derived from `~`,
so no single operator's home is the only place this can look. `SYM_BUILD_DEPTH` (default 6)
caps the descent, and history, caches, build output and vendored dependency trees are pruned:
an unbounded walk of the sandbox took longer than a test is allowed to take, and a capability
report nobody waits for is a capability report nobody reads. A full pass takes about 1.9 s.

**`work` is deliberately NOT pruned.** The executor's own work directory is `tmp/work`, which
`tmp` already covers, so pruning the name buys nothing there — while in this estate `work/` is a
portal holding first-party recipes. Pruning it hid fifteen layers and the live build directory
quoted above, and the counts came back low with nothing looking wrong. `work-shared` stays
pruned: that one really is build output.

Configurations outside those roots are not reported. One is known:
`~/Downloads/sendtodrive/old-run/yocto-parse/conf`, which declares eleven layers under a
`/home/google/Symoneural` that no longer exists. Point `SYM_BUILD_ROOTS` at it to include it.

## Routes

    GET /api/symonbuild/health        public; answers before the unit is configured
    GET /api/symonbuild/bitbakes      every executor found, its version, device and pin match
    GET /api/symonbuild/devtools      the OE tooling; an absent tool is named, never omitted
    GET /api/symonbuild/configs       every configuration, and each declared layer's existence
    GET /api/symonbuild/layers        layers on disk, the name each declares, acquired or present
    GET /api/symonbuild/cooker-live   is a cooker running; R2 rests on this
    GET /api/symonbuild/buildable     per-precondition, with what is in the way

Bind is `SYM_BUILD_HOST` (default `127.0.0.1`) on `SYM_BUILD_PORT` (default 8828).

Health is public. On a loopback bind **no token is asked for**: §3.2a, a token on `127.0.0.1`
defends only against a caller who already has code execution on this host, and such a caller can
read the token. Off-loopback `SYM_BUILD_TOKEN` is required and an unset one returns 503, so a
unit that becomes reachable through a configuration change does not become public through that
same change. The bind address decides, at runtime, in `_open_on_loopback()`.

`NOT_EXPOSED` is empty: every public callable in `cooker.py` has a route.

## Placement

    placement-triage prospect symonbuild --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

Built from the Python standard library at PSF-2.0 and FastAPI at MIT. Nothing else is imported.

**Inspecting a copyleft build system does not make this component copyleft.** §3.1b-i places by
consequence, not by resemblance: a component belongs in the open tree when its *output* is
copyleft and would reach a shipped artifact. This reads files, runs `df` and `git`, and reads
`/proc`. It links nothing, imports nothing from the build system, and executes none of it. The
executor's own licence attaches to what the executor builds, not to a program that reports where
it is — the same reasoning that places the image unit, whose runtime is a program it invokes
rather than a library it links.

The two subprocesses it does run, `df` and `git`, are invoked as programs and read as data.

## Barriers

§3.8: raised, with evidence, not worked around.

**1. No OE build can run on this host today.** `buildable()` is false. The blocking precondition
is `config_with_every_layer_present`: 12 build configurations were found and **none** has every
declared layer on disk.

**2. The estate's own build configuration points at an empty directory.**
`~/symoneural-staging/yocto/build-audit/conf/bblayers.conf` declares
`BBLAYERS ?= " /yocto/openembedded-core/meta "`. `/yocto` is root-owned, dated 25 August 2026, <!-- gate-allow: no-august — a measured mtime read off disk, quoted as a finding, not material built from -->
and contains nothing. The `build-symoneural` configurations name eleven `/yocto/*` paths, all
absent. Rules §6.2 item 21 records `/yocto` as an ext4 mount of `/dev/nvme0n1p2` that must never
be removed or formatted; `findmnt -T /yocto` reports the target as `/`, so it is a directory on
that filesystem and not a mount. What was under it appears to have moved to
`~/symoneural-staging/yocto/`, which carries a `lost+found` timestamped 2026-08-25 11:08:53, <!-- gate-allow: no-august — a measured mtime read off disk, quoted as a finding, not material built from -->
fifty-six seconds before `/yocto` itself. **This is
recorded, not acted on** — nothing here moves, creates or edits a build directory, layer, recipe
or conf file.

**3. The newest build directory names the canonical executor's tree at a path that does not
exist.** `~/symonsaylearn/work/output/learn/build/devtool-master/conf/bblayers.conf` declares
three layers under `/home/google/symoneural-bootstrap-master/`. That directory does not exist;
the tree is at `/home/google/SymonSaysLLC/Projects/symoneural-bootstrap-master/`, and the three
layer directories are present there. A fourth entry, `${SYMON_REPO}/work/recipes`, is unresolved
because `SYMON_REPO` is not set in the configuration this reads. This one is a path repair
rather than an acquisition, which makes it the cheapest of the four to clear — and it is a
decision about where the tree should live, so it is recorded here and not made.

**4. The task executor is not on PATH, and it exists eight times at two versions.** Three of
those copies are at three different revisions and five are vendored inside other repositories.
Only the pin resolves it, and only one copy of the eight is at the pinned revision. Until one
copy is made canonical in fact rather than only in the pin, "which executor ran" is not
answerable after the event.

**5. Both dates and devices put the whole build stack outside the estate.** Every copy sits on
`/dev/sda1` or `/dev/nvme0n1p3` — the sandbox — and none under `/mnt`. Three of the twelve
configurations are August-dated, which §3.2 bans from use; they are flagged `august_dated` in the
report rather than silently included.

**Corrected against the brief this component was built from**, because §3.1d makes a recalled
fact an untested claim and three of the facts handed to this work did not survive being read:

- `devtool` was reported absent from this host. It is present, as a regular file, in three
  trees — `.../openembedded-core/scripts/devtool`, 15309, 15633 and 15309 bytes, mode 775 — plus
  copies in a cache. So are `bitbake-layers`, `oe-init-build-env` and `recipetool`. The tooling
  is not a barrier.
- Three executors were reported. There are eight.
- All were reported to be on `/dev/sda1`. Two are on `/dev/nvme0n1p3`.

## Testing

22 tests. The ones that matter are the ones that would pass on a tidy machine and therefore
prove nothing, written the other way round:

- **more than one version is asserted**, because the divergence is real here; a test asserting a
  single canonical copy would say the estate is tidy, and would have to fail before the mess was
  cleaned up and pass afterwards
- **every reported version is re-read from its own file** and must agree
- **a declared layer that does not exist is flagged**, against a fixture built under `tmp_path`;
  a second test requires a config whose layers all exist to come back usable, so
  `all_layers_present` cannot be hardwired false; a third requires an unexpanded entry to be
  `null` rather than `false`
- **`buildable()` is false here with a non-empty `blocked_by`**, and a negative control points
  the search at an empty directory and requires every precondition to fail
- **`cooker_live` names neither forbidden process utility**, asserted with `inspect.getsource`
  against the function and against the whole module
- **the matcher is tested both ways** — a decoy whose command line contains the executor's name
  is not a cooker; two real invocation shapes are
- **loopback needs no token; off-loopback with no token is 503**, with `SYM_BUILD_HOST` set
  before `importlib.reload`, and a wrong token off-loopback is 401
- **this module can run only `df` and `git`**, proved by parsing it rather than by grepping it

```sh
python3 -m pytest tests/ -q --color=no
```

`python3 -m` is load-bearing: it puts the worktree root on `sys.path`, which is what makes
`import service` and `from symonbuild import cooker` resolve.

## Gates

    gate endpoints-current /mnt/SymonSayDistribute/symonbuild                       rc=0
    gate no-divergent-copy /mnt/SymonSayDistribute /mnt/SymonSaySource \
                           /mnt/SymonSayOSS /mnt/SymonSayOpen                       rc=0

The capability module is `cooker.py`, not `build.py`, `probe.py` or `layers.py`: `layers.py`
already exists on `symonscope`, and the other three are names a parallel branch would reach for.
Two different jobs under one filename is what `no-divergent-copy` refuses.

## Releases

Tagged `symonbuild/v<version>`.

## Status

**Built and tested; not running and not wired.** No process is listening on 8828, this unit is
not registered on the control board, and nothing in the estate calls it yet. `SYM_BUILD_TOKEN`
is unprovisioned, which on a loopback bind is the designed state and not a gap.

## Where this leads

The flow ends here for the build capability itself, because this component deliberately stops at
reporting. What it reports leads two ways, and neither is this component's to do:

- The pins it compares against live on `/mnt/SymonSaySource/build` — `pins/bitbake.json` and
  `pins/openembedded-core.json` — and that branch's `sources.md` is where a pin moves.
- The four barriers above are decisions and file operations, not reports. Making one executor
  canonical, and pointing a build configuration at layers that exist, are the next work; this
  component's only role afterwards is that `buildable()` stops saying no.

Adjacent and deliberately not built here: anything that repairs a configuration, relocates an
executor, or starts a cooker.
