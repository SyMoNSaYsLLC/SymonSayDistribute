#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
#
#   workflow/lay-out-on-disk.sh <repo-name> <clone-url>
#   workflow/lay-out-on-disk.sh SymonSaySource https://github.com/SyMoNSaYsLLC/SymonSaySource.git
#
# Lay a repository out on disk the way it is laid out on the remote: one directory per
# branch. A bare repository holds the history once; each branch is a worktree beside it, so
# every branch is present at the same time and none of them is "the" checkout.
#
# WHY NOT AN ORDINARY CLONE
# -------------------------
# In this estate a branch is a thing — a runtime, a source family, a group of copyleft
# builds — not a line of development toward one trunk. An ordinary clone shows exactly one of
# them and hides the rest behind a command, so what is on disk stops resembling what was
# pushed and a reader has to already know the branch names to find anything. Worktrees make
# the structure the same in both places.
#
# The layout is destructive: it removes and recreates $HOME/<repo-name>. Uncommitted work in
# an existing layout is lost, so it is run on a tree with nothing in flight.
set -o pipefail
repo=$1; url=$2; root=$HOME/$repo
rm -rf "$root"; mkdir -p "$root" || exit 1
git clone -q --bare "$url" "$root/.bare" || exit 1
printf 'gitdir: ./.bare\n' > "$root/.git"
cd "$root" || exit 1
git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git fetch -q origin || exit 1
n=0
for b in $(git branch -r --format='%(refname:short)' | sed 's|^origin/||' | grep -v '^HEAD$' | sort); do
  git worktree add -q "$b" "$b" 2>/dev/null || git worktree add -q "$b" -b "$b" "origin/$b" 2>/dev/null || { echo "  skip $b"; continue; }
  n=$((n+1))
done
echo "  $repo: $n branch directories"
