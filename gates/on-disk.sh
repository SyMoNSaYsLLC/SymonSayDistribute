#!/usr/bin/env bash
# one-line: proves a path is on a real filesystem with a UUID
# target: worktree — asks whether the repository is on a real filesystem, not whether scratch is
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# Section 3.1c: "on disk" means Garrett's machine. An agent that cannot name the filesystem UUID
# it is writing to is not writing to disk in the sense this estate means. A container path, a
# tmpfs, or a network mount will all happily accept a write and lose it.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }
SRC=$(findmnt -no SOURCE -T "$T" 2>/dev/null)
FST=$(findmnt -no FSTYPE -T "$T" 2>/dev/null)
MNT=$(findmnt -no TARGET -T "$T" 2>/dev/null)
UUID=""
case "$SRC" in /dev/*) UUID=$(lsblk -no UUID "$SRC" 2>/dev/null | head -1) ;; esac
echo "path       $T"
echo "mounted at $MNT"
echo "device     ${SRC:-(none)}"
echo "filesystem ${FST:-(unknown)}"
echo "uuid       ${UUID:-(none)}"
case "$FST" in
  tmpfs|ramfs|overlay|fuse*|nfs*|cifs|9p)
      echo "NOT DISK — $FST is not a block filesystem on this machine"; exit 1 ;;
esac
[ -n "$UUID" ] || { echo "NOT DISK — no filesystem UUID could be read"; exit 1; }
exit 0
