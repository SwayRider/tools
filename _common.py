"""Shared helpers for the tools/ scripts. Not a CLI itself."""

import os
import sys


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


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


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


def require_root():
    root = os.environ.get("SWAYRIDER_ROOT")
    if not root:
        die("SWAYRIDER_ROOT is not set — run via direnv, or "
            "`source .vscode/environment.example` first")
    return root


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
