# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The training set, and refusing to train on one that will not teach anything.

WHY VALIDATION IS MOST OF THIS MODULE
-------------------------------------
A LoRA run is hours of a card that is otherwise serving, and the failure mode is not a crash:
it is an adapter that trains cleanly and makes the model worse. Every cause of that is visible
in the data before the run starts.

Duplicates are the clearest. A set with the same example forty times teaches the model that one
answer with forty times the weight, and the loss curve looks excellent while it happens. So
duplicates are counted and refused rather than reported as a warning nobody reads.

WHAT IT REFUSES
---------------
Too few examples, duplicates, mixed schemas in one file, an empty completion, and an example
longer than the context it will be trained at. None of these are style; each one is a run that
will finish and be worth nothing.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

# No default. How many examples are enough depends on what is being taught, and a number
# inherited from a tutorial is how a run gets justified by a figure nobody chose.
NOT_EXPOSED = {
    "load":     "reading a file is not a capability on its own; its result is validated by POST /api/symonlora/validate and /deduplicate, and a route that only read a training set back would be a way to fetch any file this unit can open",
    "validate": "routed as POST /api/symonlora/validate",
    "deduplicate": "routed as POST /api/symonlora/deduplicate",
}

SUGGESTED_MINIMUM = 50


class DatasetError(Exception):
    """A training set that will not teach what it is meant to, carrying why."""


def _fingerprint(ex: dict) -> str:
    return hashlib.sha256(json.dumps(ex, sort_keys=True).encode()).hexdigest()[:16]


def _shape(ex: dict) -> str:
    if "messages" in ex:
        return "messages"
    if "prompt" in ex and "completion" in ex:
        return "prompt_completion"
    return "unknown"


def _text_of(ex: dict) -> str:
    if "messages" in ex:
        return "\n".join(str(m.get("content", "")) for m in ex["messages"])
    return str(ex.get("prompt", "")) + "\n" + str(ex.get("completion", ""))


def load(path: str | Path) -> list[dict]:
    """Read a JSONL training set, with the line number on any line that is not an example."""
    p = Path(path)
    if not p.is_file():
        raise DatasetError(f"{p} is not a file")
    rows = []
    for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception as e:
            raise DatasetError(f"{p}:{i} is not json: {e}")
        if not isinstance(d, dict):
            raise DatasetError(f"{p}:{i} is a {type(d).__name__}, not an example object")
        rows.append(d)
    if not rows:
        raise DatasetError(f"{p} has no examples")
    return rows


def validate(rows: list[dict], *, minimum: int = SUGGESTED_MINIMUM,
             max_chars: int | None = None) -> dict[str, Any]:
    """Everything wrong with a training set, found before the card is taken."""
    if not rows:
        raise DatasetError("an empty set teaches nothing")

    shapes = Counter(_shape(r) for r in rows)
    problems: list[dict[str, Any]] = []

    unknown = shapes.get("unknown", 0)
    if unknown:
        bad = next(i for i, r in enumerate(rows, 1) if _shape(r) == "unknown")
        problems.append({"kind": "shape", "count": unknown,
                         "why": f"{unknown} examples are neither {{messages: [...]}} nor "
                                f"{{prompt, completion}}; the first is example {bad}"})
    if len([s for s in shapes if s != "unknown"]) > 1:
        problems.append({"kind": "mixed_shape", "count": len(rows),
                         "why": f"two schemas in one file ({', '.join(sorted(shapes))}); a "
                                f"loader will read one and silently drop the other"})

    fps = Counter(_fingerprint(r) for r in rows)
    dupes = {f: n for f, n in fps.items() if n > 1}
    if dupes:
        worst = max(dupes.values())
        problems.append({"kind": "duplicates", "count": sum(dupes.values()) - len(dupes),
                         "why": f"{len(dupes)} examples appear more than once, one of them "
                                f"{worst} times. A repeated example is that answer weighted "
                                f"{worst} times, and the loss curve looks excellent while it "
                                f"happens"})

    empty = sum(1 for r in rows if not _text_of(r).strip())
    if empty:
        problems.append({"kind": "empty", "count": empty,
                         "why": f"{empty} examples have no text"})

    lengths = [len(_text_of(r)) for r in rows]
    if max_chars:
        over = [i for i, n in enumerate(lengths, 1) if n > max_chars]
        if over:
            problems.append({"kind": "too_long", "count": len(over),
                             "why": f"{len(over)} examples exceed {max_chars} characters and "
                                    f"will be truncated mid-example, teaching a cut-off answer"})

    if len(rows) < minimum:
        problems.append({"kind": "too_few", "count": len(rows),
                         "why": f"{len(rows)} examples against a stated minimum of {minimum}"})

    lengths.sort()
    stats = {
        "examples": len(rows), "unique": len(fps),
        "shapes": dict(shapes),
        "characters": {"total": sum(lengths), "min": lengths[0], "max": lengths[-1],
                       "median": lengths[len(lengths) // 2],
                       "mean": round(sum(lengths) / len(lengths), 1)},
    }
    return {"ok": not problems, "problems": problems, "stats": stats,
            "verdict": "usable" if not problems else "refused",
            "why": ("nothing found that would make this train badly" if not problems else
                    "; ".join(p["why"] for p in problems))}


def deduplicate(rows: list[dict]) -> dict[str, Any]:
    """Return the set with duplicates removed, and say exactly what was dropped.

    Offered rather than done automatically. Removing duplicates changes what is being taught,
    and a tool that quietly rewrites a training set is a tool that decides the experiment.
    """
    seen: set[str] = set()
    kept, dropped = [], []
    for r in rows:
        f = _fingerprint(r)
        if f in seen:
            dropped.append(f)
            continue
        seen.add(f)
        kept.append(r)
    return {"kept": kept, "dropped": len(dropped), "before": len(rows), "after": len(kept),
            "note": "offered, not applied — removing duplicates changes what is taught"}
