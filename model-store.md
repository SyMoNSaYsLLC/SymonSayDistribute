# model-store

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

Puts a checkpoint into the estate's weight store, under our name, provably.

    model-store where              the store's path, device, UUID, free space
    model-store place <src> <name> copy it in, verify every digest, record provenance
    model-store verify <name>      re-hash every tracked file against the manifest

`verify` is the same function the HTTP surface calls, not a second implementation. Two answers
to "is this checkpoint still what it was" would eventually disagree, and the day they disagree
is the day nobody knows which to believe.

Pinning is **not** here. Recording what an upstream is — its commit, its declared licence, the
checksum of that licence file — is what the `source-pin` skill does, and `model-store pin`
refuses with a pointer rather than keeping a second pin record.

## Why it exists

Nothing in the estate put a model anywhere. `serve-chat-unit.sh` READS the store; the store was
filled by hand. So the one artifact the whole product depends on arrived by a command nobody
recorded, under a name nobody checked, with no manifest, no provenance and no pin — and the only
thing making it "ours" was a symlink to a directory named after its upstream.

## What a migration is, and is not

It is: our store, our name, our manifest, our provenance record, our model card. Section 3.11 —
our name goes on what we made, which is the composition.

It is **not** rewriting the checkpoint. `config.json`, the tokenizer and every tensor file are
copied byte for byte and verified, for two reasons that happen to agree: they are technical
identifiers required to load the software, so changing `model_type` or `architectures` breaks
every loader; and the licence obliges us to keep attribution and to state what we changed. A
migration that edited them would be a misrepresentation.

## What it refuses

A destination with no filesystem UUID, or on tmpfs, overlay or FUSE — that is not disk. A
destination without room for the copy plus five percent. A store inside a git repository, because
weights never go on a path git can stage. A source with no LICENSE. An entry that already exists,
because this places new things and does not overwrite.

## The source is never touched

Copy, never move. The acquired tree stays exactly where it is, complete and unmodified, so the
placement is reversible and nothing is destroyed to perform it.

## Releases

Tagged `model-store/v<version>`.

## Over HTTP

Five routes on `127.0.0.1:8812`, the port `/models/control.board` assigns to `store`.
Placement is deliberately **not** among them: putting thirteen gigabytes
somewhere is an act with a filesystem, free space and a licence to check, and it stays a
command somebody runs with their hands. A surface that could place a model by accident is a
surface that will.

    GET  /api/store/health                    public; answers while unconfigured and empty
    GET  /api/store/where                     device, filesystem, UUID, free space, is_disk
    GET  /api/store/models                    what is in the store, and what is unverifiable
    GET  /api/store/models/{name}             the manifest and the provenance record
    POST /api/store/models/{name}/verify      re-hash every tracked file and compare

`is_disk` is false for tmpfs, overlay and network mounts — all of which accept every write and
lose them — and false when no filesystem UUID can be read. Section 3.1c.

### Verify is the point

A manifest nobody recomputes is a claim, not a check. `verify` reports three things separately,
because they mean different things: a digest that **moved** (the bytes changed), a file that is
**gone**, and a file that is present but **untracked**. Collapsing them loses the distinction
between corruption and somebody having added something.

It is a POST because it reads every byte of a multi-gigabyte checkpoint, which is not something
to do on a page load.
