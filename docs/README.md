# Documentation

SyMoNsAyLeaRn is an inference runtime you run on your own hardware: one GPU, one host,
three loopback ports, a public wire dialect on the front. This page is the map. Every page
it links says at the top whether it describes something **running**, something **built and
staged**, or a **direction** — and nothing here is ever more finished than the thing it
describes.

- New here: read [Architecture](ARCHITECTURE.md), then [Getting started](getting_started.md).
- Using it: [HTTP API](http_api.md), [Command line](cli.md), [Configuration](../config/README.md).
- Running it: [Monitoring](monitoring.md), [Performance](performance.md), [Security](security.md).
- Building it: [BUILD.md](../BUILD.md) (host build, hardware profiles, the image),
  [Releases](releases.md).
- Something is wrong: [Troubleshooting](troubleshooting.md).

## About

- [Architecture, design, and why](ARCHITECTURE.md) — units and ports, the wire contract and
  why it is not proprietary, the gateway by example, the engine and the substitution on record,
  the web interface, configuration, packaging, licence position, the rules the design obeys.
- [Licence](../LICENSE) and [NOTICE](../NOTICE) — FSL-1.1-ALv2, proprietary and
  source-available; what is covered and what is not.

## Get started

- [Getting started](getting_started.md) — install from a release (verified first) or from
  source; first request in five commands; what has to exist before the chat unit answers.
- [Configuration](../config/README.md) — the rule for `config/`, and
  [`symoneural-learn.env.example`](../config/symoneural-learn.env.example): every `SYM_*`
  variable with its default and reason.
- [BUILD.md §2–3](../BUILD.md) — prerequisites and the host build, measured on the reference host.

## Use

- [HTTP API](http_api.md) — the Messages dialect as this gateway serves it: every route, the
  credential, the error envelope, model rows and the family-tier field, streaming, with
  requests and responses taken from this runtime.
- [Command line](cli.md) — `symoneural-gateway`, the chat-unit bring-up ladder, the image
  unit launcher, and the tools: ship gate, release cutter, installer, benchmark, licence audit.
- [Web interface](../web/) — three surfaces (chat, code, work), models, rack, settings; source
  only, built with the lockfile-pinned dependency set.

## Operate

- [Monitoring](monitoring.md) — `/health`, `/ready`, `/version`, request ids, the rack view,
  where each unit logs, what the bring-up ladder records.
- [Performance](performance.md) — measured numbers on the reference host, how they were taken
  (`tools/bench-gateway.sh`), and what changes them.
- [Security](security.md) — the credential model, loopback by design, what never enters a
  repository, the ship gate.
- [Troubleshooting](troubleshooting.md) — the traps this build has already paid for, each with
  its symptom, cause and fix.

## Reference

- [Releases](releases.md) — how a release is staged, gated and cut; asset naming per
  architecture; what a release note must contain; the installer.
- [Recipes](../recipes/recipes-learn/recipes-learn.md) — how the estate packages the product
  as an OpenEmbedded image (they build inside the estate's layer).
- [Runtime bring-up](../runtime/runtime.md) — the chat unit's launcher and ladder, and the
  substitution on record.
- [Gateway internals](../gateway/gateway.md) — the endpoint register with the evidence that
  promoted each route, the credential model, the module map.

## Status of this documentation

| Page | State |
|---|---|
| ARCHITECTURE, http_api, cli, monitoring, security, troubleshooting, getting_started, releases, performance | written 2026-09-18 from the running system and the build records |
| configuration | lives in `config/README.md` + the env example; no separate page |
| development (building from source) | lives in `BUILD.md`; no separate page |
| web interface guide | **not written** — the surfaces exist; a walkthrough with screenshots does not |
| conformance suite guide | **not written** — the suite exists in the estate; its use is described in http_api.md only |
| image unit (text-to-image) guide | **not written** — the CUDA build is staged; the unit's HTTP surface is documented in the estate's endpoint register, not here yet |

A machine-readable index for language-model tools is at [`llms.txt`](llms.txt).
