# recipes

Build recipes. 4 at generation time.

```
    packagegroup-symoneural-learn.bb
    symoneural-image-learn.bb
    symoneural-learn-web_1.0.0.bb
    symoneural-learn_1.0.0.bb
```

## Interfaces

No environment variable is read here, nothing inside this unit is imported, and
nothing inside this unit imports it. Stated rather than omitted: an absent interface
section reads as an oversight, an explicit one is an answer.

## Directories

| Directory | Holds |
|---|---|
| [`recipes-core`](recipes-core/recipes-core.md) | build recipes — 2 at generation time |
| [`recipes-devtools`](recipes-devtools/recipes-devtools.md) | a grouping directory — `python` |
| [`recipes-learn`](recipes-learn/recipes-learn.md) | build recipes — 2 at generation time |

## Where this leads

Up to [symoneural-learn.md](../symoneural-learn.md), the map for this unit.

Onward, in the order the code runs: [`recipes-core`](recipes-core/recipes-core.md), [`recipes-devtools`](recipes-devtools/recipes-devtools.md), [`recipes-learn`](recipes-learn/recipes-learn.md).
