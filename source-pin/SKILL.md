---
name: source-pin
description: Record or verify what an acquired upstream tree actually is — the commit, the declared licence with the checksum of its licence file, the copyright line, and when it was acquired. Use when acquiring any upstream source, before building from one, when a licence audit disagrees with a pin, and whenever asked what version of something we build from. A pin is what lets the same bytes be fetched again and the choice defended later.
license: SymonSaysLLC Proprietary License 1.0
---

# Source pin

The estate builds from pristine upstream source and does not carry it: the trees are tens of
gigabytes and stay on the build host, read-only. What is recorded instead is enough to fetch
the identical bytes again, and enough to defend the choice at a licence review a year later
when the tree may be gone and nobody remembers the conversation.

    scripts/pin.py record <tree> [--component NAME] [--out FILE]
    scripts/pin.py check  <pin.json> [--tree PATH]

## Why a commit and never a tag

A tag moves. A maintainer can delete one and push it again pointing somewhere else, and every
build that trusted it changes silently. A commit identifier cannot move. The pin records the
full commit; the nearest tag sits beside it for humans to read and is never what gets fetched.

## Why the licence checksum matters more than the licence name

"It was MIT" is a claim. The checksum of the licence file is what makes that claim checkable
after upstream relicenses, adds a clause, or changes a copyright holder. `check` compares the
checksum, not the name, and reports drift in the file even when the name is unchanged.

The copyright line is recorded for the same reason: a permissive licence obliges us to carry
attribution, and that obligation is only meetable if we know what the attribution says.

## What check reports

Every field that has moved since the pin was written, with what it was and what it is now, and
why the difference matters. It also fails on two things beyond drift: an acquired tree with
local modifications, because those trees are read-only and a modified one means a build is no
longer reproducible; and anything dated August 2026, which predates the estate's fresh start  <!-- gate-allow: no-august — the rule is named here in order to state it -->
and is barred until ruled on.

## When the tree is gone

`check` says so and stops rather than guessing. The pin is still the record — re-fetch from
the recorded URL at the recorded commit and check against that.

## What it refuses

A tree that is not a git checkout gets no pin, because a pin without a commit is not a pin. A
tree whose licence cannot be determined exits non-zero and says so: that is not something to
build from until the licence is established.
