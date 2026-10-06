# flame_chasoid _(flame-chasoid-flows)_

Flame Chasoid for hmz: the flame chase and its variants (agent cleanup, fixed interrupt, parallel lanes) as subflows of one flow.

Every flow here is [flame_chase](https://docs.humanfia.ai/humanize/flows/flame-chase), agents
taking turns in fresh sessions over one workspace, with something added. They are one
[hmz](https://github.com/humanfia/humanize) flow, `flame_chasoid`, and each variant is a
subflow of it:

| Flow | What it adds |
| --- | --- |
| `flame_chasoid:agent_cleanup_ralph_loop` | One agent's [Ralph loop](https://docs.humanfia.ai/humanize/flows/ralph-loop) whose workspace a `cleaner` agent distills every few turns. |
| `flame_chasoid:agent_cleanup_flame_chase` | Two agents' flame chase whose workspace a `cleaner` agent distills every few turns. |
| `flame_chasoid:fixed_interrupt` | Two agents alternating at accepted-experiment boundaries, counted by a trusted evaluator, then one blind final review. |
| `flame_chasoid:parallel_git_pr` | Three lanes of alternating agents in clones of their own; a pull request reaches `main` only when a measurement shows it is better. |
| `flame_chasoid:parallel` | Three report-driven lanes of alternating agents; only lane 1 writes your tree. |

A bare `flame_chasoid` is refused: name the variant. `flame_chasoid:parallel` is left out of
the lists where you pick a flow, so only its Git PR variant is offered there; it runs by its
name all the same.

These were three flows of their own before, `agent_cleanup`, `fixed_interrupt_flame_chase` and
`parallel_flame_chase`, each in a repository of its own. Their history is kept here.

| Was | Is |
| --- | --- |
| `agent_cleanup:ralph_loop` | `flame_chasoid:agent_cleanup_ralph_loop` |
| `agent_cleanup:flame_chase` | `flame_chasoid:agent_cleanup_flame_chase` |
| `fixed_interrupt_flame_chase` | `flame_chasoid:fixed_interrupt` |
| `parallel_flame_chase` | `flame_chasoid:parallel` |
| `parallel_flame_chase:git_pr` | `flame_chasoid:parallel_git_pr` |

Params, roles and where each run keeps its data are as they were, so a run's archived history
and state stay where they were. A run started under an old name is not resumed under a new one.

## Table of Contents

- [Install](#install)
- [Usage](#usage)
  - [agent_cleanup_ralph_loop and agent_cleanup_flame_chase](#agent_cleanup_ralph_loop-and-agent_cleanup_flame_chase)
  - [fixed_interrupt](#fixed_interrupt)
  - [parallel_git_pr and parallel](#parallel_git_pr-and-parallel)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Install

You need [hmz](https://github.com/humanfia/humanize). In hmz, open `/flow`, go to
**Flowverses → official → flame_chasoid** and **Install** it. Every variant comes with it.

To run a release without installing it, name it by its git ref:

```sh
hmz exec -f git+https://github.com/humanfia/flame-chasoid-flows@v0.1.0#flame_chasoid:parallel_git_pr ...
```

A clone runs as a flow too: `hmz exec -f /ABS/flame-chasoid-flows/flame_chasoid:<flow>`.

## Usage

### agent_cleanup_ralph_loop and agent_cleanup_flame_chase

Keep a long run's workspace tidy. Coding turns run in fresh sessions, and every few turns a
`cleaner` steps in: it keeps the work, deletes what strayed, writes down what is next, and the
repository's history becomes one commit of what survived. Each fresh session then starts from
a tree that holds only the work under `work_paths` and a short `NEXT.md`.

> [!WARNING]
> **Each cleaning rewrites your git history.** It replaces the repository's history with a
> single commit, `epoch N: distilled tree`. The history it replaces is archived outside the
> repository, never deleted; see [History archive](flame_chasoid/_agent_cleanup/README.md#history-archive)
> for how to read it back. Run this on a clone you are willing to have rewritten.

```text
❯ $flame_chasoid:agent_cleanup_ralph_loop make every test in tests/ pass
❯ $flame_chasoid:agent_cleanup_flame_chase make every test in tests/ pass
```

```sh
hmz exec -f flame_chasoid:agent_cleanup_ralph_loop \
    -a agent=claude/claude-opus-5:high -a cleaner=claude/claude-opus-5:high \
    -p work_paths=src -p budget.duration=12h,budget.cost=100 "$(cat TASK.md)"

hmz exec -f flame_chasoid:agent_cleanup_flame_chase \
    -a first_chaser=claude/claude-opus-5:high -a second_chaser=codex/gpt-5.6-sol:high \
    -a cleaner=claude/claude-opus-5:high \
    -p work_paths=src -p budget.duration=12h,budget.cost=100 "$(cat TASK.md)"
```

Use it on a run long enough that the tree fills up with scratch files, dead ends and notes
nobody reads again. The workspace is the directory `hmz exec` runs in. `-p budget.<limit>=` is
required, and is the run's only budget: whichever of its limits is reached first stops the run.

| Role | |
| --- | --- |
| `agent` | `agent_cleanup_ralph_loop`'s coding turns, each in a fresh session. |
| `first_chaser` · `second_chaser` | `agent_cleanup_flame_chase`'s coding turns, alternating, each in a fresh session. |
| `cleaner` | One cleaning at a time, in a fresh session that it keeps through its repairs. |
| `human` | You, filled in by hmz. Asked only whether to start on a very large workspace. |

Every role must be a backend the flow can speak to mid-turn, because a turn that runs too long
is told to wrap up: `claude`, `codex`, `kimi` or `pi`. Any other is refused before the first
turn.

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
[`_agent_cleanup`](flame_chasoid/_agent_cleanup/README.md) package both flows drive.

**What ends it.** The [budget](https://docs.humanfia.ai/humanize/features/allowances); a
cleaning it interrupts puts the tree back first. Or three turns in a row that come to nothing:
a turn that answered nothing, or whose backend failed, is taken again on the same seat, and the
third in a row stops the run.

**Picking it up.** Both flows are resumable. `--resume` carries on the turn count and the
cleanings done so far, so the next cleaning comes when it would have. See
[Picking a run up](https://docs.humanfia.ai/humanize/user/resuming).

### fixed_interrupt

`flame_chasoid:fixed_interrupt` brings the [HMA](https://github.com/humanfia/hma) paper's
fixed-*k* alternation to the asynchronous hmz flow API. Two agents take ordinary, fresh
sessions in one workspace. A trusted evaluator closes admission after *k* **accepted
experiments**. One final review by the other author can select an older accepted candidate.
The default is *k* = 5, six hours total, 900 seconds reserved for review, and at most 600
seconds of reviewer execution.

The interrupt only needs something that counts accepted experiments. Two admission backends
provide it, chosen by whether `gate_config` is given:

| | native MLE (`gate_config` set) | FlowBench (`gate_config` unset) |
|---|---|---|
| Counts | the native evaluator's receipts | records the cell's evaluator scored without `report.error` |
| Actor submits | `submit.py submit PATH.csv` | `submit.py submit` (builds with the workspace's `submit.sh`) |
| Admission service | `evaluator.py`, started by you | a loopback service inside the flow process |
| Candidate files | `<sha>.csv` in the native evaluator | `run_dir/candidates/<sha>` |
| Leftover `.fixed-interrupt/` | refused | replaced (a restarted FlowBench worker starts a new run) |

This is a native local flow integration. The paper's Docker runner additionally creates a new
container and HOME for every option and isolates private evaluator files. `LocalEnv` does not
provide those guarantees: native conversations are fresh, but HOME, installed packages and the
operating system are shared. Paths outside the workspace are an organizational boundary,
**not** protection from an agent running as the same OS user. Use the
[HMA reproduction repository](https://github.com/humanfia/hma)'s isolated runner for
paper-equivalent containment and full benchmark reruns.

The admission wrapper derives from
`antoinegg1/flowverse/flows/flame_chase_submit3_minimal/evaluator.py` at `e4c8033`. The native
scheduler, adapter and tests were added here; the historical Docker supervisor and
artifacts-only workspace exporter were not copied.

#### Params

Every param has a default, so FlowBench, which passes no `-p`, can run it. The wall clock is
`active_time_limit_seconds` when set, else the run budget's `duration` (FlowBench's
`-c run.yaml`), else six hours.

| Param | Default | |
| --- | --- | --- |
| `gate_config` | unset | Absolute path to the trusted native evaluator connection JSON (see [`gate.example.json`](flame_chasoid/_fixed_interrupt/gate.example.json)); unset for a FlowBench task. |
| `run_dir` | unset | New absolute controller output directory, outside the workspace; a fresh one under `~/.fixed_interrupt_flame_chase/` when unset. |
| `evaluator_url` | `http://evaluator` | The FlowBench evaluator, used when no `gate_config` is given. |
| `max_valid_submissions_per_session` | `5` | *k*: accepted experiments before an option closes. |
| `active_time_limit_seconds` | unset | The whole run's wall clock, review included. |
| `review_reserve_seconds` | `900` | Wall time reserved at the end for review and finalization. |
| `review_turn_seconds` | `600` | The most the reviewer may execute. |
| `finalize_reserve_seconds` | `60` | Reserve for finalization. |
| `cleanup_reserve_seconds` | `35` | Reserve for session cleanup. |
| `build_timeout_seconds` | `900` | How long one FlowBench `submit.sh` may run. |
| `poll_seconds` | `0.25` | How often a running turn's accepted count is checked, at most 5. |
| `rest_seconds` | `1` | Seconds to rest between one turn and the next, at most 60. |

#### Start the trusted admission service

The native MLE backend only. It runs `evaluator.py` from this repository, so keep a clone
where the evaluator process can import it:

```sh
git clone --branch v0.1.0 https://github.com/humanfia/flame-chasoid-flows /ABS/flame-chasoid-flows
```

Prepare a **fresh** native MLE evaluator directory containing `mle-evaluator-server.py`,
`mle-score-worker.py`, and `mle-config.json`, alongside prepared public/private task data and
the pinned grader. The task configuration must have `feedback_mode: "blind"` and
`submission_limit: null`. Its dataset, control and upstream paths must be reachable from the
evaluator process. The [HMA repository](https://github.com/humanfia/hma)'s
`hma-stage-evaluator --config ... --home /ABS/evaluator` can stage these generic files from its
evaluator configuration; it does not download task data by itself. Dataset staging remains the
benchmark integration's responsibility.

The included `evaluator.py` wraps the native evaluator without editing its code. It requires
the native `State` / `Handler`, receipt journal and retained artifact interfaces used by the
paper implementation. A generic scoreboard or a JSON file of model-reported experiments is not
a compatible replacement. Use a new native ledger **and** a new turn journal for every task
run.

Keep evaluator/control directories outside the agent workspace. Create a random local control
key (this is a service capability, not a model API key):

```sh
mkdir -p /ABS/trusted
python3 -c 'import pathlib,secrets; p=pathlib.Path("/ABS/trusted/control.key"); p.write_text(secrets.token_urlsafe(32)); p.chmod(0o600)'
```

Run this in a separate terminal using the benchmark's Python environment:

```sh
PYTHONPATH=/ABS/flame-chasoid-flows/flame_chasoid python -m _fixed_interrupt.evaluator \
  --base /ABS/evaluator/workspace/.flowbench/mle-evaluator-server.py \
  --control /ABS/trusted/turns.json \
  --key-file /ABS/trusted/control.key \
  --host 127.0.0.1 --port 8765
```

Copy [`gate.example.json`](flame_chasoid/_fixed_interrupt/gate.example.json) outside the
workspace and fill its absolute file paths. The endpoint is a local evaluator URL; it is
unrelated to a model provider's API base URL. Provider API keys and base URLs in
[`providers.env.example`](flame_chasoid/_fixed_interrupt/providers.env.example) are empty.
Configure the native CLIs yourself; the flow does not read that template, copy credentials or
configure providers automatically. No credentials are stored in its contract, results or
prompt.

#### Run

Start from the task's shared workspace, containing the public input and task instructions. Use
a new `run_dir` outside it:

```sh
hmz exec -f flame_chasoid:fixed_interrupt \
  -a first_chaser=claude/claude-opus-5:max \
  -a second_chaser=codex/gpt-5.6-sol:max \
  -p budget.duration=6h \
  -p gate_config=/ABS/trusted/gate.json \
  -p run_dir=/ABS/results/new-task-run \
  -p max_valid_submissions_per_session=5 \
  -p active_time_limit_seconds=21600 \
  -p review_reserve_seconds=900 \
  -p review_turn_seconds=600 \
  "$(cat TASK.md)"
```

Model availability and effort values belong to the installed native CLI. The names above
illustrate the paper pair; this flow does not pin provider model versions. The flow's own wall
clock includes review. hmz also requires a framework budget; the example supplies
`-p budget.duration=6h`. A tighter budget can end it earlier, including before review; do not
set a six-hour *active-agent* budget expecting it to replace this wall-clock deadline.

The prompt directs actors to `python3 .fixed-interrupt/submit.py submit PATH.csv`.
`validate PATH.csv` validates without consuming an experiment; `status` exposes only accepted
count, closed and exhausted. Existing task prompts that explicitly point to a different submit
helper must be updated to this helper. The helper does not install itself over existing task
scripts.

The flow refuses an existing output directory, existing `.fixed-interrupt` workspace directory,
or nonempty evaluator ledger. It is intentionally **not resumable**. After a failed run, retain
its evidence and start a new task run with fresh evaluator/control state; never restart an old
budget or run alongside an old agent process.

#### FlowBench tasks

Run it as any other FlowBench flow: no evaluator to start and no params. Each
`submit.py submit` runs `bash submit.sh <tmp>` in the workspace, uploads what it wrote to
`evaluator_url` (`http://evaluator`) exactly as the worker's own autoeval does, and answers
with the evaluator's record. A build that fails, a record with an `error` in its report (aopt's
penalty, kd's parity, ...), a duplicate of an accepted build, and a score that lands after its
turn closed are not experiments. `submit.py validate` only builds. Final review re-uploads the
nominated candidate so it is the cell's last record.

The task's autoeval keeps running beside the flow and is not counted. The two run `submit.sh`
in one workspace unordered, so a task's `submit.sh` must not write into the workspace it builds
from (humanfia/flowbench-internal#58 makes aopt and swe_vllm_kv_cache_watermark hold to that).
Feedback is whatever the task gives: the flow does not hide the evaluator's record, and aopt's
own brief points actors at `/scores`.

#### Protocol

- The evaluator, under its native score lock, enforces accepted count, turn token and
  deadline. Concurrent submissions cannot overshoot *k*. Invalid predictions, validations and
  artifact duplicates do not increment the native receipt count. The polling loop determines
  when to cancel the session; it is not the cap gate.
- Each turn is a hidden subflow, `flame_chasoid:fixed_interrupt_turn`, with one fresh
  session, no `/goal` continuation, no transcript transfer and no additional planning agent.
  Completed subflow cleanup is awaited before another agent starts. Workspace files carry
  over.
- Options end at natural return, the accepted cap, or the exploration deadline. Natural return
  wins when it is already observed at the cap boundary, matching Appendix A's tie convention.
  The historical Docker polling implementation checked exhaustion first; option-closure labels
  from that runner can differ at ties.
- The cap is absent from the task prompt and actor-facing status. Public source and a
  shared-user environment mean it is not secret from deliberate inspection.
- All submitting turns share `start + total - reserve`. A score that finishes after that
  deadline is rejected before its accepted receipt is committed.
- Final review runs only with at least two accepted candidates. It is assigned to the agent
  opposite the author of the latest accepted candidate, even if later options accepted zero
  experiments. The ballot has identities, order and `you`/`peer` authorship, with no scores or
  medal verdicts. Candidate bytes are verified against native artifact hashes before copying.
- Review admission is zero. The reviewer can nominate only an existing candidate and gets its
  actual remaining wall explicitly. Silence, malformed/unknown nominations and reviewer errors
  retain the standing candidate. There is one ballot and no retry. Finalization reuses accepted
  bytes and stays within the global deadline; a recognizably committed receipt is reconciled
  after an error.
- The default reserve includes 35 seconds for cleanup and 60 for finalization. Session
  cancellation is given five seconds before reporting a cleanup failure; no successor is
  dispatched on that failure. hmz/CLI shutdown and OS child processes still depend on the
  backend. A malfunctioning local backend can outlive Python cancellation; the evaluator
  continues rejecting expired submits. A local flow cannot promise Docker-style process
  teardown or a hard OS kill.
- Provider or evaluator failure during exploration propagates and marks the run failed. The
  protocol does not turn authentication errors into natural handoffs.

The final selected identity refers to the nominated original receipt when review changes
selection; native finalization may append a new receipt with the same artifact hash. An
evaluator transport failure during finalization can leave its completion uncertain until the
service settles; that case returns `status: incomplete` and `review_finalization_unconfirmed`,
retaining the pre-review candidate as the fallback. Retain the failed-call evidence and inspect
the authoritative ledger before treating such a run as a benchmark result.

#### Outputs

`run_dir` contains `contract.json` (parameters and original deadline), `turns.json` (option
authors, closure reasons and accepted counts), `review.json`, and `result.json`. hmz retains its
own session transcripts. The shared `.fixed-interrupt/review/` contains only the blind ballot
and candidate copies; the current token route is removed at shutdown. The native evaluator
retains the authoritative receipts and candidate hashes.

### parallel_git_pr and parallel

Chase three leads at once. A coordinator plans three lanes; in each lane two actors take turns
in fresh sessions, and the lanes keep each other informed by report. Two shapes:

| Flow | What reaches your tree |
| --- | --- |
| `flame_chasoid:parallel_git_pr` | **Every lane has a clone and opens pull requests**, and a pull request reaches `main` only when a measurement shows it is better. |
| `flame_chasoid:parallel` | **Only lane 1 writes your tree.** Lanes 2 and 3 work on private copies, and what they find reaches lane 1 as a report and an artifact. |

The bundled `parallel-flame-chase` and `parallel-flame-chase-git-pr` skills define the actor,
report, artifact, checkpoint and resume protocol each shape's agents work by. Both coordinate
local work only: nothing in them releases, deploys, submits or sends anything.

An ordinary `parallel` run on the AOPT task, a cycle-count optimisation, took it from a
147,734-cycle baseline to 969 cycles:

![AOPT ordinary run, all agents' aggregate output tokens](assets/aopt_all_agents.png)

![AOPT ordinary run, the most output tokens any one non-parallel path spent](assets/aopt_max_nonparallel.png)

#### parallel_git_pr

```text
❯ $flame_chasoid:parallel_git_pr get the solver under 10 s on every benchmark in bench/
```

```sh
hmz exec -f flame_chasoid:parallel_git_pr \
    -a orchestrator=codex/gpt-5.6-sol:max \
    -a lane_1_actor_a=codex/gpt-5.6-sol:max,lane_1_actor_b=claude/claude-opus-5:max \
    -a lane_2_actor_a=claude/claude-opus-5:max,lane_2_actor_b=codex/gpt-5.6-sol:max \
    -a lane_3_actor_a=claude/claude-opus-5:max,lane_3_actor_b=codex/gpt-5.6-sol:max \
    -p budget.duration=12h,budget.cost=500 "$(cat TASK.md)"
```

[`examples/git-pr.sh`](flame_chasoid/examples/git-pr.sh) spells every param out.

Use it when the task has a number to beat, such as a benchmark, a score or a size, and a
command that measures it. Nothing here asks a model whether a change is good: the measurement
decides. There is no reviewer. Its setup is fixed to the one that did best in a twelve-hour
Git PR Lite experiment: Report Share and deterministic, receipt-backed PR integration.

How a change reaches `main`:

1. A lane may keep many drafts, but only one pull request ready at a time. A ready pull request
   is frozen, and a newer one from the same lane replaces it.
2. The lane measures it with `pfc evaluate -- <command>`, which runs your evaluator on a clean
   tree and keeps a receipt of the result that cannot be changed. Large artifacts go through
   `pfc artifact put` rather than Git.
3. The lowest-cycle candidate is merged only if its receipt improves on `main`. The central
   repository's hook refuses a `main` that is not exactly the tree that was measured, with two
   exact parents, an allowed-path diff, a head-bound receipt and the matching `PFC-PR` trailer.

What lanes learn from each other is their reports, and the flow's own reports of what was
merged and what was refused.

| Role | |
| --- | --- |
| `orchestrator` | Plans the three lanes, once. |
| `lane_1_actor_a` · `lane_1_actor_b` | Lane 1, taking turns in fresh sessions, in a clone of its own. |
| `lane_2_actor_a` · `lane_2_actor_b` | Lane 2, the same. |
| `lane_3_actor_a` · `lane_3_actor_b` | Lane 3, the same. |
| `human` | You, filled in by hmz. Asked only to confirm copying a very large workspace. |

Any backend can fill any role. The lane actors may also write outside their clone, which is how
they push to the run's central repository.

| Param | Default | |
| --- | --- | --- |
| `rest_seconds` | `1.0` | Seconds the scheduler rests between passes, 0.05 to 60. |
| `resume_mode` | `auto` | `auto` picks up a compatible earlier run; `fresh` starts another. |
| `confirm_large_workspace_copies` | `false` | Ask before making the copies of a very large workspace. Under `hmz exec` nobody answers, so the run does not start. |
| `workspace_file_warning_threshold` | `5000` | Files that make a workspace very large. |
| `workspace_copy_warning_threshold_bytes` | `1073741824` | Bytes of copies that make it very large (1 GiB): the lanes' clones, the planning and integration trees, and the git objects. |

Five more params are fixed, so that a launch cannot turn the measured setup into a different
one: `git_pr_enabled` is `true`, and `global_knowledge_enabled`, `experiment_memory_enabled`,
`token_efficient_enabled` and `main_update_monitor_enabled` are `false`. SQLite/WAL is the live
truth, JSONL the audit stream, and JSON/Markdown disposable views; the
[`_parallel_flame_chase_git_pr`](flame_chasoid/_parallel_flame_chase_git_pr/README.md)
package describes the runtime.

#### parallel

```text
❯ $flame_chasoid:parallel get the solver under 10 s on every benchmark in bench/
```

```sh
hmz exec -f flame_chasoid:parallel \
    -a coordinator=codex/gpt-5.6-sol:max \
    -a lane_1_actor_a=claude/claude-opus-5:max,lane_1_actor_b=codex/gpt-5.6-sol:max \
    -a lane_2_actor_a=claude/claude-opus-5:max,lane_2_actor_b=codex/gpt-5.6-sol:max \
    -a lane_3_actor_a=claude/claude-opus-5:max,lane_3_actor_b=codex/gpt-5.6-sol:max \
    -p budget.duration=12h,budget.cost=500 "$(cat TASK.md)"
```

Use it when the task is open enough that three approaches are worth trying side by side, and
you have the budget for seven agents.

| Role | |
| --- | --- |
| `coordinator` | Plans the three lanes, once, and leaves the run. |
| `lane_1_actor_a` · `lane_1_actor_b` | Lane 1, taking turns. The only ones that write your tree. |
| `lane_2_actor_a` · `lane_2_actor_b` | Lane 2, taking turns, on a private copy. |
| `lane_3_actor_a` · `lane_3_actor_b` | Lane 3, taking turns, on a private copy. |
| `human` | You, filled in by hmz. Asked only to confirm copying a very large workspace. |

Every role may write anywhere its user can and use the web: lanes run your builds, tests and
evaluators, and publish what they make beside the workspace. Any backend can fill any role, and
none of them is run as a `/goal`. The `workspace` environment is the directory the run starts
in, and takes no `-e`.

| Param | Default | |
| --- | --- | --- |
| `rest_seconds` | `1.0` | Seconds the scheduler rests between passes, 0.05 to 60. |
| `resume_mode` | `auto` | `auto` picks up a compatible earlier run; `fresh` starts another. |
| `confirm_large_workspace_copies` | `false` | Ask before copying a very large workspace. Under `hmz exec` nobody answers, so the run stops before copying. |
| `workspace_file_warning_threshold` | `5000` | Files that make a workspace very large. |
| `workspace_copy_warning_threshold_bytes` | `1073741824` | Bytes of copies that make it very large (1 GiB). |

Reports are redelivered until the receiving lane completes a valid turn and acknowledges them.
All three lanes may use task-provided evaluators and attach an accepted candidate to a
`deliverable_ready` report; the runtime binds every candidate to hashed artifacts and keeps a
single-writer cross-lane board at `shared/leaderboard.json`, whose best is in every fresh lane
prompt. Submitting a candidate grants no right to integrate source or act remotely. The
[`_parallel_flame_chase`](flame_chasoid/_parallel_flame_chase/README.md) package describes the
runtime.

#### What ends it

**The [budget](https://docs.humanfia.ai/humanize/features/allowances), or you.** The lanes go
on for as long as the run does, so give it a `-p budget.duration=`. When it runs out, the turns
under way finish and are recorded, and the run stops. In either shape, a lane whose two turns
in a row fail is held until the objective is replanned; the others go on.

#### Picking it up

Both shapes are resumable. `--resume` picks up the newest run in the workspace: the plan, the
copies or the central repository, the receipts, the artifacts, the reports and whose turn each
lane is on. `-p resume_mode=fresh` starts another run instead. For `parallel`, the same task
carries on where it stopped; `continue` reads `TASK.md` if there is one; and a changed
objective is planned again against a fresh copy of your tree, in the same run. See
[Picking a run up](https://docs.humanfia.ai/humanize/user/resuming).

Leave your source tree alone while a run holds it. Only one run may hold a source tree at a
time, whether of `parallel` or of `parallel_git_pr`: a second one refuses to start.

#### Where a run keeps its data

A run keeps its runtime data in a scratch directory of the workspace environment, under hmz's
home, named `parallel_flame_chase-<run-id>` or `parallel_flame_chase_git_pr-<run-id>`:

```text
<hmz home>/envs/<workspace>-<digest>/scratch/parallel_flame_chase-<run-id>-<digest>/
├── objective.md
├── private/lane-2/  private/lane-3/        # the private snapshots
└── shared/
    ├── planning-workspace/  planning-revisions/
    ├── reports/  artifacts/  checkpoints/  staging/
    └── leaderboard.json  state.json  manifest.json  workspace-map.json
```

A run that keeps a journal, as every `hmz exec` run of a resumable flow does, keeps this
directory for `--resume`. A run that keeps none, such as one called from a flow that is not
resumable, has it removed when it ends; what it wrote to your source stays.

## Maintainers

[@antoinegg1](https://github.com/antoinegg1) and [@futrime](https://github.com/futrime), as listed
in [`.github/CODEOWNERS`](.github/CODEOWNERS).

## Contributing

Issues and pull requests are welcome. The flow is the `flame_chasoid/` directory: its
`__init__.py` imports every variant's flows from the private package that holds it. Its tests
are in `tests/`. With [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest
```

The tests need no provider credentials, network services, Docker or GPU. They exercise the real
flow engine with fake agents, real git repositories, the actual admission wrapper with
concurrent synthetic submissions, and the FlowBench backend over real HTTP against a fake
FlowBench evaluator. Live CLIs, paid model calls, real benchmark grading and container
isolation are not verified by them.

CI runs the same on every pull request. A release is a `vX.Y.Z` tag on `main`; it reaches hmz
users once a `flows/flame_chasoid/X.Y.Z/flow.yaml` pointing at it is merged into
[humanfia/flowverse](https://github.com/humanfia/flowverse).

## License

[Apache-2.0](LICENSE) © Humanfia
