#!/usr/bin/env python3
"""Audits Go version and internal (swayrider/*) module version consistency
across every module in go.work.

Read-only: reports drift, makes no changes. Two kinds of drift are flagged:
  - a module's `go X.Y` directive differs from the others
  - a module's declared github.com/swayrider/{protos,grpcclients,swlib}
    version is older than that dependency's latest git tag

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import os
import re
import subprocess
import sys

from _common import Style, pad, require_root, visible_len

MODULES = [
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

INTERNAL_DEPS = ["protos", "grpcclients", "swlib"]
GO_VERSION_RE = re.compile(r"^go (\d+\.\d+(?:\.\d+)?)", re.MULTILINE)
REQUIRE_RE = {
    dep: re.compile(
        r"github\.com/swayrider/" + dep + r"\s+(v\d+\.\d+\.\d+)"
    )
    for dep in INTERNAL_DEPS
}
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def parse_version(v):
    return tuple(int(p) for p in v.lstrip("v").split("."))


def read_go_mod(root, module):
    path = os.path.join(root, module, "go.mod")
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def latest_tag(root, module):
    result = subprocess.run(
        ["git", "-C", os.path.join(root, module), "tag"],
        capture_output=True, text=True,
    )
    tags = [t for t in result.stdout.splitlines() if TAG_RE.match(t)]
    if not tags:
        return None
    return max(tags, key=parse_version)


def main():
    root = require_root()
    style = Style(sys.stdout.isatty())

    info = {}
    for mod in MODULES:
        content = read_go_mod(root, mod)
        go_ver = GO_VERSION_RE.search(content)
        deps = {}
        for dep, pat in REQUIRE_RE.items():
            if dep == mod:
                continue
            m = pat.search(content)
            if m:
                deps[dep] = m.group(1)
        info[mod] = {
            "go_version": go_ver.group(1) if go_ver else None,
            "deps": deps,
        }

    latest = {dep: latest_tag(root, dep) for dep in INTERNAL_DEPS}

    go_versions = {i["go_version"] for i in info.values() if i["go_version"]}
    go_drift = len(go_versions) > 1

    width = max(len(m) for m in MODULES)
    print(pad(style.paint(style.bold, "MODULE"), width)
          + "  " + style.paint(style.bold, "GO") + "      "
          + style.paint(style.bold, "DEPS"))

    findings = []
    for mod in MODULES:
        i = info[mod]
        go_cell = i["go_version"] or "-"
        if go_drift and i["go_version"]:
            go_cell = style.paint(style.orange, go_cell)

        dep_parts = []
        for dep in INTERNAL_DEPS:
            if dep == mod or dep not in i["deps"]:
                continue
            declared = i["deps"][dep]
            behind = (
                latest[dep]
                and parse_version(declared) < parse_version(latest[dep])
            )
            if behind:
                dep_parts.append(
                    style.paint(style.red, f"{dep}@{declared} (latest {latest[dep]})")
                )
                findings.append(
                    f"{mod}: {dep}@{declared} is behind latest tag {latest[dep]}"
                )
            else:
                dep_parts.append(f"{dep}@{declared}")

        print(pad(style.paint(style.bold, mod), width)
              + "  " + pad(go_cell, 8)
              + "  " + (", ".join(dep_parts) if dep_parts else style.paint(style.dim, "-")))

    print()
    if go_drift:
        print(style.paint(style.orange, "Go version drift: ")
              + ", ".join(sorted(go_versions)))
    if findings:
        print(style.paint(style.red, "Dependency drift:"))
        for f in findings:
            print(f"  - {f}")
    if not go_drift and not findings:
        print(style.paint(style.green, "no drift found"))

    return 1 if (go_drift or findings) else 0


if __name__ == "__main__":
    sys.exit(main())
