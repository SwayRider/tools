# CLAUDE.md

Guidance for Claude Code when working in `tools/`. See [`README.md`](README.md)
for what each script does and how to run it — this file only covers
conventions for maintaining or extending them.

## Conventions

Every script here follows the same shape; match it for anything new:

- Standalone, stdlib-only Python 3, directly executable (`#!/usr/bin/env
  python3` + `chmod +x`). No third-party pip dependencies — if a script
  needs one, it doesn't belong in `tools/` as-is.
- Import shared helpers from `_common.py` (`Style`, `die`, `pad`,
  `visible_len`, `find_repos`, `require_root`) rather than re-implementing
  them. `_common.py` itself is not a CLI.
- Read `SWAYRIDER_ROOT` via `require_root()` and fail fast with its existing
  error message if unset.
- `argparse`-based, with `--dry-run` on anything that mutates state (build,
  test, git/gh operations) — it should print exactly what would run without
  running it.
- Colored terminal output via `Style`, which auto-disables when stdout isn't
  a TTY (`Style(sys.stdout.isatty())`) — never emit raw ANSI codes directly.
- Per-module/per-service loops accept a `--services`/`--modules` subset flag
  and a `--fail-fast` flag where it makes sense to run across many repos.
- Exit code reflects success/failure (`0`/`1`) so scripts compose in CI or
  shell `&&` chains.

## Testing changes

There's no test suite for these scripts — verify by running them for real
against this workspace:

- Read-only scripts (`gitstatus.py`, `depaudit.py`, `reviewstatus.py`,
  `doctor.py`) are safe to just run directly.
- Mutating scripts (`containerbuild.py`, `gotest.py`, `golint.py`,
  `checkprotos.py`, `release.py`) should be exercised with `--dry-run`
  first, and with a narrow `--services`/`--modules`/`--only` scope before a
  full run, since they touch real repos, containers, or (for `release.py`)
  branches/PRs/tags on GitHub.
- Never run `release.py` without `--dry-run` or `--only <module>` as part of
  a verification pass — it's the one script here with real, hard-to-reverse
  side effects (pushed branches, opened PRs, pushed tags) across up to 15
  repos.

## Adding a new script

If it's a repeated manual multi-step or cross-repo process (not a single-
service concern — those belong in that service's own `Makefile`), it's a
tools/ candidate. Extend `_common.py` rather than duplicating a helper a
second time; three or more scripts needing the same small piece of logic is
the threshold, not two.
