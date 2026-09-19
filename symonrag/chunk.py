# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Turning documents into passages that can be cited.

A CHUNK THAT CANNOT SAY WHERE IT CAME FROM IS NOT A CHUNK
---------------------------------------------------------
The whole value of retrieval over training is that the answer can be traced: a passage put in
front of the model carries its source, its byte offsets and its line numbers, so what the model
read can be checked afterwards. A retrieval system that returns text without provenance has
given up the only advantage it has over a LoRA.

So provenance is not metadata attached later. It is constructed with the chunk, and a chunk
missing any part of it cannot be built at all.

SPLIT ON STRUCTURE, THEN ON SIZE
--------------------------------
Paragraph boundaries first, because a paragraph is a unit somebody wrote deliberately, and a
retriever that splits mid-sentence returns passages that read as nonsense and score badly for
the same reason. Size is the fallback when a paragraph is too long to be one passage.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# No default. How much context a passage carries is a decision about the model's window and
# about what a citation should show, and inheriting it is how a corpus ends up chunked for a
# model nobody is using any more.
DEFAULT_TARGET = 1200
DEFAULT_OVERLAP = 150

_PARA = re.compile(r"\n\s*\n")


class ChunkError(Exception):
    """A document that could not be chunked, carrying why."""


@dataclass(frozen=True)
class Passage:
    """One retrievable piece of text, and everything needed to point at where it came from."""

    id: str
    text: str
    source: str
    ordinal: int
    start: int
    end: int
    line_start: int
    line_end: int
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ChunkError("an empty passage is not a passage")
        if not self.source:
            raise ChunkError("a passage with no source cannot be cited, and citing it is the "
                             "reason it exists")
        if self.end <= self.start:
            raise ChunkError(f"{self.source}: offsets {self.start}..{self.end} are not a span")

    def cite(self) -> str:
        return f"{self.source}:{self.line_start}-{self.line_end}"


def _passage_id(source: str, start: int, text: str) -> str:
    h = hashlib.sha256(f"{source}\x00{start}\x00{text}".encode()).hexdigest()
    return h[:16]


def chunk_text(text: str, source: str, *, target: int = DEFAULT_TARGET,
               overlap: int = DEFAULT_OVERLAP, meta: dict | None = None) -> list[Passage]:
    """Split one document into passages, each carrying exactly where it came from."""
    if target <= 0:
        raise ChunkError("a target size must be positive")
    if overlap < 0 or overlap >= target:
        raise ChunkError(f"overlap {overlap} must be non-negative and smaller than the target "
                         f"{target}; otherwise passages contain each other")
    if not text.strip():
        raise ChunkError(f"{source} has no text to chunk")

    # Line numbers from byte offsets, computed once.
    newlines = [i for i, c in enumerate(text) if c == "\n"]

    def line_of(off: int) -> int:
        lo, hi = 0, len(newlines)
        while lo < hi:
            mid = (lo + hi) // 2
            if newlines[mid] < off:
                lo = mid + 1
            else:
                hi = mid
        return lo + 1

    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _PARA.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))

    out: list[Passage] = []
    buf_start: int | None = None
    buf_end = 0
    for s, e in spans:
        if not text[s:e].strip():
            continue
        if buf_start is None:
            buf_start, buf_end = s, e
            continue
        if (e - buf_start) <= target:
            buf_end = e
            continue
        out.extend(_emit(text, buf_start, buf_end, source, len(out), target, overlap,
                         line_of, meta or {}))
        buf_start, buf_end = s, e
    if buf_start is not None:
        out.extend(_emit(text, buf_start, buf_end, source, len(out), target, overlap,
                         line_of, meta or {}))
    if not out:
        raise ChunkError(f"{source} produced no passages")
    return out


def _emit(text: str, start: int, end: int, source: str, ordinal: int, target: int,
          overlap: int, line_of, meta: dict) -> Iterable[Passage]:
    """Emit one span, splitting on size only when it is genuinely too long."""
    if (end - start) <= target:
        body = text[start:end].strip()
        if body:
            yield Passage(id=_passage_id(source, start, body), text=body, source=source,
                          ordinal=ordinal, start=start, end=end,
                          line_start=line_of(start), line_end=line_of(end), meta=dict(meta))
        return
    step = target - overlap
    i = start
    n = ordinal
    while i < end:
        j = min(i + target, end)
        body = text[i:j].strip()
        if body:
            yield Passage(id=_passage_id(source, i, body), text=body, source=source,
                          ordinal=n, start=i, end=j,
                          line_start=line_of(i), line_end=line_of(j), meta=dict(meta))
            n += 1
        if j >= end:
            break
        i += step


def chunk_file(path: str | Path, *, target: int = DEFAULT_TARGET,
               overlap: int = DEFAULT_OVERLAP) -> list[Passage]:
    """Chunk a file on disk. The source is its real path, so a citation can be opened."""
    p = Path(path)
    if not p.is_file():
        raise ChunkError(f"{p} is not a file")
    try:
        text = p.read_text(errors="replace")
    except Exception as e:
        raise ChunkError(f"{p} could not be read: {e}")
    return chunk_text(text, str(p.resolve()), target=target, overlap=overlap,
                      meta={"bytes": p.stat().st_size, "suffix": p.suffix})
