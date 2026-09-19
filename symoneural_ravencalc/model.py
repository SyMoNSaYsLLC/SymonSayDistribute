# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""RavenCalc model arithmetic — what a checkpoint costs, derived from the checkpoint.

Sizing a model is arithmetic, and arithmetic in this estate is RavenCalc's job. It was
being done in throwaway interpreter one-liners instead: the numbers had no route, no
record, no version and no way to reproduce them, which is exactly the failure mode the
runtime exists to prevent.

EVERY NUMBER HERE COMES OFF DISK
--------------------------------
Tensor sizes are read from the safetensors header — the real dtype and shape of every
tensor, not a parameter count multiplied by an assumed width. Layer geometry comes from
config.json. Nothing is inferred from a model's name or its advertised size.

WHAT IT REFUSES TO DO
---------------------
It will not estimate. A quantity that cannot be derived from the files is an argument the
caller must supply, and if it is missing the function raises rather than guessing. Bus
bandwidth is the clearest case: it is a property of the machine, not of the checkpoint, so
`transfer_ms` takes a measured figure and there is no default. A default there would have
produced a confident token-rate number with nothing behind it.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# safetensors dtype -> bytes per element. From the format's own specification.
_DTYPE_BYTES = {
    "BOOL": 1, "U8": 1, "I8": 1, "F8_E4M3": 1, "F8_E5M2": 1,
    "I16": 2, "U16": 2, "F16": 2, "BF16": 2,
    "I32": 4, "U32": 4, "F32": 4,
    "I64": 8, "U64": 8, "F64": 8,
}


class ModelReadError(Exception):
    """The checkpoint could not be read, or does not carry what was asked for."""


@dataclass(slots=True)
class Tensor:
    name: str
    dtype: str
    shape: list[int]
    bytes: int


def read_tensors(model_dir: str | Path) -> list[Tensor]:
    """Every tensor in a checkpoint, with its exact on-disk size.

    The safetensors header is a length-prefixed JSON object at the start of each shard:
    eight bytes of little-endian length, then that many bytes of JSON mapping tensor name
    to dtype, shape and byte offsets. The size is `end - start` — the file's own answer,
    which is why this does not multiply a shape by an assumed element width.
    """
    d = Path(model_dir)
    if not d.is_dir():
        raise ModelReadError(f"not a directory: {d}")
    shards = sorted(d.glob("*.safetensors"))
    if not shards:
        raise ModelReadError(f"no .safetensors in {d}")
    out: list[Tensor] = []
    for shard in shards:
        with shard.open("rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                raise ModelReadError(f"{shard.name}: truncated header length")
            (n,) = struct.unpack("<Q", raw)
            head = json.loads(f.read(n))
        for name, meta in head.items():
            if name == "__metadata__":
                continue
            offs = meta.get("data_offsets")
            if not offs or len(offs) != 2:
                continue
            out.append(Tensor(name=name, dtype=meta.get("dtype", "?"),
                              shape=list(meta.get("shape", [])), bytes=offs[1] - offs[0]))
    return out


def kv_cache(config: dict, context: int, sequences: int = 1, bytes_per_element: int = 2) -> dict[str, Any]:
    """Bytes of key/value cache for a given context and concurrency.

    Two things decide this and both are read from the config rather than assumed:

    GROUPED-QUERY ATTENTION. The cache is sized by `num_key_value_heads`, not by
    `num_attention_heads`. Using the attention-head count is the common error and here it
    would overstate the result eightfold.

    PER-LAYER ATTENTION TYPE. `layer_types` may mark some layers sliding-window, and a
    sliding layer never caches more than `sliding_window` positions however long the
    context is. Treating every layer as full attention is the other common error.
    """
    need = ("num_hidden_layers", "num_key_value_heads", "head_dim")
    missing = [k for k in need if k not in config]
    if missing:
        raise ModelReadError(f"config lacks {missing} — cannot size the cache without them")
    if context < 1 or sequences < 1:
        raise ModelReadError("context and sequences are both at least 1")

    layers = config["num_hidden_layers"]
    per_pos_per_layer = 2 * config["num_key_value_heads"] * config["head_dim"] * bytes_per_element

    types = config.get("layer_types") or ["full_attention"] * layers
    if len(types) != layers:
        raise ModelReadError(f"layer_types has {len(types)} entries for {layers} layers")
    window = config.get("sliding_window")

    per_type: dict[str, dict[str, int]] = {}
    total = 0
    for t in types:
        if "sliding" in t:
            if not window:
                raise ModelReadError("a sliding layer is declared but sliding_window is unset")
            positions = min(context, window)
        else:
            positions = context
        b = per_pos_per_layer * positions
        total += b
        row = per_type.setdefault(t, {"layers": 0, "positions_cached": positions, "bytes": 0})
        row["layers"] += 1
        row["bytes"] += b

    return {
        "context": context, "sequences": sequences,
        "bytes_per_element": bytes_per_element,
        "kv_heads": config["num_key_value_heads"], "head_dim": config["head_dim"],
        "bytes_per_position_per_layer": per_pos_per_layer,
        "per_layer_type": per_type,
        "bytes_per_sequence": total,
        "bytes_total": total * sequences,
        "mib_per_sequence": round(total / (1 << 20), 2),
        "mib_total": round(total * sequences / (1 << 20), 2),
    }


def expert_residency(model_dir: str | Path, config: dict) -> dict[str, Any]:
    """What the mixture-of-experts weights cost, and what one token actually touches.

    The question a 16 GB card asks is not "how big is the model" but "how much must be
    resident to produce one token". For a sparse mixture that is the routed experts only,
    and the gap between the two is the whole argument for paging.
    """
    for k in ("num_local_experts", "num_experts_per_tok", "num_hidden_layers"):
        if k not in config:
            raise ModelReadError(f"config lacks {k} — not a routed mixture, or not declared")

    tensors = read_tensors(model_dir)
    expert_bytes = sum(t.bytes for t in tensors if ".mlp.experts." in t.name)
    router_bytes = sum(t.bytes for t in tensors if ".mlp.router." in t.name)
    attn_bytes = sum(t.bytes for t in tensors if ".self_attn." in t.name)
    other_bytes = sum(t.bytes for t in tensors) - expert_bytes - router_bytes - attn_bytes

    n_exp = config["num_local_experts"]
    n_act = config["num_experts_per_tok"]
    layers = config["num_hidden_layers"]
    if n_act > n_exp:
        raise ModelReadError(f"{n_act} experts active of {n_exp} available is not possible")

    per_expert_per_layer = expert_bytes / (n_exp * layers)
    active_per_token = per_expert_per_layer * n_act * layers
    always_resident = router_bytes + attn_bytes + other_bytes

    return {
        "experts_total": n_exp, "experts_active_per_token": n_act, "layers": layers,
        "bytes_all_experts": expert_bytes,
        "bytes_per_expert_per_layer": round(per_expert_per_layer),
        "bytes_active_per_token": round(active_per_token),
        "bytes_always_resident": always_resident,
        "gib_all_experts": round(expert_bytes / (1 << 30), 3),
        "gib_active_per_token": round(active_per_token / (1 << 30), 3),
        "gib_always_resident": round(always_resident / (1 << 30), 3),
        "sparsity": round(n_act / n_exp, 4),
    }


def transfer_ms(nbytes: int, bandwidth_bytes_per_s: float) -> float:
    """Milliseconds to move nbytes at a MEASURED bandwidth.

    There is deliberately no default bandwidth. It is a property of the machine and the
    moment, not of the checkpoint, and a plausible constant here would manufacture a
    token-rate figure with nothing behind it.
    """
    if bandwidth_bytes_per_s <= 0:
        raise ModelReadError("bandwidth must be measured and positive — there is no default")
    if nbytes < 0:
        raise ModelReadError("bytes cannot be negative")
    return (nbytes / bandwidth_bytes_per_s) * 1000.0


def budget(config: dict, model_dir: str | Path, vram_bytes: int, context: int,
           sequences: int = 1, bytes_per_element: int = 2) -> dict[str, Any]:
    """Does it fit? Weights plus cache against a real card, with the shortfall named."""
    kv = kv_cache(config, context, sequences, bytes_per_element)
    ex = expert_residency(model_dir, config)
    resident_min = ex["bytes_always_resident"] + ex["bytes_active_per_token"] + kv["bytes_total"]
    resident_all = ex["bytes_always_resident"] + ex["bytes_all_experts"] + kv["bytes_total"]
    return {
        "vram_bytes": vram_bytes,
        "vram_gib": round(vram_bytes / (1 << 30), 2),
        "minimum_resident_bytes": resident_min,
        "minimum_resident_gib": round(resident_min / (1 << 30), 3),
        "everything_resident_bytes": resident_all,
        "everything_resident_gib": round(resident_all / (1 << 30), 3),
        "fits_minimum": resident_min <= vram_bytes,
        "fits_everything": resident_all <= vram_bytes,
        "headroom_minimum_gib": round((vram_bytes - resident_min) / (1 << 30), 3),
        "shortfall_everything_gib": round(max(0, resident_all - vram_bytes) / (1 << 30), 3),
        "kv": kv, "experts": ex,
    }


def gpu_fraction(total_bytes: int, free_bytes: int, required_bytes: int,
                 *, reserve_bytes: int, ceiling: float) -> dict[str, Any]:
    """The share of the card an engine may take, derived rather than chosen.

    This is the estate's most load-bearing single calculation and it lived in a shell script
    as `min(0.917, (free - 600)/total)` shelled to a throwaway interpreter, with the ceiling
    and the reserve written into the expression. Two things followed: the launcher that falls
    back defaults to a DIFFERENT figure (0.90), and no test ever compared them.

    Both knobs are arguments here, with no defaults, because they are policy about this
    machine and not properties of the model:

      reserve_bytes  what must stay free for everything that is not the engine — the
                     compositor, the display server, anything else holding the card
      ceiling        the highest share to take even when more is free, so an engine that
                     measures at a quiet moment does not claim memory something else is
                     about to want back

    `fits` answers the question the fraction alone cannot: whether what the model actually
    needs is available after the reserve. A fraction can be perfectly computed and still name
    less memory than the model requires.
    """
    if total_bytes <= 0 or free_bytes < 0:
        raise ModelReadError("total and free must be measured from the device")
    if free_bytes > total_bytes:
        raise ModelReadError(f"free {free_bytes} exceeds total {total_bytes} — not a measurement")
    if not (0 < ceiling <= 1.0):
        raise ModelReadError("ceiling is a share of the card, in (0, 1]")
    if reserve_bytes < 0:
        raise ModelReadError("reserve cannot be negative")

    usable = free_bytes - reserve_bytes
    if usable <= 0:
        raise ModelReadError(
            f"reserve {reserve_bytes} leaves nothing of {free_bytes} free — nothing can be served")

    raw = usable / total_bytes
    fraction = min(ceiling, raw)
    granted = int(fraction * total_bytes)
    return {
        "total_bytes": total_bytes, "free_bytes": free_bytes,
        "reserve_bytes": reserve_bytes, "ceiling": ceiling,
        "usable_bytes": usable,
        "fraction_uncapped": round(raw, 4),
        "fraction": round(fraction, 3),
        "capped_by_ceiling": fraction < raw,
        "granted_bytes": granted,
        "required_bytes": required_bytes,
        "fits": required_bytes <= granted,
        "headroom_bytes": granted - required_bytes,
        "headroom_gib": round((granted - required_bytes) / (1 << 30), 3),
    }
