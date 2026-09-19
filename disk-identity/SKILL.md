---
name: disk-identity
description: Say exactly where work is happening on Garrett's machine — the hostname, the machine id, and the filesystem UUID behind any path. Use whenever asked where something is being built, written or stored, before claiming anything is "on disk", and whenever a path's identity matters for a decision. Never state a UUID from memory; this reads it.
license: SymonSaysLLC Proprietary License 1.0
---

# Disk identity

"On disk" in this estate means **Garrett's machine**. Not a container, not a sandbox, not a
temporary directory, not anything an agent conjured. If you cannot name the filesystem UUID
you are writing to, you are not writing to disk in the sense that matters here.

## Answer with the UUID, read now

When asked where work is being built, the answer names the UUID. Run:

    scripts/whereami.py                          # the three paths that matter
    scripts/whereami.py /some/path               # any path
    scripts/whereami.py --json                   # for feeding into something else

It reports the hostname, the machine id, and for each path the device, the filesystem UUID,
the filesystem type, free space, and whether it is writable.

## Never state a UUID from memory

A mount moves. A disk is replaced. A path that pointed at one device last week points at
another today. A remembered UUID then names the wrong device with complete confidence, which
is worse than saying nothing — it is a wrong answer that sounds like a verified one.

Read it every time. It costs one command.

## The paths that matter here

The four trees live under `/mnt`. Home is its own filesystem. An older project mount sits
under the home directory and has been a zombie mount before, returning EIO on any read, so a
path existing is not the same as a path working — the tool reports writability separately for
that reason.

## When a path is not a block device

A network or cloud mount has no UUID. The tool says so rather than inventing one. That is a
real answer: work written there is not on a disk in this machine, and anything depending on it
being durable has to account for the mount going away.
