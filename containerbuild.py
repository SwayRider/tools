#!/usr/bin/env python3
"""Runs `make container-build` for every backend service. Python port of the
old containerbuild.sh.

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import argparse
import os
import subprocess
import sys

SERVICES = [
    "authservice",
    "mailservice",
    "regionservice",
    "routerservice",
    "searchservice",
    "swayrider-api",
    "swctl",
    "tilesservice",
]


class Style:
    def __init__(self, enabled):
        self.reset = "\033[0m" if enabled else ""
        self.bold = "\033[1m" if enabled else ""
        self.dim = "\033[2m" if enabled else ""
        self.yellow = "\033[33m" if enabled else ""
        self.red = "\033[31m" if enabled else ""

    def paint(self, color, text):
        return f"{color}{text}{self.reset}"


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the resolved tags and docker buildx command for each "
        "service (via `make -n`) without building or pushing anything",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="print a compact, colored table of each service and its "
        "resolved tags (via `make print-tags`) without building or "
        "pushing anything",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="build a single-arch (host platform) image loaded into the "
        "local Docker daemon instead of a multi-arch image pushed to the "
        "registry (sets NO_PUSH=1)",
    )
    parser.add_argument(
        "--dev-latest",
        action="store_true",
        help="also push/show the dev-latest floating tag (sets "
        "FORCE_DEV_LATEST=1). dev-latest is always added automatically for "
        "an untagged main HEAD; this forces it for a tagged release or any "
        "other branch too",
    )
    parser.add_argument(
        "--services",
        help="comma-separated subset to build (default: all -- "
        + ",".join(SERVICES) + ")",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop at the first failed service instead of continuing "
        "through the rest and reporting failures at the end",
    )
    return parser.parse_args()


def resolve_services(selection):
    if not selection:
        return list(SERVICES)
    requested = [s.strip() for s in selection.split(",") if s.strip()]
    unknown = [s for s in requested if s not in SERVICES]
    if unknown:
        die(f"unknown service(s): {', '.join(unknown)} "
            f"(known: {', '.join(SERVICES)})")
    return [s for s in SERVICES if s in requested]


def show_tags(services, root, env, style):
    width = max(len(svc) for svc in services)
    failed = []
    for svc in services:
        svc_dir = os.path.join(root, svc)
        result = subprocess.run(
            ["make", "print-tags"], cwd=svc_dir, env=env,
            capture_output=True, text=True,
        )
        name = style.paint(style.bold, svc.ljust(width))
        if result.returncode != 0:
            print(f"{name}  {style.paint(style.red, 'error')}")
            failed.append(svc)
            continue
        tags = result.stdout.split()
        if not tags:
            print(f"{name}  {style.paint(style.dim, '-')}")
            continue
        base, rest = tags[0], tags[1:]
        painted = style.paint(style.yellow, base)
        if rest:
            painted += " " + style.paint(style.dim, " ".join(rest))
        print(f"{name}  {painted}")

    if failed:
        print(f"\nfailed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def main():
    args = parse_args()
    root = os.environ.get("SWAYRIDER_ROOT")
    if not root:
        die("SWAYRIDER_ROOT is not set — run via direnv, or "
            "`source .vscode/environment.example` first")

    services = resolve_services(args.services)

    env = os.environ.copy()
    if args.dev_latest:
        env["FORCE_DEV_LATEST"] = "1"
    if args.no_push:
        env["NO_PUSH"] = "1"

    if args.show:
        style = Style(sys.stdout.isatty())
        return show_tags(services, root, env, style)

    make_cmd = ["make"]
    if args.dry_run:
        make_cmd.append("-n")
    make_cmd.append("container-build")

    if args.dry_run:
        print("[dry-run] resolving tags for each service, nothing will "
              "build or push\n", flush=True)

    failed = []
    for svc in services:
        svc_dir = os.path.join(root, svc)
        print(f"=== {svc} ===", flush=True)
        result = subprocess.run(make_cmd, cwd=svc_dir, env=env)
        print()
        if result.returncode != 0:
            failed.append(svc)
            if args.fail_fast:
                break

    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("dry run completed" if args.dry_run else "all builds succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
