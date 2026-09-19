# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Batch formation — turning admitted requests into one call the engine can take.

A batch is formed against a token ceiling, not a request count. Four requests can be four
hundred tokens or forty thousand, and a batcher that counts requests will form one that does
not fit and discover it at the engine. The count bound exists as well, because a batch of two
thousand tiny requests has its own problems, but tokens are the bound that decides.

Every formed batch carries what formed it: which bound tripped, what the alternatives were.
A batch that cannot say why it is the size it is cannot be tuned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from .admit import Request


class CannotForm(Exception):
    """A batch could not be formed, carrying why. Never a silent empty batch."""


class TokenBudget:
    """The token ceiling a batch may not cross.

    Not a suggestion and not a target: `fits` is asked before a request joins, and a request
    that cannot ever fit is a refusal at admission, not a batch that gets formed anyway.
    """

    def __init__(self, ceiling: int) -> None:
        if ceiling <= 0:
            raise ValueError("a token ceiling must be positive")
        self.ceiling = ceiling
        self.spent = 0

    @property
    def left(self) -> int:
        return self.ceiling - self.spent

    def fits(self, tokens: int) -> bool:
        return tokens <= self.left

    def spend(self, tokens: int) -> None:
        if not self.fits(tokens):
            raise CannotForm(f"{tokens} tokens does not fit in the {self.left} left of {self.ceiling}")
        self.spent += tokens

    def reset(self) -> None:
        self.spent = 0


@dataclass(frozen=True)
class Batch:
    """The formed unit, with its provenance.

    `bound` says what ended formation — "tokens", "count", "window" or "drained". That field is
    the difference between tuning and guessing: a unit always bound by "window" is waiting when
    it could be working, and one always bound by "tokens" wants a bigger ceiling or a smaller
    context, and those are opposite changes.

    "drained" means the pending list ran out, which is not a bound at all — it is the unit
    being under-loaded. It earns its own value because reporting it as "count" or "window"
    would make an idle unit look like a saturated one, and those call for opposite responses.
    """

    requests: tuple[Request, ...]
    tokens: int
    bound: str

    def __post_init__(self) -> None:
        if not self.requests:
            raise ValueError("an empty batch is not a batch; raise CannotForm instead")
        if self.bound not in ("tokens", "count", "window", "drained"):
            raise ValueError(f"unknown bound {self.bound!r}")

    def __len__(self) -> int:
        return len(self.requests)

    @property
    def ids(self) -> list[str]:
        return [r.id for r in self.requests]


class DynamicBatcher:
    """Forms a batch on whichever bound trips first.

    Three bounds, all explicit, none defaulted: the token ceiling, the request count, and the
    window in milliseconds. `LatencyBoundBatcher` in the name map is this class with the window
    set small — a configuration, not a second implementation, because two implementations of
    "when do we stop waiting" is two answers to the same question.
    """

    def __init__(self, *, max_tokens: int, max_requests: int, window_ms: int,
                 clock: Callable[[], int]) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_ms < 0:
            raise ValueError("window_ms cannot be negative")
        self.max_tokens = max_tokens
        self.max_requests = max_requests
        self.window_ms = window_ms
        self.clock = clock
        self._budget = TokenBudget(max_tokens)

    def form(self, pending: Sequence[Request], opened_at_ms: int | None = None) -> Batch:
        """Form one batch from the front of `pending`, in the order given.

        Order is the caller's: the Prioritizer decided it, and re-sorting here would quietly
        override an admission policy from inside a formatter.
        """
        if not pending:
            raise CannotForm("nothing pending")
        first = pending[0]
        if first.tokens > self.max_tokens:
            raise CannotForm(
                f"{first.id} alone is {first.tokens} tokens against a ceiling of {self.max_tokens}; "
                f"this cannot be batched and should have been refused at admission")

        self._budget.reset()
        taken: list[Request] = []
        bound = "count"
        for req in pending:
            if len(taken) >= self.max_requests:
                bound = "count"
                break
            if not self._budget.fits(req.tokens):
                bound = "tokens"
                break
            if (opened_at_ms is not None and taken
                    and self.clock() - opened_at_ms >= self.window_ms):
                bound = "window"
                break
            self._budget.spend(req.tokens)
            taken.append(req)
        else:
            # Fell off the end of `pending` without any bound tripping: there was simply no
            # more work. Not a limit, and it must not be reported as one.
            bound = "count" if len(taken) >= self.max_requests else "drained"

        return Batch(requests=tuple(taken), tokens=self._budget.spent, bound=bound)


class MicroBatch:
    """Splits a formed batch into pieces that fit a device.

    Separate from forming because the reasons differ: forming is about latency and fairness,
    splitting is about what the card will hold. Collapsing them means a latency decision gets
    made by a memory constraint.
    """

    def __init__(self, *, max_tokens: int) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.max_tokens = max_tokens

    def split(self, batch: Batch) -> list[Batch]:
        pieces: list[Batch] = []
        cur: list[Request] = []
        tot = 0
        for r in batch.requests:
            if r.tokens > self.max_tokens:
                raise CannotForm(
                    f"{r.id} is {r.tokens} tokens and no micro-batch of {self.max_tokens} holds it")
            if tot + r.tokens > self.max_tokens and cur:
                pieces.append(Batch(tuple(cur), tot, "tokens"))
                cur, tot = [], 0
            cur.append(r)
            tot += r.tokens
        if cur:
            pieces.append(Batch(tuple(cur), tot, batch.bound))
        return pieces


class Padder:
    """Pads sequences to a common length and reports what that cost.

    The waste is returned, not logged and forgotten. Padding to the longest member is the
    normal thing to do and it is also where throughput quietly goes: one 8k sequence among
    seven 200-token ones wastes more than it serves, and the number is what makes that visible.
    """

    def pad(self, lengths: Sequence[int], pad_to: int | None = None) -> dict:
        if not lengths:
            raise CannotForm("nothing to pad")
        if any(n < 0 for n in lengths):
            raise ValueError("a negative length is not a length")
        width = pad_to if pad_to is not None else max(lengths)
        if width < max(lengths):
            raise CannotForm(f"cannot pad to {width}; the longest member is {max(lengths)}")
        used = sum(lengths)
        total = width * len(lengths)
        return {"width": width, "count": len(lengths), "used": used,
                "allocated": total, "wasted": total - used,
                "waste_fraction": round((total - used) / total, 4) if total else 0.0}


class Stacker:
    """Equal-shape stacking. Refuses ragged input rather than padding it silently.

    Padding is Padder's decision and it is a decision — it costs memory and it changes the
    result's shape. A stacker that pads when it meets ragged input makes that choice invisibly
    and at the worst moment.
    """

    def stack(self, shapes: Sequence[tuple[int, ...]]) -> tuple[int, ...]:
        if not shapes:
            raise CannotForm("nothing to stack")
        first = shapes[0]
        for i, s in enumerate(shapes[1:], 1):
            if s != first:
                raise CannotForm(
                    f"ragged: member 0 is {first} and member {i} is {s}. Pad deliberately with "
                    f"Padder, or split; stacking will not choose for you")
        return (len(shapes), *first)


class Concatenator:
    """Joins sequences into one, with the boundaries recorded.

    The offsets come back because the result has to be taken apart again. A concatenation whose
    boundaries are recomputed downstream is a concatenation that will one day be split wrongly.
    """

    def join(self, lengths: Sequence[int]) -> dict:
        if not lengths:
            raise CannotForm("nothing to concatenate")
        offsets, at = [], 0
        for n in lengths:
            if n <= 0:
                raise ValueError("a zero-length member has no place in a concatenation")
            offsets.append((at, at + n))
            at += n
        return {"total": at, "count": len(lengths), "boundaries": offsets}


class Packer:
    """Packs members into rows of a fixed width, first-fit-decreasing, no padding waste.

    Where Padder pads everything to the longest, this reorders to fill rows. It is the better
    answer when members vary a lot, and it is not always the right one — it changes the order,
    which matters when order is fairness. The caller chooses; this does not choose for them.
    """

    def pack(self, lengths: Sequence[int], width: int) -> dict:
        if width <= 0:
            raise ValueError("width must be positive")
        if any(n > width for n in lengths):
            raise CannotForm(f"a member of {max(lengths)} does not fit a width of {width}")
        rows: list[list[int]] = []
        order = sorted(range(len(lengths)), key=lambda i: -lengths[i])
        sums: list[int] = []
        placed: list[list[int]] = []
        for i in order:
            for r, s in enumerate(sums):
                if s + lengths[i] <= width:
                    placed[r].append(i); sums[r] += lengths[i]; break
            else:
                placed.append([i]); sums.append(lengths[i])
        rows = [[lengths[i] for i in row] for row in placed]
        used = sum(lengths)
        allocated = width * len(rows)
        return {"rows": len(rows), "width": width, "members": placed, "row_lengths": rows,
                "used": used, "allocated": allocated, "wasted": allocated - used}


class Bundler:
    """Request bodies into one wire payload, keeping the mapping back to the callers."""

    def bundle(self, batch: Batch, bodies: dict[str, dict]) -> dict:
        missing = [r.id for r in batch.requests if r.id not in bodies]
        if missing:
            raise CannotForm(f"no body supplied for {', '.join(missing)}")
        return {"count": len(batch), "tokens": batch.tokens, "bound": batch.bound,
                "order": batch.ids, "items": [bodies[i] for i in batch.ids]}


@dataclass
class Staging:
    """Formed but not yet dispatched.

    It exists so a stall is visible. Without it a batch that is formed and then never sent
    looks identical to a batch that was never formed, and those have different causes.
    """

    held: list[Batch] = field(default_factory=list)

    def put(self, batch: Batch) -> None:
        self.held.append(batch)

    def take(self) -> Batch:
        if not self.held:
            raise CannotForm("nothing staged")
        return self.held.pop(0)

    @property
    def depth(self) -> int:
        return len(self.held)

    @property
    def tokens_held(self) -> int:
        return sum(b.tokens for b in self.held)


class Reservoir:
    """Tokens available to spend in the current window.

    Refills on a window boundary rather than continuously: a continuous refill smooths the
    rate but hides the burst, and the burst is what runs the card out of memory.
    """

    def __init__(self, *, per_window: int) -> None:
        if per_window <= 0:
            raise ValueError("per_window must be positive")
        self.per_window = per_window
        self.available = per_window
        self.windows = 0

    def draw(self, tokens: int) -> None:
        if tokens <= 0:
            raise ValueError("draw needs a positive amount")
        if tokens > self.available:
            raise CannotForm(f"{tokens} tokens exceeds the {self.available} left this window")
        self.available -= tokens

    def refill(self) -> None:
        self.available = self.per_window
        self.windows += 1
