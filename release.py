#!/usr/bin/env python3
"""Interactive multi-repo release tool.

Walks the internal Go dependency chain

    protos -> grpcclients -> swlib -> {swctl, authservice, mailservice,
    routerservice, regionservice, searchservice, tilesservice, swayrider-api}

plus standalone repos with no go.mod and no internal deps to bump
(data-pipeline, infra, swayriderapp, swayrider) -- for those, only the "is
there a new tag to cut" question applies, never the dependency-bump/PR
dance.

Per module: shows the current release tag, bumps go.mod to point at
whatever upstream internal deps were just released (opening a branch + PR
for that and waiting for you to merge it), then asks for the module's own
new tag and pushes it. Requires `gh` to be authenticated and each repo to
be on a clean `main`.

Requires SWAYRIDER_ROOT to be set (exported by .envrc /
.vscode/environment.example).
"""

import argparse
import os
import re
import subprocess
import sys
import time

from _common import Style, die, require_root

ORDER = [
    "protos",
    "grpcclients",
    "swlib",
    "swctl",
    "authservice",
    "mailservice",
    "routerservice",
    "regionservice",
    "searchservice",
    "tilesservice",
    "swayrider-api",
    "data-pipeline",
    "infra",
    "swayriderapp",
    "swayrider",
]

DEPS = {
    "protos": [],
    "grpcclients": ["protos"],
    "swlib": ["protos", "grpcclients"],
    # No go.mod, no internal deps -- never eligible for a dependency bump.
    "data-pipeline": [],
    "infra": [],
    "swayriderapp": [],
    "swayrider": [],
}
DEFAULT_DEPS = ["protos", "grpcclients", "swlib"]  # everything past swlib

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
REQUIRE_RE = {
    dep: re.compile(r"(github\.com/swayrider/" + dep + r")\s+v\d+\.\d+\.\d+")
    for dep in DEFAULT_DEPS
}


def deps_of(module):
    return DEPS.get(module, DEFAULT_DEPS)


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report current tag/at_tag/needs_dep_bump per module without "
        "making any git/gh mutation",
    )
    parser.add_argument("--only", help="process a single module")
    parser.add_argument("--start-from", help="start the chain at this module")
    return parser.parse_args()


def resolve_chain(args):
    if args.only:
        if args.only not in ORDER:
            die(f"unknown module {args.only!r} (known: {', '.join(ORDER)})")
        return [args.only]
    if args.start_from:
        if args.start_from not in ORDER:
            die(f"unknown module {args.start_from!r} (known: {', '.join(ORDER)})")
        return ORDER[ORDER.index(args.start_from):]
    return list(ORDER)


def git(module_dir, *args, check=True):
    result = subprocess.run(
        ["git", "-C", module_dir, *args], capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        die(f"git {' '.join(args)} failed in {module_dir}:\n{result.stderr}")
    return result


def run_mut(cmd, cwd, dry_run, label=None):
    """A mutating command: printed and skipped under --dry-run."""
    shown = label or " ".join(cmd)
    if dry_run:
        print(f"  [dry-run] $ {shown}")
        return True
    print(f"  $ {shown}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode == 0


def parse_version(tag):
    m = TAG_RE.match(tag)
    return tuple(int(x) for x in m.groups())


def latest_tag_at_head(module_dir):
    result = git(module_dir, "tag", "--merged", "HEAD")
    tags = [t for t in result.stdout.splitlines() if TAG_RE.match(t)]
    if not tags:
        return None
    return max(tags, key=parse_version)


def latest_tag_anywhere(module_dir):
    result = git(module_dir, "tag")
    tags = [t for t in result.stdout.splitlines() if TAG_RE.match(t)]
    if not tags:
        return None
    return max(tags, key=parse_version)


def is_at_tag(module_dir, tag):
    if not tag:
        return False
    head = git(module_dir, "rev-parse", "HEAD").stdout.strip()
    at_tag_sha = git(module_dir, "rev-parse", tag).stdout.strip()
    return head == at_tag_sha


def go_mod_dep_version(module_dir, dep):
    path = os.path.join(module_dir, "go.mod")
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        return None
    m = re.search(r"github\.com/swayrider/" + dep + r"\s+(v\d+\.\d+\.\d+)", content)
    return m.group(1) if m else None


def ensure_clean_main(module_dir, module, dry_run):
    branch = git(module_dir, "branch", "--show-current").stdout.strip()
    if branch != "main":
        die(f"{module} is on branch {branch!r}, not main -- checkout main first")
    status = git(module_dir, "status", "--porcelain").stdout
    if status.strip():
        die(f"{module} has a dirty working tree -- commit or stash first:\n{status}")
    git(module_dir, "fetch", "origin", "main", "--tags")
    local = git(module_dir, "rev-parse", "HEAD").stdout.strip()
    remote = git(module_dir, "rev-parse", "origin/main", check=False).stdout.strip()
    if remote and local != remote:
        merge = git(module_dir, "merge", "--ff-only", "origin/main", check=False)
        if merge.returncode != 0:
            die(f"{module}: local main has diverged from origin/main -- "
                "resolve manually before running release.py")


def prompt_bump_menu(style, current_tag):
    base = parse_version(current_tag) if current_tag else (0, 0, 0)
    patch = f"v{base[0]}.{base[1]}.{base[2] + 1}"
    minor = f"v{base[0]}.{base[1] + 1}.0"
    major = f"v{base[0] + 1}.0.0"
    print(f"  current tag: {style.paint(style.yellow, current_tag or '(none)')}")
    print(f"  1) patch -> {patch}")
    print(f"  2) minor -> {minor}")
    print(f"  3) major -> {major}")
    print(f"  4) custom")
    while True:
        choice = input("  choose new tag [1]: ").strip() or "1"
        if choice == "1":
            return patch
        if choice == "2":
            return minor
        if choice == "3":
            return major
        if choice == "4":
            custom = input("  enter tag (vX.Y.Z): ").strip()
            if TAG_RE.match(custom):
                return custom
            print("  invalid tag format, try again")
            continue
        print("  invalid choice")


def wait_for_merge(module_dir, pr_number, dry_run):
    if dry_run:
        print(f"  [dry-run] would wait for PR #{pr_number} to be merged")
        return
    while True:
        input(f"  press Enter once PR #{pr_number} has been merged (Ctrl-C to abort)... ")
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "state", "-q", ".state"],
            cwd=module_dir, capture_output=True, text=True,
        )
        state = result.stdout.strip()
        if state == "MERGED":
            return
        print(f"  PR #{pr_number} is not merged yet (state: {state or 'unknown'})")


def tag_and_push(module_dir, module, tag, dry_run):
    if not run_mut(["git", "tag", "-a", tag, "-m", f"Release {module} {tag}"],
                    module_dir, dry_run):
        die(f"failed to create tag {tag} in {module}")
    if not run_mut(["git", "push", "origin", tag], module_dir, dry_run):
        die(f"failed to push tag {tag} in {module}")


def process_module(style, root, module, released, dry_run):
    module_dir = os.path.join(root, module)
    print(style.paint(style.bold, f"\n=== {module} ==="))

    if not dry_run:
        ensure_clean_main(module_dir, module, dry_run)

    current_tag = latest_tag_at_head(module_dir) if not dry_run else latest_tag_anywhere(module_dir)
    at_tag = is_at_tag(module_dir, current_tag) if current_tag else False

    bumps = {}
    for dep in deps_of(module):
        declared = go_mod_dep_version(module_dir, dep)
        wanted = released.get(dep)
        if declared and wanted and declared != wanted:
            bumps[dep] = (declared, wanted)

    print(f"  current tag: {current_tag or '(none)'}  at_tag: {at_tag}")
    if bumps:
        for dep, (declared, wanted) in bumps.items():
            print(f"  needs bump: {dep} {declared} -> {wanted}")

    if dry_run:
        released[module] = current_tag or "vUNRELEASED"
        return

    # Case A: nothing changed at all.
    if not bumps and at_tag:
        answer = input(f"  no changes for {module}; keep {current_tag}? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            die(f"aborted at {module} -- rerun with --start-from {module} to retry")
        released[module] = current_tag
        return

    # Case B: dependency bump needed -> branch + PR + merge-wait + tag.
    if bumps:
        for dep, (_, wanted) in bumps.items():
            if not run_mut(["go", "get", f"github.com/swayrider/{dep}@{wanted}"],
                            module_dir, dry_run):
                die(f"`go get` failed for {dep}@{wanted} in {module}")
        if not run_mut(["go", "mod", "tidy"], module_dir, dry_run):
            die(f"`go mod tidy` failed in {module}")

        branch = f"chore/bump-deps-{int(time.time())}"
        run_mut(["git", "switch", "-c", branch], module_dir, dry_run)
        run_mut(["git", "add", "go.mod", "go.sum"], module_dir, dry_run)
        summary = ", ".join(f"{d}@{w}" for d, (_, w) in bumps.items())
        run_mut(["git", "commit", "-s", "-m", f"chore: bump internal dependencies ({summary})"],
                 module_dir, dry_run)
        run_mut(["git", "push", "-u", "origin", branch], module_dir, dry_run)

        pr_result = subprocess.run(
            ["gh", "pr", "create", "--base", "main", "--head", branch,
             "--title", f"chore: bump internal dependencies ({summary})",
             "--body", f"Bumps {summary} ahead of releasing {module}."],
            cwd=module_dir, capture_output=True, text=True,
        )
        if pr_result.returncode != 0:
            die(f"`gh pr create` failed in {module}:\n{pr_result.stderr}")
        pr_url = pr_result.stdout.strip().splitlines()[-1]
        pr_number = pr_url.rstrip("/").split("/")[-1]
        print(f"  opened {pr_url}")

        log = git(module_dir, "log", f"{current_tag}..HEAD" if current_tag else "HEAD",
                   "--oneline", check=False).stdout
        if log.strip():
            print("  commits since last tag:\n    " + "\n    ".join(log.splitlines()))

        new_tag = prompt_bump_menu(style, current_tag)
        wait_for_merge(module_dir, pr_number, dry_run)

        git(module_dir, "checkout", "main")
        git(module_dir, "fetch", "origin", "main")
        git(module_dir, "merge", "--ff-only", "origin/main")
        tag_and_push(module_dir, module, new_tag, dry_run)
        released[module] = new_tag
        return

    # Case C: local changes already on main, no dep bump needed -> tag HEAD directly.
    log = git(module_dir, "log", f"{current_tag}..HEAD" if current_tag else "HEAD",
               "--oneline", check=False).stdout
    if log.strip():
        print("  commits since last tag:\n    " + "\n    ".join(log.splitlines()))
    new_tag = prompt_bump_menu(style, current_tag)
    tag_and_push(module_dir, module, new_tag, dry_run)
    released[module] = new_tag


def main():
    args = parse_args()
    root = require_root()
    style = Style(sys.stdout.isatty())
    chain = resolve_chain(args)

    released = {module: latest_tag_anywhere(os.path.join(root, module)) for module in ORDER}

    for module in chain:
        process_module(style, root, module, released, args.dry_run)

    print(style.paint(style.bold, "\ndone"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        sys.exit(130)
