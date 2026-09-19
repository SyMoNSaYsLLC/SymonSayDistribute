# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The index, and why it is lexical.

WHY BM25 AND NOT EMBEDDINGS
---------------------------
There is no embedding model, no sentence-transformers and no vector store on this host, and the
one GPU is serving. Waiting for those would mean no retrieval at all, and reaching for a hosted
embedding API is not something this estate does — its runtimes are the product.

BM25 is not a compromise made quietly. It is deterministic, it needs no model, and every score
decomposes into terms a person can read: this passage ranked here because these words are rare
in the corpus and frequent in it. When a retrieval is wrong, that is inspectable. A cosine
distance between two vectors is not.

It has a real limit and it is stated rather than discovered: it matches WORDS. A question that
shares no vocabulary with the passage that answers it will not retrieve it. Embeddings fix that
specific weakness, and `explain` exists so the day this is not good enough, the evidence for
replacing it is in hand rather than a feeling.

WHAT IS STORED
--------------
Passages with their provenance, term frequencies, and the corpus statistics BM25 needs. Written
as JSON, because an index nobody can read is an index nobody can check — and this one is small
enough that the cost of that is nothing.
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .chunk import ChunkError, Passage, chunk_file, chunk_text

# BM25's two knobs, at the values the original work settles on. Named, not buried, because a
# number nobody can find is a number nobody can question.
K1 = 1.5     # how fast term frequency saturates
B = 0.75     # how much document length is penalised

_WORD = re.compile(r"[a-z0-9_]+")
# Words carried by nearly every document in any corpus. Not a language model: a short list that
# earns its place by being useless for discriminating between documents.
STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "that", "this", "for", "on",
    "as", "be", "are", "was", "with", "by", "at", "from", "not", "but", "if", "so", "than",
    "then", "there", "they", "you", "we", "he", "she", "its", "has", "have", "had", "will",
}


class IndexError_(Exception):
    """An index operation that could not be completed, carrying why."""


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, stop words dropped. The same function at index and query time.

    It is one function on purpose: an index built with one tokenizer and queried with another
    silently retrieves nothing, and nothing is the hardest failure to notice.
    """
    return [w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1]


class Index:
    """A BM25 index over passages that each know where they came from."""

    def __init__(self) -> None:
        self.passages: dict[str, Passage] = {}
        self.tf: dict[str, Counter] = {}
        self.df: Counter = Counter()
        self.length: dict[str, int] = {}
        self.built_at: str = ""

    # --- building -----------------------------------------------------------------
    def add(self, passages: list[Passage]) -> int:
        added = 0
        for p in passages:
            if p.id in self.passages:
                continue            # the same bytes at the same offset is the same passage
            toks = tokenize(p.text)
            if not toks:
                continue
            self.passages[p.id] = p
            c = Counter(toks)
            self.tf[p.id] = c
            self.length[p.id] = len(toks)
            for t in c:
                self.df[t] += 1
            added += 1
        self.built_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        return added

    def add_file(self, path: str, **kw) -> int:
        return self.add(chunk_file(path, **kw))

    def add_text(self, text: str, source: str, **kw) -> int:
        return self.add(chunk_text(text, source, **kw))

    # --- statistics ---------------------------------------------------------------
    @property
    def n(self) -> int:
        return len(self.passages)

    @property
    def avgdl(self) -> float:
        return (sum(self.length.values()) / self.n) if self.n else 0.0

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    # --- searching ----------------------------------------------------------------
    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Top passages for a query, each with its citation and its score.

        An empty index raises rather than returning []. "Nothing matched" and "there is nothing
        to match against" are different answers, and returning the same thing for both is how a
        retrieval system appears to work while indexing nothing.
        """
        if self.n == 0:
            raise IndexError_("the index is empty; nothing has been added to it. That is a "
                              "different answer from 'nothing matched' and it is not one to "
                              "return silently")
        if k <= 0:
            raise IndexError_("k must be positive")
        terms = tokenize(query)
        if not terms:
            raise IndexError_(f"{query!r} has no searchable words once stop words are dropped")

        avgdl = self.avgdl
        scored = []
        for pid, tf in self.tf.items():
            dl = self.length[pid]
            s = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                s += self.idf(t) * (f * (K1 + 1)) / (f + K1 * (1 - B + B * dl / avgdl))
            if s > 0:
                scored.append((s, pid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for s, pid in scored[:k]:
            p = self.passages[pid]
            out.append({"id": pid, "score": round(s, 4), "cite": p.cite(),
                        "source": p.source, "lines": [p.line_start, p.line_end],
                        "text": p.text})
        return out

    def explain(self, query: str, passage_id: str) -> dict[str, Any]:
        """Why one passage scored what it did, term by term.

        This is the argument for a lexical index. When a retrieval is wrong, the reason is a
        table somebody can read, not a distance between two vectors.
        """
        if passage_id not in self.passages:
            raise IndexError_(f"no passage {passage_id!r} in this index")
        tf = self.tf[passage_id]
        dl = self.length[passage_id]
        avgdl = self.avgdl
        rows, total = [], 0.0
        for t in tokenize(query):
            f = tf.get(t, 0)
            idf = self.idf(t)
            contrib = (idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * dl / avgdl))) if f else 0.0
            total += contrib
            rows.append({"term": t, "in_passage": f, "documents_with_term": self.df.get(t, 0),
                         "idf": round(idf, 4), "contribution": round(contrib, 4)})
        return {"passage": passage_id, "cite": self.passages[passage_id].cite(),
                "score": round(total, 4), "passage_words": dl,
                "average_words": round(avgdl, 1), "terms": rows,
                "k1": K1, "b": B,
                "reading": "a term contributes when it is rare in the corpus (high idf) and "
                           "present here; length normalisation stops long passages winning by "
                           "size alone"}

    # --- persistence ---------------------------------------------------------------
    def save(self, path: str | Path) -> dict[str, Any]:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        blob = {"schema": "symonrag/index/1", "built_at": self.built_at, "n": self.n,
                "k1": K1, "b": B,
                "passages": [asdict(x) for x in self.passages.values()]}
        p.write_text(json.dumps(blob, indent=1))
        return {"path": str(p), "passages": self.n, "bytes": p.stat().st_size}

    @classmethod
    def load(cls, path: str | Path) -> "Index":
        p = Path(path)
        if not p.is_file():
            raise IndexError_(f"no index at {p}")
        blob = json.loads(p.read_text())
        if blob.get("schema") != "symonrag/index/1":
            raise IndexError_(f"{p} is schema {blob.get('schema')!r}, not symonrag/index/1")
        ix = cls()
        ix.add([Passage(**d) for d in blob["passages"]])
        ix.built_at = blob.get("built_at", "")
        return ix
