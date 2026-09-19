# symonweb

The capability `symonweb` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `browse.py` | `drivers`, `visit` | Driving a browser — any browser that speaks W3C WebDriver. |
| `fetch.py` | `fetch` | Fetching a page, and turning it into something a model can read. |
| `guard.py` | `check_public`, `robots_allows` | What this component refuses to fetch, and why each refusal exists. |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonweb.md](../symonweb.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonweb.md](../symonweb.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
