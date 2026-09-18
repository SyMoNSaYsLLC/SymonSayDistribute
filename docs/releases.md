# Releases

How a release is staged, gated and cut; how assets are named; what a release note must
contain; how an operator installs one. A release is a commit: the tag, the assets and the
notes all name the same HEAD.

## Contents

- [The stage](#the-stage)
- [The gate](#the-gate)
- [Cutting](#cutting)
- [Asset names](#asset-names)
- [What a release note contains](#what-a-release-note-contains)
- [Installing a release](#installing-a-release)
- [Versioning](#versioning)

## The stage

Artifacts are built out-of-tree from `git archive` exports of the tagged commit and staged as
`<stage>/<unit>/<arch>/<files>`, `arch` ∈ `noarch`, `x86_64`, `aarch64`, `armv7`, `i686`. Each
unit carries a `BUILD-RECORD.md` — source commit, exact commands, timings, hashes, what was and
was not exercised — and a per-arch `SHA256SUMS`. Pure-Python wheels are built **twice** from two
separate exports with `SOURCE_DATE_EPOCH` and must hash identically; a unit that is not
byte-reproducible says so in its record.

Units in a release, and what they are: `symoneural-gateway` (wheel), `symoneural-api` and
`symoneural-llm` (wheels), `symoneural-learn-hostrun` (scripts), `symoneural-api-native` (C
library, per arch), `symoneural-image-cuda` (the image worker with the CUDA backend, x86_64),
`symoneural-chat-engine` (the engine, x86_64 CUDA), `symoneural-llm-native` (the estate's own
inference library with the CUDA backend module), the web source tarball, the product source
tarball.

## The gate

`tools/ship-gate.py --stage <stage> --repo .` re-derives every census from the artifacts and
the repository history and exits 1 on any FAIL. Classes: strong, network, weak (file/library),
use-restricted, proprietary third-party, unknown; attribution present; secrets by content and
path (inside archives, across all history blobs); weights in artifacts; third-party marks in
artifact names; known vulnerabilities; August-2026 inputs. Recorded exceptions (for example the
CUDA runtime libraries the operator provides) live in `tools/ship-gate-policy.json` with who
ruled them.

## Cutting

```sh
tools/cut-release.sh v1.0.0 ~/symoneural-release/v1.0.0 --dry-run   # prints the gh command
tools/cut-release.sh v1.0.0 ~/symoneural-release/v1.0.0             # tags HEAD, uploads, publishes
```

It refuses (with a documented exit code) when the tag does not equal HEAD, the tree is dirty,
`SHA256SUMS` does not verify, the gate fails, an asset sits under an unknown arch directory, or
the release already exists — releases are immutable; bump the tag.

## Asset names

`<unit>-<version>-noarch.<ext>` or `<unit>-<version>-linux-<arch>.<ext>`; wheels keep their own
tag (`py3-none-any` already states the architecture). `SHA256SUMS`, `THIRD-PARTY-NOTICES.md` and
`SHIP-GATE-REPORT.json` are attached to every release.

## What a release note contains

1. The licence line and licensor contacts.
2. Source commits: product and estate HEAD shas.
3. **The truth table**: units × architectures — SHIPPED (hash prefix), BUILT-UNVERIFIED,
   NOT BUILT (reason), N/A. Only what an independent check confirmed is SHIPPED.
4. What is not in the release and why (weights; the engine behind `/v1` if it is still a
   recorded substitution; anything that failed the gate; arches without a toolchain).
5. Install commands per shipped unit, with the assumption stated for the chat unit.
6. The measured numbers from `tools/bench-gateway.sh`, naming the engine that produced them.
7. Reproducibility: what was rebuilt twice and matched, and what is not byte-reproducible.

## Installing a release

```sh
tools/install-from-release.sh --dry-run            # the plan for this machine
tools/install-from-release.sh --release v1.0.0     # verified against SHA256SUMS first
```

See [Getting started](getting_started.md#install-from-a-release).

## Versioning

`vMAJOR.MINOR.PATCH`. The recipes' `PV` and the wheels' versions agree with the tag. The first
release is `v1.0.0`; it goes out only when its stage passes the gate, and its note says exactly
which units and architectures are in it.
