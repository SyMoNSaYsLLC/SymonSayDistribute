# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonlora tests. The arithmetic and the refusals, because a LoRA fails by finishing cleanly
and making the model worse — and every cause of that is visible before the run starts."""
import importlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from symonlora import dataset as D
from symonlora import plan as P
from symonlora import prereq as Q

TOKEN = uuid.uuid4().hex
SYMON = "/models/symon"

# A grouped-query config: 64 attention heads, 8 key/value heads. The whole point of deriving
# shapes rather than assuming them.
GQA = {"architectures": ["TestForCausalLM"], "num_hidden_layers": 2, "hidden_size": 2880,
       "num_attention_heads": 64, "num_key_value_heads": 8, "head_dim": 64}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SYM_LORA_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- the arithmetic ------------------------------------------------------------------
def test_grouped_query_makes_kv_projections_smaller_not_equal():
    s = P.module_shapes(GQA)
    assert s["q_proj"][1] == 64 * 64
    assert s["k_proj"][1] == 8 * 64 == s["v_proj"][1]
    assert s["k_proj"][1] * 8 == s["q_proj"][1]


def test_adapter_params_are_rank_times_in_plus_out_per_layer():
    a = P.adapter_params(GQA, rank=16)
    q = 16 * (2880 + 4096)
    k = 16 * (2880 + 512)
    assert a["per_layer"] == q + k + k + 16 * (4096 + 2880)
    assert a["total"] == a["per_layer"] * 2


def test_doubling_the_rank_doubles_the_trainable_parameters():
    a = P.adapter_params(GQA, rank=8)["total"]
    b = P.adapter_params(GQA, rank=16)["total"]
    assert b == 2 * a


def test_adamw_costs_more_than_sgd_and_the_difference_is_the_moments():
    m_adam = P.memory(GQA, rank=16, optimizer="adamw")
    m_sgd = P.memory(GQA, rank=16, optimizer="sgd")
    assert m_sgd["optimizer_state_bytes"] == 0
    assert m_adam["optimizer_state_bytes"] == m_adam["trainable_params"] * 4 * 2


# --- refusals ------------------------------------------------------------------------
def test_a_checkpoint_with_no_config_is_refused(tmp_path):
    with pytest.raises(P.PlanError, match="no config.json"):
        P.read_config(tmp_path)


def test_a_module_the_architecture_does_not_have_is_refused_by_name():
    with pytest.raises(P.PlanError, match="no gate_proj"):
        P.adapter_params(GQA, rank=8, targets=("gate_proj",))


def test_a_config_without_head_shapes_cannot_size_an_adapter():
    with pytest.raises(P.PlanError, match="does not declare attention head shapes"):
        P.module_shapes({"hidden_size": 100, "num_hidden_layers": 2})


def test_no_fit_verdict_is_given_without_a_measured_free_figure():
    p = P.plan(SYMON, rank=8)
    assert p["fits"] is None and "measured, not assumed" in p["fits_why"]


def test_a_fit_verdict_says_it_excludes_activations():
    p = P.plan(SYMON, rank=8, free_bytes=8 << 30)
    assert p["fits"] is True
    assert "EXCLUDES activations" in p["fits_why"] and "never 'will fit'" in p["fits_why"]


def test_memory_names_what_it_leaves_out():
    m = P.memory(GQA, rank=16)
    joined = " ".join(m["excludes"])
    assert "activations" in joined and "MEASURED" in joined


# --- the real checkpoint --------------------------------------------------------------
def test_symons_quantization_does_not_cover_the_modules_being_adapted():
    p = P.plan(SYMON, rank=16)
    assert p["quantization"] == "mxfp4"
    assert "does NOT convert attention" in p["quantization_note"]


# --- the training set -----------------------------------------------------------------
def test_duplicates_are_refused_and_the_worst_count_is_named():
    rows = [{"prompt": "a", "completion": "b"}] * 4 + [{"prompt": "c", "completion": "d"}]
    v = D.validate(rows, minimum=1)
    dup = next(p for p in v["problems"] if p["kind"] == "duplicates")
    assert "4 times" in dup["why"] and v["ok"] is False


def test_two_schemas_in_one_file_are_refused():
    rows = [{"prompt": "a", "completion": "b"}, {"messages": [{"content": "x"}]}]
    v = D.validate(rows, minimum=1)
    assert any(p["kind"] == "mixed_shape" for p in v["problems"])


def test_a_clean_set_passes_and_says_why():
    rows = [{"prompt": f"q{i}", "completion": f"a{i}"} for i in range(60)]
    v = D.validate(rows)
    assert v["ok"] is True and "train badly" in v["why"]


def test_deduplicate_is_offered_and_not_applied():
    rows = [{"prompt": "a", "completion": "b"}] * 3
    out = D.deduplicate(rows)
    assert out["after"] == 1 and out["dropped"] == 2
    assert "not applied" in out["note"]


def test_a_non_json_line_is_refused_with_its_line_number(tmp_path):
    f = tmp_path / "d.jsonl"
    f.write_text('{"prompt":"a","completion":"b"}\nnot json at all\n')
    with pytest.raises(D.DatasetError, match=":2 is not json"):
        D.load(f)


# --- prerequisites ---------------------------------------------------------------------
def test_prereq_names_every_missing_package_at_once_with_an_install_line():
    c = Q.check("/home/google/.venvs/vllm-0271-cu130")
    assert c["ready"] is False
    assert set(c["missing"]) >= {"peft"}
    assert c["install"] and "pip install" in c["install"]
    assert all(m in c["missing_why"] for m in c["missing"])


def test_a_directory_that_is_not_an_environment_is_refused(tmp_path):
    with pytest.raises(Q.PrereqError, match="not a python environment"):
        Q.check(tmp_path)


# --- over http ---------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    monkeypatch.delenv("SYM_LORA_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonlora/health").status_code == 200
    assert c.get("/api/symonlora/prereq?venv=/x").status_code == 503


def test_there_is_no_train_route(client):
    import service
    paths = {r.path for r in service.app.routes if hasattr(r, "methods")}
    assert not any("train" in p for p in paths), \
        "a train route would be a promise this unit cannot keep"


def test_plan_over_http_returns_the_module_table(client):
    r = client.post("/api/symonlora/modules", headers=auth(), json={"model_dir": SYMON})
    assert r.status_code == 200
    mods = {m["module"]: m for m in r.json()["modules"]}
    assert mods["k_proj"]["out"] < mods["q_proj"]["out"]
