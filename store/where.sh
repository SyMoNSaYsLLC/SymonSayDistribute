#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# where — say exactly where the store is, and refuse to answer with a path that is not disk.
#
# Section 3.1c: an agent that cannot name the filesystem UUID it is writing to is not writing
# to disk in the sense this estate means. A model store on tmpfs would accept 13 GB and lose
# it at the next reboot, having reported success throughout.
set -o pipefail
STORE=${SYM_MODELS_DIR:-$HOME/symoneural-models}
[ "${1:-}" = "--store" ] && { STORE=${2:?directory}; }

echo "store      $STORE"
if [ ! -d "$STORE" ]; then
  echo "state      does not exist yet"
  parent=$(dirname "$STORE")
  [ -d "$parent" ] || { echo "           and neither does $parent"; exit 1; }
  STORE=$parent
  echo "checking   $STORE (its parent)"
fi
SRC=$(findmnt -no SOURCE -T "$STORE" 2>/dev/null)
FST=$(findmnt -no FSTYPE -T "$STORE" 2>/dev/null)
MNT=$(findmnt -no TARGET -T "$STORE" 2>/dev/null)
UUID=""; case "$SRC" in /dev/*) UUID=$(lsblk -no UUID "$SRC" 2>/dev/null | head -1);; esac
echo "mounted at $MNT"
echo "device     ${SRC:-(none)}"
echo "filesystem ${FST:-(unknown)}"
echo "uuid       ${UUID:-(none)}"
echo "free       $(df -h --output=avail "$STORE" 2>/dev/null | tail -1 | tr -d ' ')"
echo "entries    $(ls -1A "$STORE" 2>/dev/null | wc -l)"
case "$FST" in
  tmpfs|ramfs|overlay|fuse*|nfs*|cifs|9p)
    echo "NOT DISK — $FST cannot hold a model store"; exit 1 ;;
esac
[ -n "$UUID" ] || { echo "NOT DISK — no filesystem UUID"; exit 1; }
if [ "$MNT" = "/" ]; then
  echo
  echo "note       this is the ROOT filesystem. A store that fills it wedges the machine,"
  echo "           which a store on any other filesystem cannot do."
fi
exit 0
