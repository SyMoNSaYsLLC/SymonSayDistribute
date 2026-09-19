# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Tests for the model arithmetic.

The important ones are the REFUSALS. A sizing function that quietly substitutes a default
for a missing input is worse than one that fails, because the number it returns looks
exactly like a real answer. Each refusal here is a case that produced a wrong figure when
it was done by hand.
"""
import json
import pytest
from symoneural_ravencalc import model

# A minimal config in the shape the real checkpoint uses: grouped-query attention and
# alternating sliding/full layers. Both are what make the naive cache estimate wrong.
CFG = {
    "num_hidden_layers": 4,
    "num_attention_heads": 64,
    "num_key_value_heads": 8,
    "head_dim": 64,
    "sliding_window": 128,
    "layer_types": ["sliding_attention", "full_attention", "sliding_attention", "full_attention"],
    "num_local_experts": 32,
    "num_experts_per_tok": 4,
}


def test_cache_is_sized_by_kv_heads_not_attention_heads():
    kv = model.kv_cache(CFG, context=1024)
    # 2 (K and V) * 8 kv heads * 64 head_dim * 2 bytes
    assert kv["bytes_per_position_per_layer"] == 2 * 8 * 64 * 2
    # using the 64 attention heads would be eight times larger
    assert kv["bytes_per_position_per_layer"] * 8 == 2 * 64 * 64 * 2


def test_sliding_layers_never_cache_more_than_the_window():
    kv = model.kv_cache(CFG, context=16384)
    sliding = kv["per_layer_type"]["sliding_attention"]
    full = kv["per_layer_type"]["full_attention"]
    assert sliding["positions_cached"] == 128
    assert full["positions_cached"] == 16384
    # the two sliding layers cost the same at any context past the window
    assert model.kv_cache(CFG, 999999)["per_layer_type"]["sliding_attention"]["bytes"] == sliding["bytes"]


def test_cache_scales_with_sequences():
    one = model.kv_cache(CFG, 4096, sequences=1)
    four = model.kv_cache(CFG, 4096, sequences=4)
    assert four["bytes_total"] == one["bytes_total"] * 4
    assert four["bytes_per_sequence"] == one["bytes_per_sequence"]


def test_refuses_a_config_missing_what_it_needs():
    for key in ("num_hidden_layers", "num_key_value_heads", "head_dim"):
        bad = {k: v for k, v in CFG.items() if k != key}
        with pytest.raises(model.ModelReadError):
            model.kv_cache(bad, 1024)


def test_refuses_a_sliding_layer_with_no_window_declared():
    bad = {k: v for k, v in CFG.items() if k != "sliding_window"}
    with pytest.raises(model.ModelReadError):
        model.kv_cache(bad, 1024)


def test_refuses_layer_types_that_do_not_match_the_layer_count():
    bad = dict(CFG, layer_types=["full_attention"] * 3)
    with pytest.raises(model.ModelReadError):
        model.kv_cache(bad, 1024)


def test_refuses_nonsense_context_or_concurrency():
    for ctx, seqs in ((0, 1), (-1, 1), (1024, 0)):
        with pytest.raises(model.ModelReadError):
            model.kv_cache(CFG, ctx, seqs)


def test_transfer_has_no_default_bandwidth():
    # a plausible constant here would manufacture a token rate with nothing behind it
    assert model.transfer_ms(1_000_000_000, 1_000_000_000) == pytest.approx(1000.0)
    for bad in (0, -1):
        with pytest.raises(model.ModelReadError):
            model.transfer_ms(1000, bad)


def test_refuses_a_directory_with_no_tensors(tmp_path):
    with pytest.raises(model.ModelReadError):
        model.read_tensors(tmp_path)
    with pytest.raises(model.ModelReadError):
        model.read_tensors(tmp_path / "does-not-exist")


def test_refuses_more_active_experts_than_exist(tmp_path):
    bad = dict(CFG, num_experts_per_tok=64)
    with pytest.raises(model.ModelReadError):
        model.expert_residency(tmp_path, bad)
