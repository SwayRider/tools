#!/usr/bin/env python3
"""Compact overview of all git repositories under the current directory.

Scans top-level directories for .git and prints one row per repo:

    REPO          BRANCH               CHANGES   PUSH      STATUS
    authservice   feature/totp-mfa     3  2s1m  ↑2        ● dirty
    protos        feature/totp-mfa     -         -         ✓ clean
    swayriderapp  feat/mfa-login-data-path -     -         ⎇ on branch

Standard library only -- run as `gitstatus.py` (it's on PATH once .envrc is
loaded) or directly as `tools/gitstatus.py`. Requires SWAYRIDER_ROOT to be
set (exported by .envrc / .vscode/environment.example).
"""

import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# ANSI helpers (disabled when stdout is not a terminal)
# ---------------------------------------------------------------------------


class Style:
    def __init__(self, enabled):
        self.reset = "\033[0m" if enabled else ""
        self.bold = "\033[1m" if enabled else ""
        self.dim = "\033[2m" if enabled else ""
        self.green = "\033[32m" if enabled else ""
        self.bright_green = "\033[92m" if enabled else ""
        self.orange = "\033[38;5;208m" if enabled else ""
        self.yellow = "\033[33m" if enabled else ""
        self.cyan = "\033[36m" if enabled else ""
        self.magenta = "\033[35m" if enabled else ""
        self.red = "\033[31m" if enabled else ""

    def paint(self, color, text):
        return f"{color}{text}{self.reset}"


def visible_len(s):
    """String length ignoring ANSI escape sequences."""
    length = 0
    inside = False
    for ch in s:
        if ch == "\033":
            inside = True
        elif inside and ch == "m":
            inside = False
        elif not inside:
            length += 1
    return length


def pad(s, width):
    return s + " " * max(0, width - visible_len(s))


# ---------------------------------------------------------------------------
# Git data collection
# ---------------------------------------------------------------------------


def find_repos(root="."):
    """Top-level directories containing a .git entry."""
    repos = []
    try:
        entries = sorted(os.listdir(root))
    except OSError as e:
        die(f"cannot list {root}: {e}")
    for name in entries:
        path = os.path.join(root, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, ".git")):
            repos.append(path)
    return repos


def collect(repo):
    """Run one `git status --porcelain=v2 --branch` and parse everything."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain=v2", "--branch"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as e:
        return {"error": str(e).strip()}

    info = {
        "branch": "?",
        "upstream": None,
        "ahead": 0,
        "behind": 0,
        "staged": 0,
        "modified": 0,
        "untracked": 0,
        "unmerged": 0,
        "commit": None,
        "recent_tag": None,
        "error": None,
    }

    for line in out.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head "):]
            if head == "(detached)":
                info["branch"] = "(detached)"
            elif head == "(initial)":
                info["branch"] = "(no commits)"
            else:
                info["branch"] = head
        elif line.startswith("# branch.upstream "):
            info["upstream"] = line[len("# branch.upstream "):]
        elif line.startswith("# branch.ab "):
            # "# branch.ab +2 -1"
            parts = line.split()
            for p in parts[2:]:
                if p.startswith("+"):
                    info["ahead"] = int(p[1:])
                elif p.startswith("-"):
                    info["behind"] = int(p[1:])
        elif line.startswith("## "):
            # Fallback for git versions without full v2 headers
            head = line[3:]
            if head.startswith("No commits yet on "):
                info["branch"] = "(no commits)"
            elif head.startswith("HEAD (no branch)"):
                info["branch"] = "(detached)"
            else:
                branch = head.split("...", 1)[0]
                if " " in branch:  # e.g. "main [gone]"
                    branch = branch.split(" ", 1)[0]
                info["branch"] = branch
        elif line.startswith("? "):
            info["untracked"] += 1
        elif line.startswith("u "):
            info["unmerged"] += 1
        elif line.startswith(("1 ", "2 ")):
            xy = line.split()[1]
            if xy[0] not in (".", "?"):  # index differs from HEAD
                info["staged"] += 1
            if xy[1] not in (".", "?") or xy[0] == "U":  # worktree differs
                info["modified"] += 1

    info["total"] = (
        info["staged"] + info["modified"] + info["untracked"] + info["unmerged"]
    )

    # Short commit hash
    if not info["error"]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            info["commit"] = result.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            info["commit"] = None

    # Tags pointing at HEAD
    info["tags"] = []
    if not info["error"]:
        try:
            result = subprocess.run(
                ["git", "tag", "--points-at", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            info["tags"] = [t for t in result.stdout.splitlines() if t]
        except (subprocess.SubprocessError, OSError):
            pass

    # Fallback: nearest ancestor tag when HEAD itself is untagged on main/master
    if not info["error"] and not info["tags"] and info["branch"] in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            info["recent_tag"] = result.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            pass

    return info


def breakdown(info):
    """Compact per-type breakdown string, e.g. "2s 3m 1u"; empty when clean."""
    parts = []
    if info["staged"]:
        parts.append(f"{info['staged']}s")
    if info["modified"]:
        parts.append(f"{info['modified']}m")
    if info["unmerged"]:
        parts.append(f"{info['unmerged']}!")
    if info["untracked"]:
        parts.append(f"{info['untracked']}u")
    return " ".join(parts)


MAIN_BRANCHES = {"main", "master", "(detached)", "(no commits)"}


def _color_for(info, style):
    """Return the ANSI color that matches the branch/status color scheme."""
    if info.get("error"):
        return style.red
    is_main = info["branch"] in MAIN_BRANCHES
    dirty = bool(info["total"])
    syncing = bool(info["ahead"] or info["behind"])
    if dirty:
        return style.red
    if syncing:
        return style.orange
    if is_main:
        return style.bright_green
    return style.green


def status_icon(st, style):
    color = _color_for(st, style)
    if st.get("error"):
        return style.paint(color, "✗"), "error"
    if st["ahead"] and st["behind"]:
        return style.paint(color, "⇄"), "diverged"
    if st["total"]:
        return style.paint(color, "●"), "dirty"
    if st["ahead"]:
        return style.paint(color, "⬆"), "unpushed"
    if st["behind"]:
        return style.paint(color, "⬇"), "behind"
    if st["branch"] not in MAIN_BRANCHES:
        return style.paint(color, "⎇"), "feature-branch"
    return style.paint(color, "✓"), "clean"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

HEADER = ("REPO", "BRANCH", "COMMIT", "TAG", "CHANGES", "", "PUSH", "STATUS")


def push_cell(info, style):
    if info["error"]:
        return "-"
    if info["upstream"] is None:
        return style.paint(style.dim, "(no up)")
    marks = []
    if info["ahead"]:
        marks.append(style.paint(style.cyan, f"↑{info['ahead']}"))
    if info["behind"]:
        marks.append(style.paint(style.magenta, f"↓{info['behind']}"))
    if not marks:
        return style.paint(style.dim, "-")
    return "".join(marks)


def changes_cell(info, style):
    if info["error"]:
        return "-"
    if not info["total"]:
        return style.paint(style.dim, "-")
    cell = str(info["total"])
    detail = breakdown(info)
    if detail:
        cell += "  " + style.paint(style.dim, detail)
    return cell


def branch_cell(info, style):
    if info["error"]:
        return "-"
    if info["branch"] in ("(detached)", "(no commits)"):
        return style.paint(style.dim, info["branch"])
    return style.paint(_color_for(info, style), info["branch"])


def commit_cell(info, style):
    if info["error"] or not info["commit"]:
        return style.paint(style.dim, "-")
    return style.paint(style.dim, info["commit"])


def tags_cell(info, style):
    """List of painted tag names on HEAD, one per line; ["-"] when none."""
    if info["error"] or not info["tags"]:
        if not info["error"] and info.get("recent_tag"):
            return [style.paint(style.dim, f"({info['recent_tag']})")]
        return [style.paint(style.dim, "-")]
    return [style.paint(style.yellow, t) for t in info["tags"]]


def main():
    root = os.environ.get("SWAYRIDER_ROOT")
    if not root:
        die("SWAYRIDER_ROOT is not set — run via direnv, or "
            "`source .vscode/environment.example` first")
    repos = find_repos(root)
    if not repos:
        print("no git repositories found", file=sys.stderr)
        return 1

    style = Style(sys.stdout.isatty())

    rows = []
    for repo_path in repos:
        info = collect(repo_path)
        icon, _label = status_icon(info, style)
        rows.append(
            {
                "repo": os.path.basename(repo_path),
                "branch": branch_cell(info, style),
                "commit": commit_cell(info, style),
                "tags": tags_cell(info, style),
                "changes": changes_cell(info, style),
                "push": push_cell(info, style),
                "status": icon,
                "info": info,
            }
        )

    widths = {
        "repo": max(visible_len(r["repo"]) for r in rows),
        "branch": max(
            visible_len(HEADER[1]), max(visible_len(r["branch"]) for r in rows)
        ),
        "commit": max(
            visible_len(HEADER[2]), max(visible_len(r["commit"]) for r in rows)
        ),
        "tags": max(
            visible_len(HEADER[3]),
            max(visible_len(t) for r in rows for t in r["tags"]),
        ),
        "changes": max(visible_len(HEADER[4]), max(visible_len(r["changes"]) for r in rows)),
        "push": max(len(HEADER[6]), max(visible_len(r["push"]) for r in rows)),
    }

    header = "  ".join(
        [
            pad(style.paint(style.bold, HEADER[0]), widths["repo"]),
            pad(style.paint(style.bold, HEADER[1]), widths["branch"]),
            pad(style.paint(style.bold, HEADER[2]), widths["commit"]),
            pad(style.paint(style.bold, HEADER[3]), widths["tags"]),
            pad(style.paint(style.bold, HEADER[4]), widths["changes"]),
            "",
            pad(style.paint(style.bold, HEADER[6]), widths["push"]),
            HEADER[7],
        ]
    )
    print(header)
    for r in rows:
        blank_repo = pad("", widths["repo"])
        blank_branch = pad("", widths["branch"])
        blank_commit = pad("", widths["commit"])
        blank_changes = pad("", widths["changes"])
        blank_push = pad("", widths["push"])
        for i, tag in enumerate(r["tags"]):
            first = i == 0
            print(
                "  ".join(
                    [
                        pad(style.paint(style.bold, r["repo"]), widths["repo"])
                        if first
                        else blank_repo,
                        pad(r["branch"], widths["branch"]) if first else blank_branch,
                        pad(r["commit"], widths["commit"]) if first else blank_commit,
                        pad(tag, widths["tags"]),
                        pad(r["changes"], widths["changes"]) if first else blank_changes,
                        "",
                        pad(r["push"], widths["push"]) if first else blank_push,
                        r["status"] if first else "",
                    ]
                )
            )

    # Summary line
    dirty = sum(1 for r in rows if r["info"].get("total"))
    unpushed = sum(1 for r in rows if r["info"].get("ahead"))
    errors = sum(1 for r in rows if r["info"].get("error"))
    bits = [
        f"{len(rows)} repo{'s' if len(rows) != 1 else ''}",
        f"{dirty} dirty",
        f"{unpushed} with unpushed commits",
    ]
    if errors:
        bits.append(f"{errors} error{'s' if errors != 1 else ''}")
    print()
    print(style.paint(style.dim, ": ".join([bits[0], ", ".join(bits[1:])])))
    return 0


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
