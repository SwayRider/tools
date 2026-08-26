#!/usr/bin/env python3
"""Aggregates open findings from every repo's review/CODE_REVIEW_*.md files
(see Docs/REVIEW.md for the convention: "### N. Title" per finding,
"~~Title~~ -- FIXED <date>" once resolved).

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import glob
import os
import re
import sys

from _common import Style, find_repos, pad, require_root, visible_len

# The documented convention (Docs/REVIEW.md) is "### N. ~~Title~~ -- FIXED
# <date>", but in practice across repos the tilde sometimes wraps the number
# too ("### ~~N. Title~~ ..."), and some files mark resolution with a
# checkmark or a bare "- FIXED <date>" instead of a strikethrough at all.
# Treat any of these as fixed rather than strictly enforcing the convention,
# since the goal here is an accurate open-findings list.
FIXED_MARKER_RE = re.compile(
    r"~~|✅|[-—]\s*(FIXED|DONE|VERIFIED|RESOLVED)\b", re.IGNORECASE
)
NUMBERED_RE = re.compile(r"(\d+)\.\s+(.*)$")


def parse_file(path):
    findings = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith("### "):
                continue
            body = line[len("### "):]
            fixed = bool(FIXED_MARKER_RE.search(body))
            m = NUMBERED_RE.match(body.replace("~~", ""))
            if not m:
                continue
            num, title = m.group(1), m.group(2).strip()
            findings.append({"num": num, "title": title, "fixed": fixed})
    return findings


def main():
    root = require_root()
    style = Style(sys.stdout.isatty())

    repos = find_repos(root)
    open_findings = []
    per_repo_counts = {}

    for repo in repos:
        name = os.path.basename(repo)
        review_files = sorted(glob.glob(os.path.join(repo, "review", "CODE_REVIEW_*.md")))
        if not review_files:
            continue
        open_count = fixed_count = 0
        for path in review_files:
            for finding in parse_file(path):
                if finding["fixed"]:
                    fixed_count += 1
                else:
                    open_count += 1
                    open_findings.append({
                        "repo": name,
                        "file": os.path.basename(path),
                        "title": finding["title"],
                    })
        per_repo_counts[name] = (open_count, fixed_count)

    if not per_repo_counts:
        print("no review/CODE_REVIEW_*.md files found under any repo")
        return 0

    width = max(len(r) for r in per_repo_counts)
    print(pad(style.paint(style.bold, "REPO"), width)
          + "  " + style.paint(style.bold, "OPEN") + "   "
          + style.paint(style.bold, "FIXED"))
    for name in sorted(per_repo_counts):
        open_count, fixed_count = per_repo_counts[name]
        open_cell = style.paint(style.red if open_count else style.dim, str(open_count))
        fixed_cell = style.paint(style.green, str(fixed_count))
        print(pad(style.paint(style.bold, name), width)
              + "  " + pad(open_cell, 5) + "  " + fixed_cell)

    total_open = sum(c[0] for c in per_repo_counts.values())
    print()
    if not open_findings:
        print(style.paint(style.green, "no open findings across any repo"))
        return 0

    print(style.paint(style.bold, f"{total_open} open finding(s):"))
    for f in open_findings:
        print(f"  {style.paint(style.bold, f['repo'])} ({f['file']}): {f['title']}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
