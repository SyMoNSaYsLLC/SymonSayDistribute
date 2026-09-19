# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Residency and buffers — what is held, where, and for how long.

THE ARITHMETIC IS RAVENCALC'S. THIS IS THE BOOKKEEPING AROUND IT.
----------------------------------------------------------------
Sizes come from the checkpoint through ravencalc; nothing here recomputes them. What is here is
the part ravencalc deliberately does not do: deciding what to keep, what to evict, and whether
a page-in will have arrived before it is needed.

MEASURED FROM symon, 2026-09-19
-------------------------------
    32 experts, 4 active per token      sparsity 0.125
    all experts                         9.467 GiB
    active per token                    1.183 GiB
    always resident (non-expert)        3.349 GiB
    one expert, one layer               12.62 MiB
    24 layers: 12 sliding (window 128), 12 full attention

The shape those numbers give: the whole checkpoint is 12.82 GiB against a 15.92 GiB card, so
nothing has to page at all — until KV cache and activations are wanted too, which is why the
engine runs with 3 GiB offloaded. Residency here is therefore about what to give up FIRST when
something else needs the room, not about a checkpoint that cannot fit.

WHAT IT REFUSES
---------------
To plan a page-in without a measured bandwidth, for the same reason ravencalc refuses: a
transfer time computed from an assumed bus speed is a number that will be believed. And to
report a hit rate over an empty history, because a cache that has served nothing has not
achieved 100%.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Hashable, Iterable, Sequence


class ResidencyError(Exception):
    """A residency decision that could not be made, carrying why."""


# Measured from symon by ravencalc. Recorded, not used to decide anything — a later measurement
# should be compared against a dated one rather than against a memory.
MEASURED = {
    "taken": "2026-09-19",
    "how": "ravencalc expert_residency against /models/symon",
    "experts_total": 32,
    "experts_active_per_token": 4,
    "sparsity": 0.125,
    "gib_all_experts": 9.467,
    "gib_active_per_token": 1.183,
    "gib_always_resident": 3.349,
    "bytes_per_expert_per_layer": 13236480,
    "layers": 24,
    "sliding_layers": 12,
    "sliding_window": 128,
    "reading": "the whole checkpoint is 12.82 GiB on a 15.92 GiB card, so residency here is "
               "about what to give up first when the cache and activations want room — not "
               "about a checkpoint that cannot fit",
}


class StreamBuffer:
    """Per-stream token buffering — `symon-stream-buffer`.

    Bounded, and full means refuse. The same argument as the ingress buffer: an unbounded one
    does not remove the limit, it moves it somewhere that fails worse.
    """

    def __init__(self, *, capacity: int) -> None:
        if capacity <= 0:
            raise ResidencyError("a buffer capacity must be positive")
        self.capacity = capacity
        self._buf: deque = deque()
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def full(self) -> bool:
        return len(self._buf) >= self.capacity

    def push(self, token: Any) -> None:
        if self.full:
            self.dropped += 1
            raise ResidencyError(f"buffer is full at {self.capacity}; refusing rather than "
                                 f"dropping silently — a dropped token is a wrong answer, not "
                                 f"a slow one")
        self._buf.append(token)

    def drain(self, n: int | None = None) -> list[Any]:
        if n is None:
            out, self._buf = list(self._buf), deque()
            return out
        if n <= 0:
            raise ResidencyError("drain needs a positive count")
        out = [self._buf.popleft() for _ in range(min(n, len(self._buf)))]
        return out


class SlidingWindow:
    """The window a checkpoint's sliding layers actually use — `symon-sliding-window`.

    The window is READ from the config, never assumed. On symon half the layers cache 128
    positions and half cache everything, and that asymmetry is the whole reason its KV cache is
    small: at 32k context it is 771 MiB rather than the 1.5 GiB a uniform model would need.
    """

    def __init__(self, *, window: int, layers: int, full_attention_layers: int) -> None:
        if window <= 0:
            raise ResidencyError("a sliding window must be positive")
        if layers <= 0 or not 0 <= full_attention_layers <= layers:
            raise ResidencyError(f"{full_attention_layers} full-attention layers out of "
                                 f"{layers} is not a layer stack")
        self.window = window
        self.layers = layers
        self.full = full_attention_layers
        self.sliding = layers - full_attention_layers

    def positions_cached(self, context: int) -> dict[str, Any]:
        if context <= 0:
            raise ResidencyError("a context must be positive")
        per_sliding = min(self.window, context)
        total = self.sliding * per_sliding + self.full * context
        uniform = self.layers * context
        return {"context": context, "sliding_layers": self.sliding, "full_layers": self.full,
                "positions_per_sliding_layer": per_sliding,
                "positions_total": total, "if_all_layers_were_full": uniform,
                "saved_fraction": round(1 - total / uniform, 4) if uniform else 0.0,
                "why": "sliding layers hold a fixed window however long the context grows, so "
                       "the saving widens with context rather than staying constant"}


class FramePool:
    """Reusable buffers, so steady state stops allocating — `symon-frame-pool`.

    It reports reuse rather than claiming it. A pool that allocates a fresh buffer every time
    is a pool in name only, and the only way to tell is to count.
    """

    def __init__(self, *, size_bytes: int, capacity: int) -> None:
        if size_bytes <= 0 or capacity <= 0:
            raise ResidencyError("a pool needs a positive buffer size and capacity")
        self.size_bytes = size_bytes
        self.capacity = capacity
        self._free: list[int] = []
        self._out: set[int] = set()
        self._next = 0
        self.allocated = 0
        self.reused = 0

    def take(self) -> int:
        if self._free:
            b = self._free.pop()
            self.reused += 1
        else:
            if len(self._out) >= self.capacity:
                raise ResidencyError(f"all {self.capacity} buffers are out; refusing rather "
                                     f"than allocating past the pool, which is how a pool "
                                     f"quietly becomes an allocator")
            b = self._next
            self._next += 1
            self.allocated += 1
        self._out.add(b)
        return b

    def give_back(self, b: int) -> None:
        if b not in self._out:
            raise ResidencyError(f"buffer {b} was not taken from this pool")
        self._out.discard(b)
        self._free.append(b)

    def stats(self) -> dict[str, Any]:
        total = self.allocated + self.reused
        return {"capacity": self.capacity, "size_bytes": self.size_bytes,
                "allocated": self.allocated, "reused": self.reused, "out": len(self._out),
                "reuse_rate": round(self.reused / total, 4) if total else None,
                "bytes_held": self.capacity * self.size_bytes,
                "note": ("no takes yet, so there is no reuse rate — a pool that has served "
                         "nothing has not achieved anything" if not total else
                         "reuse rate is what distinguishes a pool from an allocator")}


class Prefetcher:
    """Brings an expert in before it is selected — `symon-prefetch`.

    It will not estimate a transfer without a MEASURED bandwidth, for the same reason ravencalc
    refuses to: a page-in time computed from an assumed bus speed is a number that will be
    believed and acted on.

    The useful output is not "prefetch this" but whether the prefetch can possibly arrive in
    time. At symon's 12.62 MiB per expert per layer, that is a question with an answer.
    """

    def __init__(self, *, bytes_per_expert: int, bandwidth_bytes_per_s: float) -> None:
        if bytes_per_expert <= 0:
            raise ResidencyError("the expert size must be read from the checkpoint")
        if bandwidth_bytes_per_s <= 0:
            raise ResidencyError("bandwidth must be MEASURED and positive — there is no default, "
                                 "because a page-in time from an assumed bus speed is a number "
                                 "that will be believed")
        self.bytes = bytes_per_expert
        self.bandwidth = bandwidth_bytes_per_s

    def page_in_ms(self, experts: int = 1) -> float:
        if experts <= 0:
            raise ResidencyError("a positive number of experts")
        return (self.bytes * experts / self.bandwidth) * 1000.0

    def in_time(self, *, experts: int, available_ms: float) -> dict[str, Any]:
        if available_ms <= 0:
            raise ResidencyError("the time available must be positive")
        need = self.page_in_ms(experts)
        return {"experts": experts, "page_in_ms": round(need, 3),
                "available_ms": available_ms, "arrives_in_time": need <= available_ms,
                "slack_ms": round(available_ms - need, 3),
                "why": ("the transfer completes before the layer needs it" if need <= available_ms
                        else "the layer would wait on the bus; prefetching this one buys "
                             "nothing and costs bandwidth another one could have used")}


class VramBalancer:
    """Residency across devices — `symon-vram-balance`.

    Capacities are measured and passed in. It refuses to place anything on a device whose free
    memory nobody has read, because the failure from guessing is an out-of-memory at load, long
    after the decision that caused it.
    """

    def __init__(self, devices: dict[str, int]) -> None:
        if not devices:
            raise ResidencyError("no devices; there is nowhere to place anything")
        bad = [d for d, b in devices.items() if b < 0]
        if bad:
            raise ResidencyError(f"{', '.join(bad)} reported negative free memory, which is not "
                                 f"a measurement")
        self.devices = dict(devices)
        self.placed: dict[str, list[tuple[str, int]]] = {d: [] for d in devices}

    def free(self, device: str) -> int:
        used = sum(b for _, b in self.placed[device])
        return self.devices[device] - used

    def place(self, name: str, size_bytes: int, *, prefer: str | None = None) -> dict[str, Any]:
        if size_bytes <= 0:
            raise ResidencyError("a placement needs a positive size")
        order = [prefer] if prefer else sorted(self.devices, key=lambda d: -self.free(d))
        for d in order:
            if d not in self.devices:
                raise ResidencyError(f"{d!r} is not a known device")
            if self.free(d) >= size_bytes:
                self.placed[d].append((name, size_bytes))
                return {"placed": name, "device": d, "bytes": size_bytes,
                        "free_after": self.free(d)}
        raise ResidencyError(
            f"{name} needs {size_bytes} bytes and no device has it free: "
            + ", ".join(f"{d}={self.free(d)}" for d in sorted(self.devices)))

    def report(self) -> dict[str, Any]:
        return {d: {"capacity": self.devices[d], "free": self.free(d),
                    "holding": [n for n, _ in self.placed[d]]}
                for d in sorted(self.devices)}


class Chunker:
    """Fixed-size chunking with the remainder named — `symon-chunker`.

    The remainder is returned rather than padded or dropped. A chunker that silently pads
    changes the data; one that silently drops loses it; and both look identical to the caller.
    """

    def __init__(self, *, size: int, overlap: int = 0) -> None:
        if size <= 0:
            raise ResidencyError("a chunk size must be positive")
        if not 0 <= overlap < size:
            raise ResidencyError(f"overlap {overlap} must be non-negative and smaller than the "
                                 f"chunk size {size}, or chunks contain each other")
        self.size = size
        self.overlap = overlap

    def spans(self, total: int) -> dict[str, Any]:
        if total <= 0:
            raise ResidencyError("nothing to chunk")
        step = self.size - self.overlap
        out, i = [], 0
        while i < total:
            j = min(i + self.size, total)
            out.append((i, j))
            if j >= total:
                break
            i += step
        last = out[-1]
        return {"chunks": len(out), "spans": out, "size": self.size, "overlap": self.overlap,
                "remainder": last[1] - last[0] if (last[1] - last[0]) < self.size else 0,
                "note": "the final short chunk is returned as it is — padding would change the "
                        "data and dropping would lose it, and both look the same from outside"}


class Splitter:
    """Splits a sequence too long for one pass — `symon-splitter`.

    It refuses to split below a floor, because a sequence cut into fragments smaller than the
    model's own window produces pieces with no useful context and an answer built from them is
    worse than a refusal.
    """

    def __init__(self, *, max_length: int, min_piece: int) -> None:
        if max_length <= 0 or min_piece <= 0:
            raise ResidencyError("both bounds must be positive")
        if min_piece > max_length:
            raise ResidencyError(f"a minimum piece of {min_piece} cannot fit a maximum of "
                                 f"{max_length}")
        self.max_length = max_length
        self.min_piece = min_piece

    def split(self, length: int) -> dict[str, Any]:
        if length <= 0:
            raise ResidencyError("nothing to split")
        if length <= self.max_length:
            return {"pieces": [(0, length)], "split": False,
                    "why": "it already fits; splitting would only add joins"}
        n = -(-length // self.max_length)
        even = -(-length // n)
        if even < self.min_piece:
            raise ResidencyError(
                f"splitting {length} into {n} pieces gives {even}, below the {self.min_piece} "
                f"floor; pieces that small carry no useful context and an answer from them is "
                f"worse than refusing")
        out, i = [], 0
        while i < length:
            out.append((i, min(i + even, length)))
            i += even
        return {"pieces": out, "split": True, "piece_length": even,
                "why": f"{length} over a {self.max_length} maximum needs {n} pieces; evened to "
                       f"{even} so the last is not a stub"}


class Slicer:
    """Splits a tensor across a boundary — `symon-slicer`.

    It refuses a slice that does not divide the axis evenly unless told explicitly to allow a
    remainder, because an uneven split of a tensor across devices is a silent load imbalance.
    """

    def slice(self, shape: Sequence[int], axis: int, parts: int, *,
              allow_remainder: bool = False) -> dict[str, Any]:
        if not shape:
            raise ResidencyError("an empty shape cannot be sliced")
        if not 0 <= axis < len(shape):
            raise ResidencyError(f"axis {axis} is outside a {len(shape)}-dimensional shape")
        if parts <= 0:
            raise ResidencyError("parts must be positive")
        n = shape[axis]
        if parts > n:
            raise ResidencyError(f"cannot cut an axis of {n} into {parts} parts")
        rem = n % parts
        if rem and not allow_remainder:
            raise ResidencyError(
                f"{n} does not divide into {parts} evenly ({rem} left over). An uneven split "
                f"across devices is a silent load imbalance — pass allow_remainder to accept it")
        base = n // parts
        sizes = [base + (1 if i < rem else 0) for i in range(parts)]
        shapes, at, spans = [], 0, []
        for s in sizes:
            sh = list(shape); sh[axis] = s
            shapes.append(tuple(sh)); spans.append((at, at + s)); at += s
        return {"axis": axis, "parts": parts, "sizes": sizes, "shapes": shapes,
                "spans": spans, "even": rem == 0,
                "imbalance": round((max(sizes) - min(sizes)) / max(sizes), 4) if sizes else 0.0}


@dataclass
class Stager:
    """Moves data between stages without copying twice — `symon-stager`.

    It tracks what is where and refuses a move whose source it does not hold, because a stager
    that "moves" something it never had leaves the real copy somewhere nobody is looking.
    """

    holds: dict[str, str] = field(default_factory=dict)
    moves: list[dict[str, Any]] = field(default_factory=list)

    def admit(self, name: str, where: str) -> None:
        if name in self.holds:
            raise ResidencyError(f"{name} is already staged at {self.holds[name]}; admitting it "
                                 f"twice would leave two records of one thing")
        self.holds[name] = where

    def move(self, name: str, to: str) -> dict[str, Any]:
        if name not in self.holds:
            raise ResidencyError(f"{name} is not staged here; moving something this does not "
                                 f"hold leaves the real copy where nobody is looking")
        frm = self.holds[name]
        if frm == to:
            return {"name": name, "from": frm, "to": to, "moved": False,
                    "why": "already there; a move to where it is would be a copy"}
        self.holds[name] = to
        row = {"name": name, "from": frm, "to": to, "moved": True}
        self.moves.append(row)
        return row

    def release(self, name: str) -> str:
        if name not in self.holds:
            raise ResidencyError(f"{name} is not staged here")
        return self.holds.pop(name)
