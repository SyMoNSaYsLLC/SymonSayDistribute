# symoneural-adaptive-fabric

Component wiring: name a component, not a port.

This page describes what is **running**: the unit answers on 8816, and a real authenticated call
was routed through it to symonscope before this was written.

## What this is

One place that knows where every component answers, and the only place that holds their
credentials.

Before it, the agents runtime hardcoded five endpoints and needed every token it might ever use.
Any caller wanting to reach two components held two credentials. Here a caller names a component
and a path and holds nothing — the fabric attaches the key from its own environment.

That is the difference between wiring that is merely enumerable and wiring where a compromised
caller cannot leak a credential, because it never had one.

## The table is read from the board, not hardcoded

`/models/control.board` has been called this estate's port authority in five documents, and
until now exactly one service read it: the board itself. Every other unit read its own
`SYM_*_PORT` with a hardcoded default, so the authority was a claim in prose.

The fabric reads it. That makes the board load-bearing in the only way that counts — something
depends on it — and changing a port becomes one edit in one file instead of an edit in every
caller.

`unknown_on_board()` reports any port named there with no entry and no recorded reason, and a
test asserts it is empty. A port that appears on the board and nowhere else is a gap, not a
decision.

## What it will not route, and why each

    chat            the engine. Reached through the gateway, which owns the dialect and the
                    credential; a second path to the engine is a second thing to secure
    web             a browser interface, not a component API. Nothing calls it
    control_plane   read-only and supervised elsewhere (rules R14). The fabric will not forward
                    to it, so it cannot be changed through here by accident
    fabric          itself. Routing the fabric through the fabric is a loop, and a caller that
                    wants the wiring table already has it — that is what /components is

## Three refusals that make routing through safer than calling directly

**An unknown component** is refused with the list of what is routable, never guessed at.

**A path outside the component's own prefix** is refused. The fabric forwards to what a
component publishes; a caller that could name any path could reach anything this host serves.
`board` asking for `/api/store/where` is declined.

**A caller cannot supply a credential.** There is no parameter for one — a test asserts the
signature has no `token` or `auth` argument. A caller that could pass a token could be persuaded
to pass somebody else's.

An unprovisioned token is a refusal naming the variable, not an anonymous 401 from somewhere
downstream: "the estate is not finished being set up" and "you are not allowed" are different
answers, and only one of them is the operator's to fix.

## Routes

    GET  /api/fabric/health       public; answers before the fabric is configured
    GET  /api/fabric/components   the wiring table — token NAMES only, never a token
    GET  /api/fabric/reachable    which components answer right now
    GET  /api/fabric/resolve      where a call would go, without making it
    POST /api/fabric/call         route one call, and say what it was routed to
    GET  /api/fabric/board        the ports section as the board actually writes it

`routed_to` is in every response including errors. Wiring that cannot say where it went is
wiring nobody can debug.

## Proven, not asserted

A call to `symonscope` routed through the fabric by a caller holding only `SYM_FABRIC_TOKEN`:

    component : symonscope
    routed_to : http://127.0.0.1:8815/api/symonscope/units
    status    : 200 in 396.9 ms
    answer    : 13 units

The caller never had `SYM_SCOPE_TOKEN`.

## Placement

    placement-triage prospect adaptive-fabric --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

## A name that already exists elsewhere

`SymonSaySource` has a branch called `adaptive-fabric` too. That one is a **source pin record** —
two pins, no code, one acquired (`FreeToken`, Apache-2.0) and one deferred (`torch-2.11.x`).
This is a first-party runtime in `SymonSayDistribute`. Different trees, different things, same
word; recorded here so the next person does not conflate them.

## Testing

19 tests, most of them refusals: no board means no table, a board with no `[ports]` section is
refused, every port on the board is accounted for, nothing named not-routable appears as
routable, the table holds variable names and never values, an unknown component is refused, a
path outside a prefix is refused, a method the fabric does not forward is refused, an
unprovisioned token names its variable, the call signature cannot accept a credential, and the
fabric will not route to itself or to the control plane.

## Releases

Tagged `adaptive-fabric/v<version>`.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symoneural_fabric`](symoneural_fabric/symoneural_fabric.md) | the capability this unit provides — `route.py`, `wiring.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symoneural_fabric`](symoneural_fabric/symoneural_fabric.md), [`tests`](tests/tests.md).
