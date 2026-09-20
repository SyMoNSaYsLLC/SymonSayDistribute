# symonlora

Everything before the card is taken.

This page describes what is **built**: the plan, the training-set validation and the
prerequisite check all run, against the real checkpoint. Training itself does not run here, and
the reason is below rather than implied.

## LoRA against RAG, since they get confused

A LoRA changes how the model **behaves** — tone, format, following a convention. Its knowledge
is frozen at training time. It is an **artifact**: it gets a version and lives in the store.

RAG supplies what the model should **know**, at question time, with citations. It is a
**component**. That is [symonrag](../symonrag/symonrag.md).

If symon formats answers wrongly, that is this unit. If symon does not know what is in the
estate today, no amount of training fixes it, because the answer changes after training ends.

## Why validation is most of this

A run is hours of a card that is otherwise serving, and the failure is not a crash. It is an
adapter that trains cleanly and makes the model worse — and every cause of that is visible in
the data beforehand.

Duplicates are the clearest case. A set containing the same example four times teaches that
answer with four times the weight, and the loss curve looks *excellent* while it happens. So
duplicates are counted and the run is refused, with the worst repeat count named.

Also refused: two schemas in one file (a loader reads one and silently drops the other), empty
completions, examples longer than the context they will be trained at, and a set below a stated
minimum. `deduplicate` reports what it *would* remove and does not touch the file — a tool that
quietly rewrites a training set is a tool that decides the experiment.

## Every number comes from the checkpoint

Adapter size depends on the shapes of the modules being adapted, and those are in `config.json`.

On symon that matters more than usual. It has **64 attention heads but 8 key/value heads**, so
`k_proj` and `v_proj` are eight times narrower than `q_proj`. Sizing an adapter as though all
four projections matched would overstate it by more than double:

    q_proj   2880 -> 4096    111,616 params per layer
    k_proj   2880 ->  512     54,272
    v_proj   2880 ->  512     54,272
    o_proj   4096 -> 2880    111,616
    -------------------------------------------------
    rank 16, 24 layers      7,962,624 trainable params
                               91.12 MiB weights + gradients + Adam moments

And symon's MXFP4 quantization **explicitly does not convert attention** — which is where these
targets live — so they are full precision and adaptable. The plan reads that out of the config
and says so rather than leaving it to be discovered.

## What it refuses to calculate

**Activation memory.** It depends on batch size, sequence length and whether recomputation is
on. It is measured, not derived from a config, and a plan that folded in a guessed figure would
be exactly the confident wrong number this estate exists to refuse.

**A fit verdict without a measured free figure.** `fits` is `null` unless free memory is
supplied. When it is supplied, the answer says it excludes activations, so `true` means *not
ruled out* and never *will fit*.

## Why there is no `train` route

Not an omission, and not a 501.

Training needs `peft`, `datasets` and `accelerate` — none installed here — and it needs the one
GPU that is currently serving. A route that accepted a request and failed inside would be a
promise this unit cannot keep, and starting a run from an HTTP call is how a card gets taken
while somebody is using it. A test asserts no route contains "train".

`prereq` is the honest surface instead. Asked about the serving venv it reports:

    present : torch, transformers
    missing : peft, datasets, accelerate
    install : <venv>/bin/python -m pip install peft datasets accelerate

with one line per package saying what it is for. That is an install on Garrett's machine, so it
is named rather than done.

## Routes

    GET  /api/symonlora/health        public; answers before configuration
    GET  /api/symonlora/prereq        what is missing, and the command that fixes it
    POST /api/symonlora/modules       what this architecture exposes, with real shapes
    POST /api/symonlora/plan          adapter size and trainable memory
    POST /api/symonlora/validate      everything wrong with a training set
    POST /api/symonlora/deduplicate   what deduplication would remove — offered, not applied

## Placement

    placement-triage prospect symonlora --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

The training libraries are not dependencies of this unit — it reports on them in another
environment and never imports them.

## Testing

21 tests. The arithmetic: grouped-query attention makes k/v projections eight times smaller,
adapter parameters are rank × (in + out) per layer, doubling the rank doubles them, and Adam's
cost is exactly two fp32 moments. The refusals: a checkpoint with no config, a module the
architecture lacks named back, a config without head shapes, no fit verdict without a measured
figure, duplicates with the worst count named, two schemas in one file, a non-json line with its
line number, an environment that is not one. And one that guards the design: no route contains
"train".

## Releases

Tagged `symonlora/v<version>`.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonlora`](symonlora/symonlora.md) | the capability this unit provides — `dataset.py`, `plan.py`, `prereq.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symonlora`](symonlora/symonlora.md), [`tests`](tests/tests.md).
