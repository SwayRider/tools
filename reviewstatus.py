#!/usr/bin/env python3
"""Aggregates open findings from every repo's review/CODE_REVIEW_*.md files
(see Docs/REVIEW.md for the convention: "### N. Title" per finding,
"~~Title~~ -- FIXED <date>" once resolved).

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import glob
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from _common import Style, find_repos, pad, require_root, visible_len

LINUX_TERMINALS = [
    "x-terminal-emulator",
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "alacritty",
    "kitty",
    "xterm",
]

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
    current = None
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if line.startswith("### "):
                header = line[len("### "):]
                fixed = bool(FIXED_MARKER_RE.search(header))
                m = NUMBERED_RE.match(header.replace("~~", ""))
                if not m:
                    current = None
                    continue
                num, title = m.group(1), m.group(2).strip()
                current = {"num": num, "title": title, "fixed": fixed, "body": []}
                findings.append(current)
            elif current is not None:
                current["body"].append(line)
    for finding in findings:
        finding["body"] = "\n".join(finding["body"]).strip()
    return findings


def build_fix_prompt(root, finding):
    rel_path = os.path.relpath(finding["file_path"], root)
    return (
        f"Fix this open code-review finding in {finding['repo']} "
        f"({rel_path}):\n\n"
        f"### {finding['title']}\n\n"
        f"{finding['body']}\n\n"
        f"Once fixed, update {rel_path} per the convention in "
        f"Docs/REVIEW.md: strike through the finding's title, append "
        f"\"-- FIXED <date>\", and add a short description of the fix "
        f"immediately after (what changed, which file(s), any tests added)."
    )


def open_new_terminal(script_path):
    system = platform.system()

    if system == "Darwin":
        command_path = script_path + ".command"
        os.rename(script_path, command_path)
        os.chmod(command_path, 0o755)
        subprocess.Popen(["open", "-a", "Terminal", command_path])
        return True

    if system == "Linux":
        os.chmod(script_path, 0o755)
        candidates = []
        term_env = os.environ.get("TERMINAL")
        if term_env:
            candidates.append(term_env)
        candidates.extend(LINUX_TERMINALS)

        for term in candidates:
            term_bin = shutil.which(term)
            if not term_bin:
                continue
            basename = os.path.basename(term_bin)
            if "gnome-terminal" in basename:
                argv = [term_bin, "--", "bash", script_path]
            elif "xfce4-terminal" in basename:
                argv = [term_bin, f"--command=bash {shlex.quote(script_path)}"]
            else:
                argv = [term_bin, "-e", "bash", script_path]
            subprocess.Popen(argv)
            return True

        print(f"no known terminal emulator found -- run manually: bash {script_path}",
              file=sys.stderr)
        return False

    print(f"unsupported platform {system!r} -- run manually: bash {script_path}",
          file=sys.stderr)
    return False


def fix_finding(root, style, finding):
    prompt = build_fix_prompt(root, finding)
    argv = ["claude", "--permission-mode", "plan", prompt]
    script_lines = [
        "#!/bin/bash",
        f"cd {shlex.quote(root)}",
        " ".join(shlex.quote(a) for a in argv),
    ]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, encoding="utf-8"
    ) as f:
        f.write("\n".join(script_lines) + "\n")
        script_path = f.name

    if open_new_terminal(script_path):
        print(style.paint(style.green,
              f"opened a new Claude Code session in a new terminal window "
              f"for {finding['repo']}"))


def fix_loop(root, style, open_findings):
    while True:
        choice = input("\nFix which finding? [number/q]: ").strip().lower()
        if choice in ("", "q", "quit"):
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(open_findings)):
            print(f"invalid selection -- enter a number from 1 to "
                  f"{len(open_findings)}, or q to quit")
            continue
        fix_finding(root, style, open_findings[int(choice) - 1])


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
                        "repo_dir": repo,
                        "file": os.path.basename(path),
                        "file_path": path,
                        "title": finding["title"],
                        "body": finding["body"],
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
    for i, f in enumerate(open_findings, start=1):
        print(f"  {i}. {style.paint(style.bold, f['repo'])} ({f['file']}): {f['title']}")

    if sys.stdin.isatty() and sys.stdout.isatty():
        fix_loop(root, style, open_findings)

    return 1


if __name__ == "__main__":
    sys.exit(main())
