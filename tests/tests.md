# tests

What proves `symongithub` does what it says. Nothing here needs a network or a credential;
the two tests that need the installed binary skip, loudly, when it is absent.

```
    test_symongithub.py
```

| Test | Refuses to pass when |
|---|---|
| pin fields | the pin lacks a field a licence review would ask for, or is August-dated |
| header and mode | either script is not executable or lacks the proprietary header |
| missing binary | the wrapper starts without the pinned binary on disk (must exit 127) |
| wrong bytes | the wrapper runs a binary whose sha256 is not the pin's (must exit 70) |
| no credential | the wrapper starts for an account gh does not hold (must exit 78) |
| token on argv | the token variable appears anywhere but the gh capture and the child's environment |
| exclusions | any destructive or admin write is missing from the default exclusion list |
| acquire --check | the installed binary, tarball, licence or reported commit drifts from the pin |

## Interfaces

Reads `../pin.json`, `../symoneural-github-mcp`, `../acquire.sh` and, when present, the
installed binary under `~/.local/share/symoneural/github-mcp-server/<tag>/`.

Run: `python3 -m pytest -q tests/` from the branch root.

The flow ends here: a passing suite is what allows the wrapper to be registered with a client.
