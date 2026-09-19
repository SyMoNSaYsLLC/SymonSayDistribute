# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Planning a LoRA run against the checkpoint that will actually be trained.

EVERY NUMBER COMES FROM THE CHECKPOINT
--------------------------------------
Adapter size depends on the shapes of the modules being adapted, and those are in config.json.
Guessing them from a parameter count is how a plan says a run fits and the run then does not.

On symon that matters more than usual. It has 64 attention heads but only 8 key/value heads, so
`k_proj` and `v_proj` are EIGHT TIMES smaller than `q_proj` — an adapter sized as though all
four projections matched would be more than twice the real figure. And its MXFP4 quantization
explicitly does not convert attention, which is the normal place to put a LoRA, so those
modules are full precision and adaptable.

WHAT THIS REFUSES
-----------------
To produce a plan for a checkpoint it cannot read, to target a module the architecture does not
have, and to say a run fits when the arithmetic says it does not. It also refuses to invent the
one number it cannot derive: how much memory the activations take, which depends on batch and
sequence length and is measured, not calculated from a config.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Attention projections, which is where a LoRA normally goes. Named per role rather than by a
# fixed list of strings, because the shapes differ and that is the whole point.
NOT_EXPOSED = {
    "read_config":    "the raw config of somebody else's checkpoint; its DERIVED results are served by POST /api/symonlora/plan and /modules. Serving the file back would publish a third party's metadata through our surface",
    "module_shapes":  "served as POST /api/symonlora/modules",
    "adapter_params": "served inside POST /api/symonlora/plan, under memory.adapter — the parameter count and what it costs are one answer, and splitting them invites a caller to size a run from the count alone",
    "memory":         "served inside POST /api/symonlora/plan",
}

ATTENTION = ("q_proj", "k_proj", "v_proj", "o_proj")

BYTES = {"fp32": 4, "bf16": 2, "fp16": 2}


class PlanError(Exception):
    """A plan that could not be made, carrying why."""


def read_config(model_dir: str | Path) -> dict[str, Any]:
    p = Path(model_dir) / "config.json"
    if not p.is_file():
        raise PlanError(f"{model_dir} has no config.json; a plan built without one is a guess")
    try:
        c = json.loads(p.read_text())
    except Exception as e:
        raise PlanError(f"{p} is not readable json: {e}")
    need = ("num_hidden_layers", "hidden_size")
    missing = [k for k in need if k not in c]
    if missing:
        raise PlanError(f"{p} does not declare {', '.join(missing)}")
    return c


def module_shapes(cfg: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """The (in, out) shape of each adaptable attention module, from the config.

    Grouped-query attention is the reason this is computed rather than assumed: q_proj is
    num_attention_heads * head_dim wide, k_proj and v_proj are num_key_value_heads * head_dim.
    On symon that is 4096 against 512.
    """
    h = int(cfg["hidden_size"])
    heads = int(cfg.get("num_attention_heads") or 0)
    kv = int(cfg.get("num_key_value_heads") or heads)
    hd = int(cfg.get("head_dim") or (h // heads if heads else 0))
    if not (heads and hd):
        raise PlanError("the config does not declare attention head shapes, so adapter size "
                        "cannot be derived")
    q_out, kv_out = heads * hd, kv * hd
    return {"q_proj": (h, q_out), "k_proj": (h, kv_out),
            "v_proj": (h, kv_out), "o_proj": (q_out, h)}


def adapter_params(cfg: dict[str, Any], *, rank: int, targets: tuple[str, ...] = ATTENTION
                   ) -> dict[str, Any]:
    """How many trainable parameters a LoRA of this rank adds, per module and in total."""
    if rank <= 0:
        raise PlanError("rank must be positive")
    shapes = module_shapes(cfg)
    unknown = [t for t in targets if t not in shapes]
    if unknown:
        raise PlanError(f"this architecture has no {', '.join(unknown)}; adaptable modules are "
                        f"{', '.join(sorted(shapes))}")
    layers = int(cfg["num_hidden_layers"])
    per_layer, rows = 0, []
    for t in targets:
        i, o = shapes[t]
        n = rank * (i + o)          # A is r x in, B is out x r
        per_layer += n
        rows.append({"module": t, "in": i, "out": o, "params_per_layer": n})
    total = per_layer * layers
    return {"rank": rank, "targets": list(targets), "layers": layers,
            "per_layer": per_layer, "total": total,
            "modules": rows,
            "note": "A is rank x in and B is out x rank, so a module contributes "
                    "rank * (in + out) per layer"}


def memory(cfg: dict[str, Any], *, rank: int, targets: tuple[str, ...] = ATTENTION,
           dtype: str = "bf16", optimizer: str = "adamw") -> dict[str, Any]:
    """What the trainable side costs. Activations are NOT included, and it says so.

    Adapter weights, their gradients and the optimizer state are all derivable from shapes.
    Activation memory is not — it depends on batch size, sequence length and whether checkpoint
    recomputation is on, and it is measured. A plan that folded in a guessed activation figure
    would be the kind of confident wrong number this estate exists to refuse.
    """
    if dtype not in BYTES:
        raise PlanError(f"{dtype!r} is not a dtype this plans for: {', '.join(BYTES)}")
    # adamw keeps two moments; sgd with momentum keeps one; plain sgd keeps none
    states = {"adamw": 2, "sgd_momentum": 1, "sgd": 0}
    if optimizer not in states:
        raise PlanError(f"{optimizer!r} is not an optimizer this plans for: "
                        f"{', '.join(states)}")
    a = adapter_params(cfg, rank=rank, targets=targets)
    w = a["total"] * BYTES[dtype]
    g = a["total"] * BYTES[dtype]
    # optimizer moments are kept in fp32 by every implementation that matters
    o = a["total"] * 4 * states[optimizer]
    total = w + g + o
    return {"trainable_params": a["total"], "dtype": dtype, "optimizer": optimizer,
            "adapter_weights_bytes": w, "gradients_bytes": g, "optimizer_state_bytes": o,
            "trainable_total_bytes": total,
            "trainable_total_mib": round(total / (1 << 20), 2),
            "excludes": ["the frozen base weights, which are already on the card when serving",
                         "activations, which depend on batch and sequence length and are "
                         "MEASURED — this refuses to guess them"],
            "adapter": a}


def plan(model_dir: str | Path, *, rank: int = 16, alpha: int | None = None,
         targets: tuple[str, ...] = ATTENTION, dtype: str = "bf16",
         optimizer: str = "adamw", free_bytes: int | None = None) -> dict[str, Any]:
    """A complete plan, and a fit verdict only when free memory was actually supplied."""
    cfg = read_config(model_dir)
    m = memory(cfg, rank=rank, targets=targets, dtype=dtype, optimizer=optimizer)
    out: dict[str, Any] = {
        "model_dir": str(model_dir),
        "architecture": (cfg.get("architectures") or ["unknown"])[0],
        "rank": rank, "alpha": alpha if alpha is not None else rank * 2,
        "alpha_note": "alpha defaults to twice the rank, the common convention; it scales the "
                      "adapter's contribution and is not derived from anything here",
        "quantization": (cfg.get("quantization_config") or {}).get("quant_method"),
        "memory": m,
    }
    q = cfg.get("quantization_config") or {}
    skip = q.get("modules_to_not_convert") or []
    if q and any("self_attn" in s for s in skip):
        out["quantization_note"] = (
            "the checkpoint is quantized but explicitly does NOT convert attention, which is "
            "where these targets live — so they are full precision and adaptable")
    if free_bytes is None:
        out["fits"] = None
        out["fits_why"] = ("no free-memory figure was supplied, so no verdict is given. The "
                           "card's free memory is measured, not assumed, and a fit claimed "
                           "against an assumed figure is worse than no claim")
    else:
        out["free_bytes"] = free_bytes
        out["fits"] = m["trainable_total_bytes"] < free_bytes
        out["fits_why"] = (
            f"the trainable side is {m['trainable_total_mib']} MiB against "
            f"{round(free_bytes / (1 << 20), 1)} MiB free. This EXCLUDES activations, so a "
            f"true here means 'not ruled out', never 'will fit'")
    return out
