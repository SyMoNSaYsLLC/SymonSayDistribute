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

## Releases

A release belongs to a runtime and its tag names one:

This branch is checked out as a worktree inside the runtime being released, so the machinery
sits beside the source without ever being committed to it:

```sh
git clone --branch symoneural-learn <repo> && cd symoneural-learn
git worktree add workflow workflow      # this branch, as a directory
workflow/cut-release.sh symoneural-learn 1.4.0 ~/symoneural-release/v1.4.0 --dry-run
workflow/cut-release.sh symoneural-learn 1.4.0 ~/symoneural-release/v1.4.0
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
