# symoneural-learn

SyMoNeuRaL's own inference runtime: three model surfaces served from one machine,
behind one API, with nothing leaving the host.

```
client  ->  127.0.0.1:9001   gateway      the /v1 dialect, the credential, the registry
            127.0.0.1:8802   chat unit    the engine holding the weights
            127.0.0.1:3000   web          the first-party interface
```

| Model | Surface | Tier |
|---|---|---|
| `symon-sonnet` | Chat | sonnet |
| `symon-opus` | Code | opus |
| `symon-fable` | Cowork | fable |

---

## Why this repository exists separately

The estate that *builds* this product lives in `SymonSayLearn`, and it tracks roughly
291,000 files of third-party source at pinned commits. That is the right shape for a
build system and the wrong shape for a product:

- **The licence question becomes ambiguous.** A root `LICENSE` in a tree full of
  other people's source reads as licensing their work too.
- **Copyleft has to be audited out** rather than designed out, because the acquired
  layers contain GPL, LGPL and AGPL components that the build must be told to
  exclude.
- **Nothing is publishable.** 19 GB, most of it not ours to publish.

This repository contains **first-party code only**. There is no `upstream/`. Every
file in it is SyMoNeuRaL's, which makes the licence unambiguous and makes copyleft a
question about what the *build* pulls in rather than about what the repository
contains.

Third-party source is acquired by the build estate at pinned commits and never
vendored here.

---

## Layout

```
gateway/          the /v1 dialect: registry, credential, worker client — pip-installable (pyproject.toml)
web/              the interface, Next.js, source only
runtime/          bring-up for the chat unit
recipes/          the BitBake recipes that package all of it (they build inside the estate's layer)
config/           the configuration contract (symoneural-learn.env.example) and reference clients
tools/            the licence audit, the ship gate, the release cutter
docs/             cross-cutting documents (empty today)
```

Each directory carries its own document named after it.

---

## The wire contract, and why it is this one

The gateway speaks the Messages API dialect — `POST /v1/messages`, `GET /v1/models`,
`POST /v1/messages/count_tokens`, streaming as server-sent events — under SyMoNeuRaL's own
model names. The shape was chosen because it is a **public, widely implemented wire
format**: every SDK, desktop client and CLI that already speaks it works against this
runtime with a base-URL change and nothing else. The endpoint shapes are not ours and are
not proprietary; what is ours is the implementation behind them, the model cards and the
engine. `docs/ARCHITECTURE.md` gives the design and its reasons.

Two design facts follow from the dialect:

1. Compatible clients filter `GET /v1/models` rows: an id survives if it matches the
   dialect's family patterns **or** the row carries the family-tier field
   (`FAMILY_TIER_FIELD` in `models.py`), and ids that carry an upstream vendor's name are
   commonly dropped. So the upstream
   checkpoint name is never exposed, and a first-party id such as `symon-sonnet` is selectable
   **only** because this gateway emits the tier field — a plain chat-completions model list
   cannot supply it. The field is a wire field, not a claim of equivalence to anyone's model.
2. The three surfaces — chat, code, cowork — map to three model cards (`symon-sonnet`,
   `symon-opus`, `symon-fable`), one default per tier. Behind them runs one engine today,
   reached through `SYM_CHAT_URL`; swapping it changes nothing above `worker.py`.

Nothing in this runtime calls a third-party service. Inference runs on the operator's own
hardware, the gateway binds loopback, and public reach is through the operator's edge proxy.

---

## Licence position

`LICENSE` is **SymonSaysLLC Proprietary License 1.0** — proprietary, source-available; not closed, not open
source. You may read, build and use it for anything that is not a competing commercial
product or service, and each release becomes Apache-2.0 two years after it ships.
Everything in this repository is covered because everything in it is first-party; see
`NOTICE`. Licensor: SymonSaysLLC — Garrett McDonald (Developer,
gmcdonald@symoneural.com), Ben Hesley (Business, bhesley@symoneural.com).

The build is a different question, and it is enforced rather than asserted:

```sh
python3 tools/licence-audit.py --check      # exit 1 if copyleft ships
python3 tools/ship-gate.py --repo .       # exit 1 on secrets, weights, August dates in ANY blob of history
python3 tools/ship-gate.py --stage <dir>  # the full release gate: every licence class, attribution, CVEs, trademarks
```

The audit reads the install manifests of images that were **actually built** — ground
truth, not intent — maps each package back to its recipe, and classifies by what the
obligation *does* on distribution. It refuses to report an unresolved package as
clean.

`recipes/recipes-core/images/symoneural-image-learn.bb` carries:

```
INCOMPATIBLE_LICENSE = "GPL-3.0* LGPL-3.0* AGPL-3.0* SSPL*"
```

BitBake refuses to place a matching package in the rootfs, so the build fails instead
of shipping. LGPL-2.1 is deliberately absent from that list: glibc is the C library
and excluding it would leave nothing to run, and LGPL permits proprietary use when
the library is dynamically linked.

`recipes/recipes-devtools/python/python3_%.bbappend` drops `gdbm`, which is
GPL-3.0-only and reached the image only because OpenEmbedded enables it in python3 by
default. Nothing here imports `dbm`; `sqlite3` already ships and its licence is
`blessing`.

**Applied, not yet run.** The image has not been rebuilt with the policy in place.

---

## Status

Serving, measured:

| Check | Result |
|---|---|
| Client's exact connection probe through the gateway | `200` in 0.365 s, `content` an array |
| `/v1/models` | three rows, each carrying a tier |
| Unknown model (the upstream checkpoint's own name) | `404`, refused by name |
| Web interface | `200`, 9 routes, TypeScript clean |

Not proven: streaming through the gateway's relay path, and the BitBake image.

See `BUILD.md` for both build paths and the per-hardware notes.
