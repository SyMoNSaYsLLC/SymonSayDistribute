# workflow — the machinery every runtime branch releases through

This branch holds no runtime. It holds the steps between a commit on a runtime branch and a
release anyone can install, and it lives on its own branch for the same reason the runtimes
do: it changes on its own schedule, and a fix to the gate should not need a runtime release
to reach the other runtimes.

## Interfaces

| Direction | What |
|---|---|
| Reads | a staging directory laid out as `<unit>/<arch>/<file>`, and the runtime branch it is run from |
| Writes | `SHA256SUMS`, `RELEASE-NOTES.md`, `SHIP-GATE-REPORT.json` into that stage; a tag and a release on this repository |
| Refuses | to publish when the gate fails, when the branch does not match the runtime, or when two assets share a basename |

## The steps, in the order they run

| Script | What it does | Refuses when |
|---|---|---|
| `pack-release-trees.sh` | collapses each multi-file `<unit>/<arch>/` tree into one reproducible archive | — |
| `build-wheel.py` | builds a pure-Python package into a reproducible wheel | the project has compiled parts or dynamic metadata |
| `ship-gate.py` | classifies every component's licence; looks for secrets by content and by path, weights, trademarks, known vulnerabilities, August-dated material and leaked identifiers | any FAIL |
| `third-party-notices.py` | writes `THIRD-PARTY-NOTICES.md` from the gate's own census | — |
| `release-notes.py` | writes `RELEASE-NOTES.md` from the gate report and the build records | — |
| `cut-release.sh` | tags `<runtime>/v<version>` and publishes | the branch is not the runtime, the tree is dirty, the gate fails, or two assets collide |
| `install-from-release.sh` | installs a runtime's latest release, verifying every asset first | a checksum does not match |
| `lay-out-on-disk.sh` | lays a repository out as one directory per branch | — |
| `verify-3p-path.sh` | exercises a live deployment end to end | any check fails |

## Why each refusal exists

Every one of them is a failure that already happened.

**Asset name collisions.** `gh release create file#text` sets an asset's label, not its name.
A rename attempted there is silently ignored, and three assets once published under names the
installer did not match — discovered only after the tag was immutable. The cutter now checks
basenames before publishing anything.

**Archives rather than loose files.** The cutter uploads every file in the stage as its own
asset, which for a directory tree means dozens of assets, name collisions between units that
each ship a `LICENSE`, and dropped symbolic links: an enumeration of files does not see them,
so a library's soname chain would not ship and it would be unloadable by name.

**Census inside archives.** Packing a unit into one archive once turned its dependency
closure into "unestablished", because the gate only opened an archive that contained a node
package. The gate opens the artifact it is actually shipping.

**A wheel builder of our own.** The backend that built the first wheels is installed in no
environment here and cannot be fetched, so a change could be committed and not shipped. The
options were to publish wheels that no longer matched their source, or to build them
ourselves; this is the latter, narrow enough to read in one sitting.


## start-estate — bringing the estate back after a reboot

    workflow/start-estate.sh [--dry-run]

The host rebooted on 2026-09-19 at 08:05 and every service was gone: eleven units, the gateway
and the engine. Nothing brought them back, because nothing ever had — each had been started by
hand in a terminal and inherited that terminal's lifetime.

The second half of that failure is the instructive one. `/tmp` is tmpfs on this host, so the
same reboot destroyed the only copies of the image unit's binaries. They survived because they
had been copied to durable storage hours earlier for an unrelated reason. Nothing about "start
it by hand" survives a power cut, and the estate had no answer to one.

**Ports come from `/models/control.board`**, not from a list in this script. That file has been
called the port authority in five documents; the fabric reads it and so does this. A port
changed there changes here.

**Four units are skipped, each with its reason printed** — the engine (its launcher owns the
fit ladder), the gateway (served from a divergent tree), the web interface (not a python
service) and the control plane (R14). A name missing from a launcher with no reason is
indistinguishable from an oversight, so the reasons are output rather than comments.

**`setsid`, not just `nohup`.** A background job still shares the session and dies when the
terminal closes. That is exactly how these died the first time.

## Releases

A release belongs to a runtime and its tag names one:

Every branch of this repository is a directory on disk, laid out by `lay-out-on-disk.sh`, so
the machinery sits beside the runtimes without ever being committed into one:

```
~/SymonSayDistribute/
    main/                 the index
    workflow/             this branch — the machinery
    symoneural-learn/     a runtime
```

A release is cut from the runtime's directory, naming the machinery beside it:

```sh
cd ~/SymonSayDistribute/symoneural-learn
../workflow/cut-release.sh symoneural-learn 1.4.0 ~/symoneural-release/v1.4.0 --dry-run
../workflow/cut-release.sh symoneural-learn 1.4.0 ~/symoneural-release/v1.4.0
```

The cutter takes the runtime from the directory it is run in, not from where it lives: the
machinery is shared by every runtime, so its own path says nothing about which one is being
released.

Installing resolves a runtime to its own latest release rather than the repository's, because
"latest" across runtimes means whichever one shipped most recently, which is never what the
caller meant:

```sh
workflow/install-from-release.sh --runtime symoneural-learn
```

## Onward

The index of runtimes and branches is on `main`. Each runtime branch carries its own
documentation; this branch describes only how one gets released.

**The chain ends here, and §3.7 asks why.** This worktree has no directories below it —
every file above is a script at the branch root — so there is no document underneath this
one to link to. The onward step is not a directory at all: it is another *branch*, checked
out as its own worktree beside this one, with its own root document. `main` holds the index
of those. A branch boundary is where the filesystem chain stops, because a worktree's
documents are laid out per branch (§3.1a) and nothing under `/mnt/SymonSayDistribute/workflow`
can name a path inside `/mnt/SymonSayDistribute/main` that survives the layout being
recreated on another host.
