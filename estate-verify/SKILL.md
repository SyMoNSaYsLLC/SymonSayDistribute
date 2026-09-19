---
name: estate-verify
description: Report what is actually running in the estate right now, with a probe behind every line. Use before claiming any part of the deployment works, after any restart or reboot, when something is reported broken, and before a release or a demo. Never present a status board as current unless it was just produced by this.
license: SymonSaysLLC Proprietary License 1.0
---

# Estate verify

    scripts/verify.sh            # listeners, gateway behaviour, models, GPU
    scripts/verify.sh --deep     # the above plus a real completion end to end

## Sequence is not status

The recurring failure in this estate is a status document that was true when it was written.
Dependencies are structural and stay true; status drifts the moment work lands, a process
dies, or a machine reboots.

So every line here is a probe run now, and the summary states the timestamp and says "and only
then". A report from this is worth quoting for about as long as it takes to read.

## What it checks and why each one

**Listeners.** The gateway, the chat unit behind it, the control plane, the web console. A
port with nothing on it is reported down rather than omitted, because a missing line reads as
"not checked" and a down line reads as a fact.

**The gateway refusing correctly.** An unauthenticated request must return 401. A gateway that
answers without a credential is a worse failure than one that is down, and it looks identical
to a healthy one unless you probe for the refusal.

**The models offered.** The ids as the gateway actually projects them. A client only offers a
model whose id satisfies its own naming rule, so this is where a silently empty picker becomes
visible.

**The GPU.** How much is used and what is holding it. The card is the scarce resource, and
"something else has it" explains most failures to start a runtime.

**A real completion**, with `--deep`. Slow, and the only check that proves the whole path
rather than its parts. Everything else can pass while the path is broken in the middle.

## Exit code

Non-zero if anything is down, so it can gate a release or a demo rather than being read and
ignored.

## What it does not do

It does not start, stop or fix anything. The control plane in particular is read-only and
demo-critical, supervised elsewhere; this reports it down and leaves it alone.
