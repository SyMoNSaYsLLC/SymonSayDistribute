# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""The loop is tested without a model, because what it must get right is transcript shape and
bounds — neither of which depends on what any model says."""
import time
import pytest
from symoneural_agents.tools import Tool, Registry, ToolError
from symoneural_agents.agent import run_agent, Bounds


def reg(**kw):
    r = Registry()
    r.add(Tool("echo", "echo back", {"type": "object"}, lambda a: a.get("say", ""), **kw))
    return r


def answers(text):
    return lambda payload: {"content": [{"type": "text", "text": text}]}


def calls_then_answers(tool, args, text):
    state = {"n": 0}
    def send(payload):
        state["n"] += 1
        if state["n"] == 1:
            return {"content": [{"type": "tool_use", "id": "t1", "name": tool, "input": args}]}
        return {"content": [{"type": "text", "text": text}]}
    return send


def always_calls(tool):
    return lambda p: {"content": [{"type": "tool_use", "id": "x", "name": tool, "input": {}}]}


def test_a_model_that_answers_returns_immediately():
    r = run_agent("a", "hello", reg().grant(["echo"]), answers("hi"),
                  model="symon-sonnet", max_steps=5, max_seconds=10)
    assert r.state == "returned" and r.answer == "hi"
    assert r.report()["calls"] == 0


def test_a_call_is_executed_and_the_result_reaches_the_model():
    seen = {}
    def send(payload):
        seen["last"] = payload["messages"]
        if len(payload["messages"]) == 1:
            return {"content": [{"type": "tool_use", "id": "t1", "name": "echo", "input": {"say": "ping"}}]}
        return {"content": [{"type": "text", "text": "done"}]}
    r = run_agent("a", "go", reg().grant(["echo"]), send,
                  model="m", max_steps=5, max_seconds=10)
    assert r.state == "returned"
    assert r.report()["calls"] == 1 and r.report()["tools_used"] == ["echo"]
    # the assistant turn goes back verbatim, the results in ONE following user turn
    msgs = seen["last"]
    assert msgs[1]["role"] == "assistant" and msgs[1]["content"][0]["type"] == "tool_use"
    assert msgs[2]["role"] == "user"
    res = msgs[2]["content"][0]
    assert res["type"] == "tool_result" and res["tool_use_id"] == "t1"
    assert res["content"] == "ping" and res["is_error"] is False


def test_every_call_in_one_turn_is_executed_and_answered_in_one_turn():
    def send(payload):
        if len(payload["messages"]) == 1:
            return {"content": [
                {"type": "tool_use", "id": "a", "name": "echo", "input": {"say": "1"}},
                {"type": "tool_use", "id": "b", "name": "echo", "input": {"say": "2"}}]}
        assert len(payload["messages"][2]["content"]) == 2   # both results, one turn
        return {"content": [{"type": "text", "text": "ok"}]}
    r = run_agent("a", "go", reg().grant(["echo"]), send, model="m", max_steps=5, max_seconds=10)
    assert r.state == "returned" and r.report()["calls"] == 2


def test_a_tool_that_raises_becomes_a_result_not_a_dead_run():
    rg = Registry()
    def boom(a): raise ToolError("the disk is full")
    rg.add(Tool("boom", "fails", {"type": "object"}, boom))
    r = run_agent("a", "go", rg.grant(["boom"]), calls_then_answers("boom", {}, "recovered"),
                  model="m", max_steps=5, max_seconds=10)
    assert r.state == "returned" and r.answer == "recovered"
    assert r.report()["failed_calls"][0]["why"] == "the disk is full"


def test_a_tool_bug_is_also_a_result():
    rg = Registry()
    rg.add(Tool("bug", "raises", {"type": "object"}, lambda a: 1 / 0))
    r = run_agent("a", "go", rg.grant(["bug"]), calls_then_answers("bug", {}, "ok"),
                  model="m", max_steps=5, max_seconds=10)
    assert r.state == "returned"
    assert "ZeroDivisionError" in r.report()["failed_calls"][0]["why"]


def test_an_ungranted_tool_is_refused_by_name_not_guessed_at():
    r = run_agent("a", "go", reg().grant(["echo"]), calls_then_answers("nope", {}, "ok"),
                  model="m", max_steps=5, max_seconds=10)
    assert r.state == "returned"
    assert "no such tool: nope" in r.report()["failed_calls"][0]["why"]


def test_the_step_bound_binds():
    r = run_agent("a", "go", reg().grant(["echo"]), always_calls("echo"),
                  model="m", max_steps=3, max_seconds=60)
    assert r.state == "exceeded"
    assert r.report()["calls"] == 3
    assert "all 3 steps" in r.why


def test_the_time_bound_binds():
    rg = Registry()
    rg.add(Tool("slow", "sleeps", {"type": "object"}, lambda a: time.sleep(0.05) or "ok"))
    r = run_agent("a", "go", rg.grant(["slow"]), always_calls("slow"),
                  model="m", max_steps=1000, max_seconds=0.15)
    assert r.state == "exceeded" and "against a" in r.why


def test_a_run_can_be_stopped_between_steps():
    flag = {"stop": False}
    def send(p):
        flag["stop"] = True
        return {"content": [{"type": "tool_use", "id": "x", "name": "echo", "input": {}}]}
    r = run_agent("a", "go", reg().grant(["echo"]), send, model="m",
                  max_steps=10, max_seconds=10, stop=lambda: flag["stop"])
    assert r.state == "stopped"


def test_bounds_with_no_teeth_are_refused():
    g = reg().grant(["echo"])
    for steps, secs in ((0, 10), (-1, 10), (5, 0), (5, -1)):
        with pytest.raises(Bounds):
            run_agent("a", "go", g, answers("x"), model="m", max_steps=steps, max_seconds=secs)


def test_a_grant_cannot_be_widened_after_it_is_made():
    g = reg().grant(["echo"])
    assert g.names() == ["echo"]
    assert not hasattr(g, "add")
    with pytest.raises(ValueError):
        reg().grant(["echo", "does_not_exist"])


def test_read_only_is_derived_from_the_tools_not_asserted():
    assert reg().grant(["echo"]).read_only() is True
    assert reg(mutates=True).grant(["echo"]).read_only() is False


def test_a_report_distinguishes_answering_from_giving_up():
    ok = run_agent("a", "go", reg().grant(["echo"]), answers("yes"),
                   model="m", max_steps=5, max_seconds=10).report()
    gave_up = run_agent("a", "go", reg().grant(["echo"]), always_calls("echo"),
                        model="m", max_steps=2, max_seconds=10).report()
    assert ok["state"] == "returned" and gave_up["state"] == "exceeded"
    assert ok["why"] != gave_up["why"]


def test_thinking_only_is_not_an_answer():
    """The first live run returned `returned` with an empty answer because the model emitted
    only a thinking block. Success and silence must not look the same."""
    thinking_only = lambda p: {"content": [{"type": "thinking", "thinking": "We need to use the add function."}]}
    r = run_agent("a", "go", reg().grant(["echo"]), thinking_only,
                  model="m", max_steps=3, max_seconds=10)
    assert r.state == "empty"
    assert r.answer == ""
    assert "neither called a tool nor answered" in r.why
    assert "thinking" in r.why


def test_no_content_at_all_is_also_empty():
    r = run_agent("a", "go", reg().grant(["echo"]), lambda p: {"content": []},
                  model="m", max_steps=3, max_seconds=10)
    assert r.state == "empty"


def test_whitespace_is_not_an_answer():
    r = run_agent("a", "go", reg().grant(["echo"]),
                  lambda p: {"content": [{"type": "text", "text": "   \n  "}]},
                  model="m", max_steps=3, max_seconds=10)
    assert r.state == "empty"
