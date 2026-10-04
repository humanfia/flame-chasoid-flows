# agent_cleanup _(agent-cleanup-flow)_

Agent Cleanup for hmz: a Ralph loop or a flame chase whose workspace a cleaner agent distills between turns.

Keep a long run's workspace tidy. Coding turns run in fresh sessions, and every few turns a
`cleaner` steps in: it keeps the work, deletes what strayed, writes down what is next, and the
repository's history becomes one commit of what survived. Each fresh session then starts from
a tree that holds only the work under `work_paths` and a short `NEXT.md`. Two
[hmz](https://github.com/humanfia/humanize) flows share that cleaning:

| Flow | Coding agents | Cleaner |
| --- | --- | --- |
| `agent_cleanup:ralph_loop` | `agent`, one [Ralph loop](https://docs.humanfia.ai/humanize/flows/ralph-loop) | `cleaner` |
| `agent_cleanup:flame_chase` | `first_chaser` and `second_chaser`, a [flame chase](https://docs.humanfia.ai/humanize/flows/flame-chase) | `cleaner` |

> [!WARNING]
> **Each cleaning rewrites your git history.** It replaces the repository's history with a
> single commit, `epoch N: distilled tree`. The history it replaces is archived outside the
> repository, never deleted; see [History archive](agent_cleanup/_agent_cleanup/README.md#history-archive)
> for how to read it back. Run this on a clone you are willing to have rewritten.

## Table of Contents

- [Install](#install)
- [Usage](#usage)
  - [Roles](#roles)
  - [Params](#params)
  - [What ends it](#what-ends-it)
  - [Picking it up](#picking-it-up)
- [Contributing](#contributing)
- [License](#license)

## Install

You need [hmz](https://github.com/humanfia/humanize). In hmz, open `/flow`, go to
**Flowverses → official → agent_cleanup** and **Install** it. Both flows come with it.

To run a release without installing it, name it by its git ref:

```sh
hmz exec -f git+https://github.com/humanfia/agent-cleanup-flow@v0.1.1#agent_cleanup:ralph_loop ...
```

## Usage

Name the flow: a bare `agent_cleanup` is refused.

```text
❯ $agent_cleanup:ralph_loop make every test in tests/ pass
❯ $agent_cleanup:flame_chase make every test in tests/ pass
```

```sh
hmz exec -f agent_cleanup:ralph_loop \
    -a agent=claude/claude-opus-5:high -a cleaner=claude/claude-opus-5:high \
    -p work_paths=src -p budget.duration=12h,budget.cost=100 "$(cat TASK.md)"

hmz exec -f agent_cleanup:flame_chase \
    -a first_chaser=claude/claude-opus-5:high -a second_chaser=codex/gpt-5.6-sol:high \
    -a cleaner=claude/claude-opus-5:high \
    -p work_paths=src -p budget.duration=12h,budget.cost=100 "$(cat TASK.md)"
```

Use it on a run long enough that the tree fills up with scratch files, dead ends and notes
nobody reads again. The workspace is the directory `hmz exec` runs in. `-p budget.<limit>=` is
required, and is the run's only budget: whichever of its limits is reached first stops the run.

### Roles

| Role | |
| --- | --- |
| `agent` | `ralph_loop`'s coding turns, each in a fresh session. |
| `first_chaser` · `second_chaser` | `flame_chase`'s coding turns, alternating, each in a fresh session. |
| `cleaner` | One cleaning at a time, in a fresh session that it keeps through its repairs. |
| `human` | You, filled in by hmz. Asked only whether to start on a very large workspace. |

Every role must be a backend the flow can speak to mid-turn, because a turn that runs too long
is told to wrap up: `claude`, `codex`, `kimi` or `pi`. Any other is refused before the first
turn.

### Params

Both flows take the same params. `work_paths` is required: the paths, relative to the
repository, where agents may create or change the work, as `-p work_paths=src,include` or a
JSON list. The rest have defaults:

| Param | Default | |
| --- | --- | --- |
| `cleanup_turns` | `3` | Coding turns between cleanings. `0` never cleans. |
| `next_lines` | `10` | The most lines `NEXT.md` may hold. |
| `comment_lines` | `30` | Comment lines allowed across `work_paths`. Going over is reported, never cut. |
| `repairs` | `2` | Times a cleaning that left too much is handed back to the cleaner, before the flow cuts it down itself. |
| `check_command` | blank | A check to run after each cleaning, such as your test command. If it fails, the cleaning is undone. Blank skips it. |
| `session_timeout_minutes` | `240` | Minutes before a coding turn is told to wrap up. `0` for never. |
| `stop_grace_minutes` | `10` | Minutes after that before the turn is cut off. `0` cuts it off then and there, which can be before the wrap-up message reaches it. |
| `idle_timeout_minutes` | `20` | Minutes of a turn spending nothing before it gets a reminder. `0` for never. |
| `max_tracked_file_mb` | `10` | Files larger than this are never committed. |
| `confirm_large_workspace_copies` | `true` | Ask before starting on a workspace over 5,000 files or 1 GiB. Under `hmz exec` nobody answers, so the run does not start; set it to `false` to only warn. |

What a turn and a cleaning epoch do, what git never tracks, how to read the archived history
and where a run keeps its data are in the
[`_agent_cleanup`](agent_cleanup/_agent_cleanup/README.md) package both flows drive.

### What ends it

- **The [budget](https://docs.humanfia.ai/humanize/features/allowances).** A cleaning it
  interrupts puts the tree back first.
- **Three turns in a row that come to nothing.** A turn that answered nothing, or whose backend
  failed, is taken again on the same seat; the third in a row stops the run.

### Picking it up

Both flows are resumable. `--resume` carries on the turn count and the cleanings done so far,
so the next cleaning comes when it would have. See
[Picking a run up](https://docs.humanfia.ai/humanize/user/resuming).

## Contributing

Issues and pull requests are welcome. The flow is the `agent_cleanup/` directory; its tests
are in `tests/`. With [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest
```

CI runs the same on every pull request. A release is a `vX.Y.Z` tag on `main`; it reaches hmz
users once a `flows/agent_cleanup/X.Y.Z/flow.yaml` pointing at it is merged into
[humanfia/flowverse](https://github.com/humanfia/flowverse).

## License

[Apache-2.0](LICENSE) © Humanfia
