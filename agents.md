# agents

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

The loop that lets Symon do work rather than only answer. Symon could already ask for a tool
and read a result — the channel format renders tool declarations, emits `tool_use` blocks and
replays a `tool_result` as a message from that tool. Nothing anywhere executed the call. This
closes that circle and nothing more.

## What it does

    send the task with the granted tools
    while the model asks for tools:
        execute each call, in the order asked
        send every result back in one turn
    return when the model answers instead of asking

## A grant, not a tool list

A tool is not "a function the model may call". It is a capability named and fixed when the run
is composed. `Grant` has no method to add one afterwards, deliberately: a grant that can grow
mid-run is not a bound.

And a tool that was not granted is never *declared*, so the model is never told it exists. That
ordering is the point. A model that knows about a capability and is refused will work around
the refusal; a model never told is simply working with a smaller set.

## Bounds are load-bearing

A run cannot be reached into once it starts. That is what makes the grant a bound rather than a
suggestion — and it means the only thing that can stop a run that will never finish is a limit
set before it began.

`max_steps` and `max_seconds` have no defaults and are refused if set with no teeth. Hitting one
ends the run `exceeded`, which is a result rather than a crash.

## Failure is a result, never an exception

A tool that raises, a tool with a bug, a tool that was never granted — each comes back as text
the model can act on. Raising past it would leave a call with no result in the transcript, which
is a shape the model was never trained on, and turns a recoverable step into a dead run.

## `empty` is its own state, and it exists because of a real run

The first live run against Symon reported `returned` with an empty answer. The model had emitted
only a thinking block — *"We need to use the add function."* — and ended the turn, having decided
to call a tool and never emitted the call.

Reporting that as a return makes "it worked" and "it produced nothing" identical in every report
downstream. It now has its own state and names what was actually produced. Three tests hold that
line: thinking-only, no content at all, and whitespace.

## Known: tool calling is not reachable yet, and the reason is now specific

`proof_live.py` runs one real agent against the live gateway. As of 2026-09-19 it returns
`empty`.

This was recorded here as "the substitution engine is running with no tool-call parser", which
was true and useless. Measured against the unit on 8802 the same day, the cause is exact:

    "Reply with exactly: READY"          42 tokens   content "READY"
    "What is 2+2?"                       47 tokens   content "4"
    "Use a tool."                       150 tokens   content ""
    the same, with a tools[] block      150 tokens   content "", tool_calls null

The model generates in every case. gpt-oss emits into harmony channels — analysis and
commentary, where its tool calls live — and the server parses neither, so those tokens are
produced and discarded. `empty` was the loop faithfully reporting a reply that had been thrown
away upstream of it.

The fix is two flags on the engine, not a change here: `--enable-auto-tool-choice` with
`--tool-call-parser openai` and `--reasoning-parser openai_gptoss`.
`symoneural-learn/runtime/serve-chat-unit.sh` passes them as of 2026-09-19 and the engine has
not been restarted onto them yet.

The loop is correct and the capability is not yet reachable. Both remain true, and `empty` was
the right state to have built — it distinguished "the model said nothing" from "the model
failed", and only one of those is what happened.

## Testing

Sixteen tests, and the loop is tested without a model, because what it must get right is
transcript shape and bounds — neither of which depends on what any model says. The assistant
turn goes back verbatim; several calls in one turn get their results in one turn; both bounds
bind; a report distinguishes answering from giving up quietly.

`proof_live.py` reads the gateway credential itself and never prints or returns it.

## Releases

This branch cuts its own releases, tagged `agents/v<version>`.

## Connectors

A connector is a tool that reaches another component **over its published HTTP surface** —
never into its files. That is the whole definition, and it is deliberately narrow: if a
component has no endpoint for something, the connector cannot do it, and the answer is to build
the endpoint rather than to reach around it.

**Every connector routes through the fabric.** Garrett, 2026-09-19: all symon component wiring
routes through the symoneural-adaptive-fabric. This file used to hold five endpoints and five
token variables, which meant this process had to hold every credential it might ever use. It
now holds exactly one — the fabric's — and names a component rather than an address.

Two things follow that matter more than the tidiness. An agent process that is compromised
cannot leak a credential it never had. And a port change is one edit on `/models/control.board`
rather than an edit here: this file no longer knows or cares what port anything is on.

The cost is honest and stated: nothing is reachable while the fabric is down, and `reachable()`
says exactly that rather than guessing per component from a table this process no longer keeps.

Verified live: an agent process holding only `SYM_FABRIC_TOKEN` reached symonscope through the
fabric and got 13 units back.

It makes the estate's wiring enumerable. `GET /api/agents/connectors` lists every wire with its
component, endpoint and token variable, and whether the far end is answering — because a
connector to something that is not running is a wire to nowhere, and saying so beats a timeout
three steps into a run.

None accepts a credential as an argument. Each reads its own token from the environment at call
time: an argument a model can fill is an argument a model can be persuaded to fill with a secret.

## Plugins

A plugin is a **manifest**, never code. It names a component, where that component answers, and
the tools that reach it. Nothing in it is imported or executed.

The obvious design is a directory of Python the runtime imports. That makes dropping a file into
a directory equivalent to arbitrary execution inside the runtime holding the gateway credential
— the capability a plugin adds would be bounded by nothing, and the grant model this runtime is
built on would be decorative. A manifest can only ever describe an HTTP call.

**Presence is not consent.** Discovery lists what is there; nothing loads until it is named in
`SYM_PLUGINS_ENABLED`. A plugin that appeared on disk has not been chosen.

**The licence is part of the manifest.** A plugin whose licence this runtime cannot absorb
without a placement decision is listed with that reason rather than loaded — the placement
procedure applied at run time.

A plugin may not take a name the estate already uses. Silently overriding a connector would let
a plugin redirect a tool an agent already trusts.

## Over HTTP

Nine routes on `127.0.0.1:8813`, the port `/models/control.board` assigns to `agents`. Health
is public; everything else needs `SYM_AGENTS_TOKEN`, and an unset token closes the service
rather than opening it.

    GET    /api/agents/health                 public; answers before anything is configured
    GET    /api/agents/tools                  the registry: every tool that may be granted
    GET    /api/agents/connectors             every wire, with whether the far end answers
    GET    /api/agents/plugins                the manifests found, and whether each is enabled
    POST   /api/agents/runs                   start a run under a grant and a set of bounds
    GET    /api/agents/runs                   the runs, filterable by `?state=`
    GET    /api/agents/runs/{run_id}          one run: its grant, bounds, steps and result
    POST   /api/agents/runs/{run_id}/stop     stop a run; a stopped run keeps its transcript
    DELETE /api/agents/runs                   clear finished runs

The grant is fixed when the run is composed and cannot be widened afterwards, so there is no
route that adds a tool to a run in flight. That absence is the design, not an omission.

**Known drift on this host.** The process serving 8813 was started before `plugins` landed and
answers 404 for it; the route is in this branch. Restart the unit to pick it up.
