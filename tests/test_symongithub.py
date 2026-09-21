# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What proves symongithub does what it says. No network, no credential needed."""
import json, os, re, subprocess, stat, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "symoneural-github-mcp"
ACQUIRE = ROOT / "acquire.sh"
PIN = json.loads((ROOT / "pin.json").read_text())

# Every tool the upstream catalog (v1.12.2, 90 tools) marks destructiveHint, plus the writes
# whose blast radius is a repository, an organisation or history rather than one issue or PR.
MUST_BE_OFF_BY_DEFAULT = {
    "delete_file", "push_files", "merge_pull_request", "create_repository", "fork_repository",
    "create_repository_ruleset", "custom_properties_write", "actions_run_trigger",
    "projects_write", "label_write", "discussion_comment_write", "assign_copilot_to_issue",
    "assign_copilot_to_issue_with_intent", "request_copilot_review", "star_repository",
    "unstar_repository", "create_gist", "update_gist",
}


def run(env_extra, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYM_GITHUB_")}
    env.update(env_extra)
    return subprocess.run([str(WRAPPER), *args], env=env, capture_output=True, text=True, timeout=30)


def test_pin_has_every_field_a_review_needs():
    for k in ("upstream_url", "commit_sha", "nearest_tag", "declared_license", "license_md5", "copyright", "acquired"):
        assert PIN[k], k
    assert re.fullmatch(r"[0-9a-f]{40}", PIN["commit_sha"])
    assert not PIN["acquired"].startswith("2026-08"), "August-dated acquisition"
    for k in ("asset", "asset_sha256", "binary_sha256", "repo"):
        assert PIN["release"][k], k


def test_scripts_are_executable_and_carry_the_header():
    for f in (WRAPPER, ACQUIRE):
        assert f.stat().st_mode & stat.S_IXUSR, f
        head = f.read_text().splitlines()[:4]
        assert any("LicenseRef-SymonSaysLLC-Proprietary-1.0" in l for l in head), f


def test_wrapper_refuses_when_binary_is_not_installed(tmp_path):
    r = run({"SYM_GITHUB_INSTALL": str(tmp_path)})
    assert r.returncode == 127, (r.returncode, r.stderr)
    assert "not installed" in r.stderr


def test_wrapper_refuses_a_binary_that_is_not_the_pinned_bytes(tmp_path):
    d = tmp_path / PIN["nearest_tag"]; d.mkdir()
    fake = d / "github-mcp-server"
    fake.write_text("#!/bin/sh\necho 'Commit: %s'\n" % PIN["commit_sha"]); fake.chmod(0o755)
    r = run({"SYM_GITHUB_INSTALL": str(tmp_path)})
    assert r.returncode == 70, (r.returncode, r.stderr)
    assert "sha256" in r.stderr and "refusing" in r.stderr


def test_wrapper_refuses_when_no_gh_credential_for_the_named_account(tmp_path):
    # Only when the real binary is installed; otherwise the earlier gate fires first.
    inst = Path(os.path.expanduser(PIN["installed_at"].replace("$HOME", "~"))).parent
    if not (inst / PIN["nearest_tag"] / "github-mcp-server").exists():
        import pytest; pytest.skip("pinned binary not installed on this host")
    r = run({"SYM_GITHUB_ACCOUNT": "no-such-account-symoneural-test"})
    assert r.returncode == 78, (r.returncode, r.stderr)
    assert "no gh credential" in r.stderr


def test_token_never_reaches_argv_or_a_file():
    lines = [l for l in WRAPPER.read_text().splitlines() if "$TOKEN" in l]
    # Exactly two lines may touch the token: the gh capture with its emptiness check, and the
    # exec that places it in the child's environment. Anything else is a leak path.
    assert len(lines) == 2, lines
    assert lines[0].startswith("if ! TOKEN=$(gh auth token --user") and '[ -z "$TOKEN" ]' in lines[0]
    assert lines[1] == 'GITHUB_PERSONAL_ACCESS_TOKEN="$TOKEN" exec "$BIN" "${ARGS[@]}" "$@"'
    src = WRAPPER.read_text()
    assert "--token" not in src and "echo" not in lines[0] + lines[1]


def test_default_exclusions_cover_every_destructive_or_admin_write():
    src = WRAPPER.read_text()
    m = re.search(r'EXCLUDE=\$\{SYM_GITHUB_EXCLUDE-([^}]*)\}', src)
    assert m, "default exclusion list not found"
    have = set(m.group(1).split(","))
    missing = MUST_BE_OFF_BY_DEFAULT - have
    assert not missing, missing


def test_acquire_check_agrees_with_pin_when_installed():
    inst = Path(os.path.expanduser(PIN["installed_at"].replace("$HOME", "~"))).parent
    if not (inst / PIN["nearest_tag"] / "github-mcp-server").exists():
        import pytest; pytest.skip("pinned binary not installed on this host")
    r = subprocess.run([str(ACQUIRE), "--check"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert PIN["commit_sha"] in r.stdout and PIN["release"]["binary_sha256"] in r.stdout
