# tests

What proves `adaptive-fabric` does what it says.

1 test file(s), 21 test function(s) at generation time.

```
    test_fabric.py
```

## Interfaces

**Consumes:** the `adaptive-fabric` package and its `service.py`. Nothing here is
imported by anything else — a test directory is a leaf by design, which is why it
does not link onward to a sibling.

**Run with:**

```
    python3 -m pytest tests/ -q
```

`python3 -m` is load-bearing: it puts the worktree root on `sys.path`, which is what
makes `import service` and the package import resolve.

## Where this leads

Back to [adaptive-fabric.md](../adaptive-fabric.md), which is the map for this unit. The flow ends here:
tests are exercised by a person or a gate, and call nothing further.
