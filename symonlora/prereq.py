# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What is missing before a run can start, named rather than discovered at hour two.

A LoRA run fails late by default. The packages are imported after the data is loaded and the
model is on the card, so a missing one costs the setup before it says anything. This asks first,
in the environment that would actually run it, and names every missing piece at once instead of
one per attempt.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

# What a LoRA run needs, and what each is for — so a missing one is a sentence rather than a
# name to look up.
NEEDED = {
    "torch":        "the tensors and the device",
    "transformers": "loading the checkpoint and its tokenizer",
    "peft":         "the LoRA itself: injecting the adapters and saving only them",
    "datasets":     "streaming the training set without holding it all in memory",
    "accelerate":   "the training loop's device placement",
    "trl":          "supervised fine-tuning on chat-shaped examples (optional if the loop "
                    "is written by hand)",
}
OPTIONAL = {"trl"}

NOT_EXPOSED = {
    "check": "routed as GET /api/symonlora/prereq",
}

_PROBE = """
import json, importlib.util as u
print(json.dumps({m: (u.find_spec(m) is not None) for m in %r}))
"""


class PrereqError(Exception):
    """Prerequisites could not be established, carrying why."""


def check(venv: str | Path) -> dict[str, Any]:
    """Which packages a run needs, which are present, and the command that fixes it."""
    py = Path(venv) / "bin" / "python"
    if not py.exists():
        raise PrereqError(f"{venv} has no bin/python; it is not a python environment")
    r = subprocess.run([str(py), "-c", _PROBE % list(NEEDED)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise PrereqError(f"probing {venv} failed rc={r.returncode}: {r.stderr.strip()[-200:]}")
    have = json.loads(r.stdout.strip().splitlines()[-1])
    missing = [m for m, ok in have.items() if not ok and m not in OPTIONAL]
    optional_missing = [m for m, ok in have.items() if not ok and m in OPTIONAL]
    return {
        "venv": str(venv),
        "present": sorted(m for m, ok in have.items() if ok),
        "missing": missing,
        "missing_why": {m: NEEDED[m] for m in missing},
        "optional_missing": optional_missing,
        "ready": not missing,
        "install": (f"{py} -m pip install " + " ".join(missing)) if missing else None,
        "note": ("nothing to install" if not missing else
                 "this is an install on Garrett's machine, so it is named rather than done"),
    }
