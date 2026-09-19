# symonrag

Retrieval that can show its work.

This page describes what is **running**: the unit answers on 8819, and the estate's own
documents were indexed and queried before this was written.

## What it is for, against the thing it is confused with

RAG supplies what the model should **know**. A LoRA changes how it **behaves**.

Knowledge that changes after training ends cannot be trained in. This estate gains a component
most days, so "what is in this estate" is a retrieval question permanently and a training
question never. That is why the first corpus indexed here is the estate's own documents.

The other half of the difference is checkability. A passage put in front of the model carries
its file and its line range, so the answer can be opened and read. A LoRA's influence cannot be
pointed at.

## Why lexical, and what that costs

There is no embedding model, no sentence-transformers and no vector store on this host, and the
one GPU is serving. Reaching for a hosted embedding API is not something this estate does — its
runtimes are the product.

So this is **BM25**, and it is not a quiet compromise:

- deterministic, no model, no GPU
- every score decomposes into terms a person can read — `explain` returns the table
- when a retrieval is wrong, the reason is inspectable. A cosine distance is not

Its limit, stated rather than discovered: **it matches words**. A question sharing no
vocabulary with the passage that answers it will not retrieve it. Embeddings fix exactly that,
and `explain` exists so that the day this is not good enough, the evidence for replacing it is
in hand rather than a feeling.

`k1 = 1.5` and `b = 0.75` are named constants with what they do written beside them, because a
number nobody can find is a number nobody can question.

## A passage that cannot be cited is not built

Provenance is constructed with the chunk, not attached afterwards. `Passage` refuses to exist
without a source, and refuses an empty span. Every result carries `file:line_start-line_end`,
and a test opens the file at those lines and checks the text is really there.

Splitting is on paragraph boundaries first and on size only when a paragraph is genuinely too
long — a paragraph is a unit somebody wrote deliberately, and passages split mid-sentence read
as nonsense and score badly for the same reason.

## What it refuses

**An empty index.** Searching one raises rather than returning `[]`. "Nothing matched" and
"there is nothing to match against" are different answers, and returning the same thing for
both is how a retrieval system appears to work while indexing nothing.

**A query of only stop words**, rather than silently returning the whole corpus.

**Indexing outside the permitted roots.** `SYM_RAG_ROOTS` decides what may be read, and there
is no default of `/`: an indexer that can read anything is a way to put anything in front of
the model.

**An index that would be empty** after every file was skipped, with the skipped list attached.

**A foreign schema** on load, by name.

## Routes

    GET  /api/symonrag/health    public; answers before configuration and before an index exists
    GET  /api/symonrag/status    what is indexed, and where indexing may read
    POST /api/symonrag/index     build from files under the permitted roots
    POST /api/symonrag/search    top passages, each with a citation
    POST /api/symonrag/explain   why a passage scored what it did, term by term
    POST /api/symonrag/context   the same passages formatted for a prompt, citations attached

`context` is separate from `search` because what goes in front of a model and what a person
reads are different shapes, and building the block here means every caller cites the same way
instead of each inventing a format.

## Where the index lives

`~/symoneural-run/rag/estate.index.json` by default, moved with `SYM_RAG_INDEX`. It is derived
data rather than weights, so it does not belong in the model store — and `/models` is root-owned
on this host, which the symon-imager placement already ran into.

It is JSON on purpose. An index nobody can read is an index nobody can check, and at this size
that costs nothing.

## Proven

Indexed against the estate's own documents: **77 passages, 1920 distinct terms**. Asked *"which
component refuses to route to itself"*, the top result was `adaptive-fabric.md` — which is the
correct answer, and the citation can be opened to confirm it.

## Placement

    placement-triage prospect symonrag --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

## Testing

17 tests: a passage cannot be built without a source or with an empty span, every result
carries a citation, the line numbers point at text that really contains the match, an empty
index is refused, a stop-word query is refused, overlap larger than the target is refused,
`explain` sums to the same score `search` reported, a rare term outscores a common one, the
same tokenizer is used at index and query time, an index round-trips with its provenance
intact, a foreign schema is refused by name, and indexing outside the permitted roots is 403.

## Releases

Tagged `symonrag/v<version>`.
