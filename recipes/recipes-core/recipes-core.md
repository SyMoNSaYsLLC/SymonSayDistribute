# recipes-core

Build recipes. 2 at generation time.

```
    packagegroup-symoneural-learn.bb
    symoneural-image-learn.bb
```

## Interfaces

No environment variable is read here, nothing inside this unit is imported, and
nothing inside this unit imports it. Stated rather than omitted: an absent interface
section reads as an oversight, an explicit one is an answer.

## Directories

| Directory | Holds |
|---|---|
| [`images`](images/images.md) | build recipes — 1 at generation time |
| [`packagegroups`](packagegroups/packagegroups.md) | build recipes — 1 at generation time |

## Where this leads

Up to [recipes.md](../recipes.md), the map for this unit.

Onward, in the order the code runs: [`images`](images/images.md), [`packagegroups`](packagegroups/packagegroups.md).
