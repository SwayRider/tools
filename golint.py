#!/usr/bin/env python3
"""Runs `golangci-lint run ./...` for every Go module that has a
.golangci.yml (protos is excluded -- it's mostly generated code with no
lint config), plus `flutter analyze` for swayriderapp.

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import argparse
import os
import subprocess
import sys

from _common import die, require_root

MODULES = [
    "authservice",
    "grpcclients",
    "mailservice",
    "regionservice",
    "routerservice",
    "searchservice",
    "swayrider-api",
    "swayriderapp",
    "swctl",
    "swlib",
    "tilesservice",
]

DEFAULT_CMD = ["golangci-lint", "run", "./..."]
MODULE_CMD = {
    "swayriderapp": ["flutter", "analyze"],
}


def lint_cmd(module, extra):
    return MODULE_CMD.get(module, DEFAULT_CMD) + extra


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--modules",
        help="comma-separated subset to lint (default: all -- "
        + ",".join(MODULES) + ")",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop at the first failing module instead of continuing "
        "through the rest and reporting failures at the end",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resolved `golangci-lint` command for each module "
        "without running it",
    )
    parser.add_argument(
        "lint_args",
        nargs=argparse.REMAINDER,
        help="extra arguments passed through to the lint command (e.g. "
        "-- --fix for `golangci-lint run`; module-specific for "
        "swayriderapp's `flutter analyze`)",
    )
    return parser.parse_args()


def resolve_modules(selection):
    if not selection:
        return list(MODULES)
    requested = [s.strip() for s in selection.split(",") if s.strip()]
    unknown = [s for s in requested if s not in MODULES]
    if unknown:
        die(f"unknown module(s): {', '.join(unknown)} "
            f"(known: {', '.join(MODULES)})")
    return [s for s in MODULES if s in requested]


def main():
    args = parse_args()
    root = require_root()
    modules = resolve_modules(args.modules)

    extra = args.lint_args
    if extra and extra[0] == "--":
        extra = extra[1:]

    failed = []
    for mod in modules:
        mod_dir = os.path.join(root, mod)
        cmd = lint_cmd(mod, extra)
        print(f"=== {mod} ===", flush=True)
        if args.dry_run:
            print(f"[dry-run] (cd {mod_dir} && {' '.join(cmd)})")
            print()
            continue
        result = subprocess.run(cmd, cwd=mod_dir)
        print()
        if result.returncode != 0:
            failed.append(mod)
            if args.fail_fast:
                break

    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("dry run completed" if args.dry_run else "all modules clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
