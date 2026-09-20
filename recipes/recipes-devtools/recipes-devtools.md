# recipes-devtools

Build recipes. 0 at generation time.

## Interfaces

No environment variable is read here, nothing inside this unit is imported, and
nothing inside this unit imports it. Stated rather than omitted: an absent interface
section reads as an oversight, an explicit one is an answer.

## Directories

| Directory | Holds |
|---|---|
| [`python`](python/python.md) | `python3_%.bbappend` |

## Where this leads

Up to [recipes.md](../recipes.md), the map for this unit.

Onward, in the order the code runs: [`python`](python/python.md).
