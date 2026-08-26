#!/usr/bin/env python3
"""Preflight check for a local SwayRider dev setup: env vars, sibling repo
checkouts, Docker, and local service ports.

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import os
import re
import socket
import subprocess
import sys

from _common import Style, die, pad, require_root, visible_len

GO_WORK_MODULES = [
    "authservice",
    "grpcclients",
    "mailservice",
    "protos",
    "regionservice",
    "routerservice",
    "searchservice",
    "swayrider-api",
    "swctl",
    "swlib",
    "tilesservice",
]

LOCAL_PORT_RE = re.compile(r"^SWAYRIDER_LOCAL_(.+)_PORT$")


def check(style, ok, label, detail=""):
    icon = style.paint(style.green, "✓") if ok else style.paint(style.red, "✗")
    line = f"{icon} {label}"
    if detail:
        line += "  " + style.paint(style.dim, detail)
    print(line)
    return ok


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    style = Style(sys.stdout.isatty())
    all_ok = True

    root = os.environ.get("SWAYRIDER_ROOT")
    all_ok &= check(style, bool(root), "SWAYRIDER_ROOT is set",
                     root or "run via direnv, or `source .vscode/environment.example`")
    if not root:
        print(style.paint(style.red, "\ncannot continue without SWAYRIDER_ROOT"), file=sys.stderr)
        return 1

    for mod in GO_WORK_MODULES:
        mod_dir = os.path.join(root, mod)
        exists = os.path.isdir(mod_dir)
        is_repo = exists and os.path.exists(os.path.join(mod_dir, ".git"))
        all_ok &= check(style, exists and is_repo, f"{mod} checked out",
                         mod_dir if not (exists and is_repo) else "")

    docker_ok = False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        docker_ok = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        docker_ok = False
    all_ok &= check(style, docker_ok, "Docker daemon reachable",
                     "" if docker_ok else "is Docker running?")

    local_ports = {}
    for key, value in os.environ.items():
        m = LOCAL_PORT_RE.match(key)
        if not m or not value.isdigit():
            continue
        local_ports[m.group(1)] = int(value)

    if not local_ports:
        check(style, False, "no SWAYRIDER_LOCAL_*_PORT vars found in environment",
              "environment.example may not be sourced")
    else:
        for name, port in sorted(local_ports.items(), key=lambda kv: kv[1]):
            free = not port_in_use(port)
            all_ok &= check(style, free, f"port {port} free ({name})",
                             "" if free else "already in use")

    print()
    if all_ok:
        print(style.paint(style.green, "all checks passed"))
        return 0
    print(style.paint(style.red, "one or more checks failed"), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
