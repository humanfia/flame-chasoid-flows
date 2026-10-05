# fixed_interrupt_flame_chase _(fixed-interrupt-flame-chase-flow)_

Fixed Interrupt Flame Chase for hmz: two fresh sessions alternate at accepted-experiment boundaries.

`fixed_interrupt_flame_chase` brings the [HMA](https://github.com/humanfia/hma) paper's fixed-*k* alternation
to the asynchronous [hmz](https://github.com/humanfia/humanize) flow API. Two agents take ordinary,
fresh sessions in one workspace. A trusted evaluator closes admission after *k* **accepted
experiments**. One final review by the other author can select an older accepted candidate.
The default is *k* = 5, six hours total, 900 seconds reserved for review, and at most 600
seconds of reviewer execution.

It is [flame_chase](https://docs.humanfia.ai/humanize/flows/flame-chase) plus that interrupt,
and the interrupt only needs something that counts accepted experiments. Two admission
backends provide it, chosen by whether `gate_config` is given:

| | native MLE (`gate_config` set) | FlowBench (`gate_config` unset) |
|---|---|---|
| Counts | the native evaluator's receipts | records the cell's evaluator scored without `report.error` |
| Actor submits | `submit.py submit PATH.csv` | `submit.py submit` (builds with the workspace's `submit.sh`) |
| Admission service | `evaluator.py`, started by you | a loopback service inside the flow process |
| Candidate files | `<sha>.csv` in the native evaluator | `run_dir/candidates/<sha>` |
| Leftover `.fixed-interrupt/` | refused | replaced (a restarted FlowBench worker starts a new run) |

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
  - [Params](#params)
  - [Start the trusted admission service](#start-the-trusted-admission-service)
  - [Run](#run)
  - [FlowBench tasks](#flowbench-tasks)
  - [Protocol](#protocol)
  - [Outputs](#outputs)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

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

## Install

You need [hmz](https://github.com/humanfia/humanize) and the native CLIs for the two models
you choose. In hmz, open `/flow`, go to **Flowverses → official →
fixed_interrupt_flame_chase** and **Install** it. To run a release without installing it, name
it by its git ref:
`hmz exec -f git+https://github.com/humanfia/fixed-interrupt-flame-chase-flow@v0.2.0#fixed_interrupt_flame_chase`.

The native MLE backend also runs `evaluator.py` from this repository, so for that one keep a
clone where the evaluator process can import it:

```sh
git clone --branch v0.2.0 https://github.com/humanfia/fixed-interrupt-flame-chase-flow /ABS/fixed-interrupt-flame-chase-flow
```

A clone runs as a flow too: `hmz exec -f /ABS/fixed-interrupt-flame-chase-flow/fixed_interrupt_flame_chase`.

For the native MLE backend, prepare a **fresh** native MLE evaluator directory containing
`mle-evaluator-server.py`, `mle-score-worker.py`, and `mle-config.json`, alongside prepared
public/private task data and the pinned grader. The task configuration must have
`feedback_mode: "blind"` and `submission_limit: null`. Its dataset, control and upstream paths
must be reachable from the evaluator process. The [HMA repository](https://github.com/humanfia/hma)'s
`hma-stage-evaluator --config ... --home /ABS/evaluator` can stage these generic files from its
evaluator configuration; it does not download task data by itself. Dataset staging remains the
benchmark integration's responsibility.

## Usage

### Params

Every param has a default, so FlowBench, which passes no `-p`, can run it. The wall clock is
`active_time_limit_seconds` when set, else the run budget's `duration` (FlowBench's
`-c run.yaml`), else six hours.

| Param | Default | |
| --- | --- | --- |
| `gate_config` | unset | Absolute path to the trusted native evaluator connection JSON (see [`gate.example.json`](fixed_interrupt_flame_chase/gate.example.json)); unset for a FlowBench task. |
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

### Start the trusted admission service

The native MLE backend only. The included `evaluator.py` wraps the native evaluator without
editing its code. It requires the native `State` / `Handler`, receipt journal and retained
artifact interfaces used by the paper implementation. A generic scoreboard or a JSON file of
model-reported experiments is not a compatible replacement. Use a new native ledger **and** a
new turn journal for every task run.

Keep evaluator/control directories outside the agent workspace. Create a random local control
key (this is a service capability, not a model API key):

```sh
mkdir -p /ABS/trusted
python3 -c 'import pathlib,secrets; p=pathlib.Path("/ABS/trusted/control.key"); p.write_text(secrets.token_urlsafe(32)); p.chmod(0o600)'
```

Run this in a separate terminal using the benchmark's Python environment, which must also have
hmz installed:

```sh
PYTHONPATH=/ABS/fixed-interrupt-flame-chase-flow python -m fixed_interrupt_flame_chase.evaluator \
  --base /ABS/evaluator/workspace/.flowbench/mle-evaluator-server.py \
  --control /ABS/trusted/turns.json \
  --key-file /ABS/trusted/control.key \
  --host 127.0.0.1 --port 8765
```

Copy [`gate.example.json`](fixed_interrupt_flame_chase/gate.example.json) outside the
workspace and fill its absolute file paths. The endpoint is a local evaluator URL; it is
unrelated to a model provider's API base URL. Provider API keys and base URLs in
[`providers.env.example`](fixed_interrupt_flame_chase/providers.env.example) are empty.
Configure the native CLIs yourself; the flow does not read that template, copy credentials or
configure providers automatically. No credentials are stored in its contract, results or
prompt.

### Run

Start from the task's shared workspace, containing the public input and task instructions. Use
a new `run_dir` outside it:

```sh
hmz exec -f fixed_interrupt_flame_chase \
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

### FlowBench tasks

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

### Protocol

- The evaluator, under its native score lock, enforces accepted count, turn token and
  deadline. Concurrent submissions cannot overshoot *k*. Invalid predictions, validations and
  artifact duplicates do not increment the native receipt count. The polling loop determines
  when to cancel the session; it is not the cap gate.
- Each turn is a hidden subflow with one fresh session, no `/goal` continuation, no transcript
  transfer and no additional planning agent. Completed subflow cleanup is awaited before
  another agent starts. Workspace files carry over.
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

### Outputs

`run_dir` contains `contract.json` (parameters and original deadline), `turns.json` (option
authors, closure reasons and accepted counts), `review.json`, and `result.json`. hmz retains its
own session transcripts. The shared `.fixed-interrupt/review/` contains only the blind ballot
and candidate copies; the current token route is removed at shutdown. The native evaluator
retains the authoritative receipts and candidate hashes.

## Maintainers

[@antoinegg1](https://github.com/antoinegg1) and [@futrime](https://github.com/futrime), as listed
in [`.github/CODEOWNERS`](.github/CODEOWNERS).

## Contributing

Issues and pull requests are welcome. The flow is the `fixed_interrupt_flame_chase/`
directory; its tests are in `tests/`. With [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest
```

The tests need no provider credentials, network services, Docker or GPU. They exercise the real
flow engine with fake agents, the actual admission wrapper with concurrent synthetic
submissions, and the FlowBench backend over real HTTP against a fake FlowBench evaluator. Live
CLIs, paid model calls, real benchmark grading and container isolation are not verified by
them.

CI runs the same on every pull request. A release is a `vX.Y.Z` tag on `main`; it reaches hmz
users once a `flows/fixed_interrupt_flame_chase/X.Y.Z/flow.yaml` pointing at it is merged into
[humanfia/flowverse](https://github.com/humanfia/flowverse).

## License

[Apache-2.0](LICENSE) © Humanfia
