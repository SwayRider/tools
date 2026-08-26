# tools/

Standalone, stdlib-only Python 3 CLI scripts that automate repetitive
operations across the SwayRider multi-repo workspace. Every script (except
`_common.py`, a shared internal module, not a CLI) is self-contained and
directly executable.

## Requirements

- `SWAYRIDER_ROOT` set to the workspace root (exported by `.envrc` /
  `.vscode/environment.example`). Every script errors out immediately with a
  clear message if it isn't set.
- Python 3, standard library only — no `pip install` needed for the scripts
  themselves.
- A few scripts shell out to other tools already required elsewhere in this
  repo: `golint.py` needs `golangci-lint`, `checkprotos.py` needs the protoc
  toolchain described in `protos/README.md`, `release.py` needs `gh`
  (authenticated) and `go`, `doctor.py` checks for `docker`.

Color output auto-disables when stdout isn't a terminal (piping to a file or
another command gets plain text).

## Scripts

### `gitstatus.py`

Compact colored table of every top-level git repo's branch, commit, tags,
pending changes, and ahead/behind state.

```
gitstatus.py
```

### `containerbuild.py`

Runs `make container-build` for every backend service.

```
containerbuild.py                          # build & push all services
containerbuild.py --services authservice   # just one
containerbuild.py --dry-run                # show resolved tags/commands only
containerbuild.py --show                   # table of resolved tags, no build
containerbuild.py --no-push --dev-latest   # flags forwarded as NO_PUSH / FORCE_DEV_LATEST
```

### `gotest.py` / `golint.py`

Per-module `go test ./...` / `golangci-lint run ./...` across every module in
`go.work` (`golint.py` skips `protos`, which has no `.golangci.yml`), plus
`flutter test` / `flutter analyze` for `swayriderapp` (Flutter, not Go —
each script dispatches per module rather than assuming Go everywhere).

```
gotest.py                              # all modules
gotest.py --modules authservice,swlib  # subset
gotest.py --modules swayriderapp       # runs `flutter test`
gotest.py --fail-fast
gotest.py --dry-run
gotest.py -- -run TestLogin -v         # extra args passed through to `go test`

golint.py --modules swlib -- --fix
golint.py --modules swayriderapp       # runs `flutter analyze`
```

### `checkprotos.py`

Regenerates `protos/` (`cd protos && make`) and checks whether the committed
generated code is still up to date with the `.proto` sources. Aborts if the
tree is already dirty (can't safely test against uncommitted changes).
Exit code doubles as a CI gate.

```
checkprotos.py             # report only; leaves regenerated files if stale
checkprotos.py --revert    # discard the regenerated diff afterward
```

### `depaudit.py`

Read-only audit of Go-version and internal (`github.com/swayrider/*`)
dependency-version consistency across every `go.work` module. Flags a module
whose declared internal dep version is behind that dependency's actual
latest git tag.

```
depaudit.py
```

### `reviewstatus.py`

Aggregates open findings from every repo's `review/CODE_REVIEW_*.md` files
(see `Docs/REVIEW.md` for the convention) into one cross-repo report — counts
per repo plus a consolidated, numbered open-findings list. Detection is
intentionally lenient about how "fixed" is marked (strikethrough per the
documented convention, but also `✅ FIXED`/`✅ DONE`/a bare `- FIXED <date>`,
since not every repo's review files follow the convention exactly).

```
reviewstatus.py
```

When run in a terminal (skipped automatically when piped/non-interactive, so
CI usage is unaffected), it then prompts `Fix which finding? [number/q]:`.
Picking a number opens a **new terminal window** running a fresh `claude
--permission-mode plan "<prompt>"` session, launched from `SWAYRIDER_ROOT`
and seeded with the finding's full title/body plus the `Docs/REVIEW.md`
fix-marking instructions as its first turn — landing straight in plan mode.
`q`/empty exits the prompt. Works on macOS (`open -a Terminal`, via a
generated `.command` file) and Linux (tries `$TERMINAL`, then
`x-terminal-emulator`, `gnome-terminal`, `konsole`, `xfce4-terminal`,
`alacritty`, `kitty`, `xterm` in order, whichever is found first); on
anything else, or if no terminal emulator is found on Linux, it prints the
command to run by hand instead of failing silently.

### `doctor.py`

Preflight check for a local dev setup: `SWAYRIDER_ROOT` set, every `go.work`
module checked out, Docker reachable, and the `SWAYRIDER_LOCAL_*_PORT` ports
free.

```
doctor.py
```

### `release.py`

Interactive multi-repo release tool. Walks the internal Go dependency chain

```
protos -> grpcclients -> swlib -> {swctl, authservice, mailservice,
routerservice, regionservice, searchservice, tilesservice, swayrider-api}
```

plus standalone repos with no `go.mod` and nothing to bump
(`data-pipeline`, `infra`, `swayriderapp`, `swayrider`).

For each module: if nothing changed (no internal dep bump needed and `HEAD`
is already at its latest tag), asks to keep the current tag. If an upstream
dependency was just released, bumps `go.mod` via `go get` + `go mod tidy` on
a branch, opens a PR, waits for you to confirm the merge (verified via
`gh pr view`), then tags the merge commit. If there are local commits since
the last tag but no dependency bump needed, skips the branch/PR step
entirely and tags `HEAD` directly. Every mutating step is interactive —
this is meant to be driven by a human, not run unattended.

```
release.py --dry-run              # report current tag / at-tag / needed bumps, no mutation
release.py --dry-run --only protos
release.py --only mailservice     # process a single module for real
release.py --start-from swctl     # resume the chain partway through
release.py                        # the full chain
```

Never force-pushes, never commits directly to `main`, requires a clean
working tree on `main` before touching a repo. Given the blast radius
(branches, pushes, PRs, tags across up to 15 repos), test with `--dry-run`
and `--only <module>` before running the full chain for real.

## `_common.py`

Shared helpers imported by every script above: `Style` (ANSI color, disabled
automatically off a TTY), `die`, `pad`/`visible_len`, `find_repos`, and
`require_root`. Not a CLI — nothing to run directly.
