#!/usr/bin/env python3
"""Regenerates protos/ and checks whether the committed generated code
(*.pb.go etc.) is up to date with the .proto sources.

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import argparse
import os
import subprocess
import sys

from _common import die, require_root

MODULE = "protos"


def git(root, *args, **kwargs):
    return subprocess.run(
        ["git", "-C", os.path.join(root, MODULE), *args],
        capture_output=True, text=True, **kwargs,
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revert",
        action="store_true",
        help="discard the regenerated diff afterward (`git checkout -- .`), "
        "leaving the tree as found -- useful for a check-only run",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    root = require_root()
    proto_dir = os.path.join(root, MODULE)

    status = git(root, "status", "--porcelain")
    if status.returncode != 0:
        die(f"git status failed in {MODULE}: {status.stderr.strip()}")
    if status.stdout.strip():
        die(f"{MODULE} has a dirty working tree -- commit or stash first, "
            "can't safely check for stale generated code against a dirty "
            "tree:\n" + status.stdout)

    print(f"=== regenerating {MODULE} ===", flush=True)
    result = subprocess.run(["make"], cwd=proto_dir)
    if result.returncode != 0:
        die(f"`make` failed in {MODULE}")

    diff = git(root, "status", "--porcelain")
    if not diff.stdout.strip():
        print("up to date -- generated code matches .proto sources")
        return 0

    print("STALE -- regeneration changed the following files:", file=sys.stderr)
    print(diff.stdout, file=sys.stderr)

    if args.revert:
        git(root, "checkout", "--", ".")
        clean = git(root, "clean", "-fd", "--dry-run")
        if clean.stdout.strip():
            print("note: --revert only discards tracked-file changes; "
                  "these untracked files remain:\n" + clean.stdout,
                  file=sys.stderr)
        print("(reverted with --revert)", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
