# symoneural-learn

SyMoNeuRaL's own inference runtime: three model surfaces served from one machine,
behind one API, with nothing leaving the host.

```
client  ->  127.0.0.1:9001   gateway      the /v1 dialect, the credential, the registry
            127.0.0.1:8802   chat unit    the engine holding the weights
            127.0.0.1:8812   web          the first-party interface
```

| Model | Surface | Tier |
|---|---|---|
| `symon-chat` | Chat | sonnet |
| `symon-coder` | Code | opus |
| `symon-work` | Cowork | fable |

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
gateway/          the /v1 dialect: registry, credential, worker client
web/              the interface, Next.js, source only
runtime/          bring-up for the chat unit
recipes/          the BitBake layer that packages all of it
config/           client configuration, tracked rather than hand-set
tools/            the licence audit
docs/             what is not a directory document
```

Each directory carries its own document named after it.

---

## The one thing to understand before changing anything

A client filters the models a gateway advertises. Measured from the installed
Claude Desktop bundle, not from documentation:

```js
Nxe = /...|gpt|...|openai|.../          // hard blocklist
qo(id) = Nxe.test(id) ? false : Ko.test(id) || Mxe.some(m => id.includes(m))
// a /v1/models row survives iff  qo(row.id) || row.anthropic_family_tier in Wo
```

Two consequences that shape the whole design:

1. A model named `gpt-oss-20b` can **never** be offered. `gpt` and `openai` are both
   blocklist entries.
2. `symon-chat` trips no blocklist entry but matches no allow-pattern either, so it
   survives **only** because this gateway emits `anthropic_family_tier`.

An engine emitting plain OpenAI-shaped model rows cannot supply that field. The
first-party gateway is therefore not a convenience layer; it is the only path by
which a Symon-branded model reaches a picker at all.

`anthropic_family_tier` is a wire field, not a claim of equivalence to anyone else's
model.

---

## Licence position

`LICENSE` is **FSL-1.1-ALv2** — proprietary, source-available; not closed, not open
source. You may read, build and use it for anything that is not a competing commercial
product or service, and each release becomes Apache-2.0 two years after it ships.
Everything in this repository is covered because everything in it is first-party; see
`NOTICE`. Licensor: SymonSaysLLC — Garrett McDonald (Developer,
gmcdonald@symoneural.com), Ben Hesley (Business, bhesley@symoneural.com).

The build is a different question, and it is enforced rather than asserted:

```sh
python3 tools/licence-audit.py --check      # exit 1 if copyleft ships
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
| Unknown model `gpt-oss-20b` | `404`, refused by name |
| Web interface | `200`, 9 routes, TypeScript clean |

Not proven: streaming through the gateway's relay path, and the BitBake image.

See `BUILD.md` for both build paths and the per-hardware notes.
