# tools

The release machinery is not here. It lives on the `workflow` branch of this repository, and
there is exactly one copy of it.

    git worktree add workflow workflow      # beside this checkout
    workflow/cut-release.sh <runtime> <version> <stage>
    workflow/ship-gate.py --stage <stage>
    workflow/ship-gate-policy.json
    workflow/install-from-release.sh
    workflow/third-party-notices.py
    workflow/release-notes.py
    workflow/pack-script-unit.sh
    workflow/bench-gateway.sh
    workflow/licence-audit.py
    workflow/verify-3p-path.sh

## Why it moved

It was here as well, and the two copies diverged. Five of the eight had drifted:
`ship-gate.py` was 467 lines here against 712 on `workflow`, the newer one carrying a census
the older one did not have — so the same release gated differently depending on which copy was
invoked. `ship-gate-policy.json` had drifted too, which meant the two gates disagreed about
what a licence class even was.

The `no-divergent-copy` gate refused a commit over it, which is how it was found. The estate
now holds one canonical copy of each tool. The others are removed by commit and recoverable
from history like anything else.
