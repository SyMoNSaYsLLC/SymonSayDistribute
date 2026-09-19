# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What a serving runtime actually offers, asked of the runtime rather than of its docs.

WHY THIS IS NOT A DOCUMENTATION LOOKUP
--------------------------------------
Finding which tool-call parsers a vLLM offers took, on 2026-09-19: a failed import of
`vllm.entrypoints.openai.tool_parsers` (moved in this version), an empty registry (parsers
register lazily, so importing the package lists nothing), an rglob for files called
`*tool_parser*`, and finally reading the lazy-module dict out of `__init__.py` by line number.

The answer — `openai` and `openai_gptoss` — is three lines of a dict. Every step to reach it was
version-specific, and the documentation for a different version would have been confidently
wrong. So this reads the installed package, in its own interpreter, and reports what is there.

Nothing here imports the serving runtime into THIS process. A probe that needs the thing it is
probing already loaded is a probe that cannot describe a broken environment, which is the one
time it is most needed.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

from .device import ProbeError, _venv_python

VENV_ROOTS = ["/home/google/.venvs", "/home/google", "/opt"]


def venvs() -> list[dict[str, Any]]:
    """Python environments on this host, with their interpreter version."""
    out = []
    seen: set[str] = set()
    for root in VENV_ROOTS:
        r = Path(root)
        if not r.is_dir():
            continue
        for cfg in list(r.glob("*/pyvenv.cfg")) + list(r.glob("*/*/pyvenv.cfg")):
            v = cfg.parent
            if str(v) in seen:
                continue
            seen.add(str(v))
            ver = ""
            for line in cfg.read_text(errors="replace").splitlines():
                if line.lower().startswith("version"):
                    ver = line.split("=", 1)[-1].strip()
            out.append({"venv": str(v), "python": ver,
                        "has_python": (v / "bin" / "python").exists()})
    return sorted(out, key=lambda d: d["venv"])


_PKGS = r'''
import json
from importlib.metadata import distributions
rows = []
for d in distributions():
    try:
        rows.append({"name": d.metadata["Name"], "version": d.version})
    except Exception:
        pass
print(json.dumps(sorted([r for r in rows if r["name"]], key=lambda r: (r["name"] or "").lower())))
'''


def packages(venv: str | Path, contains: str = "") -> list[dict[str, str]]:
    """Installed distributions and versions, read from the environment's own metadata."""
    py = _venv_python(venv)
    r = subprocess.run([str(py), "-c", _PKGS], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ProbeError(f"listing packages in {venv} failed rc={r.returncode}: "
                         f"{r.stderr.strip()[-200:]}")
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    if contains:
        c = contains.lower()
        rows = [x for x in rows if c in (x["name"] or "").lower()]
    return rows


def _lazy_registry(pkg_init: Path) -> list[str]:
    """Read the names out of a lazy-registration dict without importing anything.

    vLLM registers parsers as {name: (module, class)} in a package __init__. Importing the
    package does NOT populate the manager — that is what made this hard to find by hand — so
    the names are parsed out of the source instead. Static reading also means a package that
    cannot import still reports what it would offer.
    """
    if not pkg_init.is_file():
        return []
    try:
        tree = ast.parse(pkg_init.read_text(errors="replace"))
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and isinstance(v, ast.Tuple) and len(v.elts) == 2
                        and all(isinstance(e, ast.Constant) for e in v.elts)):
                    names.add(k.value)
    return sorted(names)


def parsers(venv: str | Path) -> dict[str, Any]:
    """Which tool-call and reasoning parsers a serving runtime offers, by registered NAME.

    The registered name is what a launcher flag takes. A file name is not it: the parser in
    `gptoss_tool_parser.py` is selected as `openai`, and guessing from the filename gives a
    flag the server rejects.
    """
    py = _venv_python(venv)
    r = subprocess.run([str(py), "-c",
                        "import vllm,pathlib;print(pathlib.Path(vllm.__file__).parent)"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ProbeError(f"{venv} has no importable vllm: {r.stderr.strip()[-200:]}")
    root = Path(r.stdout.strip().splitlines()[-1])
    ver = subprocess.run([str(py), "-c", "import vllm;print(vllm.__version__)"],
                         capture_output=True, text=True, timeout=120).stdout.strip()

    tool = _lazy_registry(root / "tool_parsers" / "__init__.py") or \
        _lazy_registry(root / "entrypoints" / "openai" / "tool_parsers" / "__init__.py")
    reason = _lazy_registry(root / "reasoning" / "__init__.py")
    return {
        "venv": str(venv), "runtime": "vllm", "version": ver, "package_root": str(root),
        "tool_call_parsers": tool, "reasoning_parsers": reason,
        "counts": {"tool_call": len(tool), "reasoning": len(reason)},
        "read_how": "parsed statically out of the lazy-registration dicts; importing the "
                    "package does not populate the manager, which is what makes these hard "
                    "to find by hand",
    }


def suggest(venv: str | Path, model_dir: str) -> dict[str, Any]:
    """Which parser names suit a checkpoint, and the evidence for the guess.

    It says `candidates`, never `answer`. Matching a checkpoint to a parser is a judgement, and
    a wrong flag is rejected loudly by the server, which is the right place to find out — better
    than this module asserting one and being believed.
    """
    p = parsers(venv)
    name = Path(model_dir).name.lower()
    cfg = Path(model_dir) / "config.json"
    arch = ""
    if cfg.is_file():
        try:
            arch = " ".join(json.loads(cfg.read_text()).get("architectures", [])).lower()
        except Exception:
            arch = ""
    hay = f"{name} {arch}"
    hints = {"gpt-oss": ("openai", "openai_gptoss"), "gptoss": ("openai", "openai_gptoss"),
             "mistral": ("mistral", None), "hermes": ("hermes", None),
             "deepseek": ("deepseek_v3", "deepseek_r1"), "qwen": ("hermes", "qwen3_engine")}
    hit = next((v for k, v in hints.items() if k in hay), None)
    return {
        "model_dir": model_dir, "matched_on": hay.strip() or "(nothing readable)",
        "candidates": {
            "tool_call_parser": hit[0] if hit and hit[0] in p["tool_call_parsers"] else None,
            "reasoning_parser": hit[1] if hit and hit[1] in p["reasoning_parsers"] else None,
        },
        "available": {"tool_call": p["tool_call_parsers"], "reasoning": p["reasoning_parsers"]},
        "caveat": "candidates, not an answer. A wrong parser name is rejected by the server at "
                  "start-up, which is a better place to learn it than here.",
    }
