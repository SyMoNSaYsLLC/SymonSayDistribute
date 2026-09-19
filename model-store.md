# model-store

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

Puts a checkpoint into the estate's weight store, under our name, provably.

    model-store where              the store's path, device, UUID, free space
    model-store place <src> <name> copy it in, verify every digest, record provenance

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
