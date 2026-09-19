# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
"""One real agent run against the live Symon. The credential is read here and used here;
it is never printed and never returned."""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from symoneural_agents.tools import Tool, Registry
from symoneural_agents.agent import run_agent

KEY = open(os.path.expanduser("~/.config/symoneural/gateway-9001.key")).read().strip()
URL = "http://127.0.0.1:9001/v1/messages"

def send(payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "content-type": "application/json", "anthropic-version": "2023-06-01",
        "authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())

CALLED = []
def add(a):
    CALLED.append(a)
    return str(int(a.get("a", 0)) + int(a.get("b", 0)))

rg = Registry()
rg.add(Tool("add", "Add two integers and return the sum.",
            {"type": "object",
             "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
             "required": ["a", "b"]}, add))

t0 = time.time()
run = run_agent("live-proof", "Use the add tool to compute 17 plus 25, then tell me the result.",
                rg.grant(["add"]), send, model="symon-sonnet", max_steps=4, max_seconds=540)
print(json.dumps(run.report(), indent=1))
print("\ntool actually invoked with:", CALLED)
print("wall seconds: %.1f" % (time.time() - t0))
