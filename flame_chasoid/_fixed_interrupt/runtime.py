from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

from hmz.flows import FlowParams

from .api import DEFAULT_TIME_LIMIT_SECONDS, Params
from .flowbench import FlowBenchGate
from .gate import INSTRUCTIONS, Gate, GateConfig
from .storage import atomic_json


def prompt_for(task: str, seconds: float, instructions: str = INSTRUCTIONS) -> str:
    task = task.replace(
        "There is no medal-based stopping condition and no submission quota.",
        "There is no medal-based stopping condition.",
    )
    if "no submission quota" in task.lower():
        raise ValueError("task contains an incompatible submission-quota claim")
    return (
        f"{task}\n\nThe whole task has a {seconds:g}-second wall-clock budget. "
        f"Keep work and checkpoints in this shared workspace. {instructions}\n"
    )


async def watch_turn(
    work: Any,
    gate: Gate,
    turn_id: str,
    deadline: float,
    poll: float,
    cleanup: float = 5,
) -> str:
    """Watch only for stopping. Admission itself is atomically enforced by the evaluator."""
    running = asyncio.ensure_future(work)
    try:
        while True:
            # Natural return wins if it coincides with a cap boundary.
            if running.done():
                running.result()  # Provider/runtime failures are failures, not natural exits.
                return "natural_exit"
            left = deadline - time.time()
            if left <= 0:
                return "deadline"
            status = await gate.call("status", {}, timeout=min(5, left))
            if status.get("id") != turn_id or status.get("closed"):
                raise ValueError("evaluator lost the current turn")
            if running.done():
                running.result()
                return "natural_exit"
            if status.get("exhausted"):
                return "submission_cap"
            await asyncio.wait(
                {running}, timeout=min(poll, max(0, deadline - time.time()))
            )
    finally:
        running.cancel()
        # Subflow cancellation closes its provider session before the successor starts.
        done, _ = await asyncio.wait({running}, timeout=cleanup)
        if not done:
            running.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            raise TimeoutError(
                "provider did not stop during cleanup; no successor dispatched"
            )
        if not running.cancelled():
            running.exception()


async def run_turn(
    *,
    gate: Gate,
    route: Path,
    turn: Any,
    agents: Any,
    envs: Any,
    actor: int,
    prompt: str,
    turn_id: str,
    limit: int,
    admission_deadline: float,
    stop_deadline: float,
    poll: float,
) -> dict:
    opened = await gate.call(
        "open", {"id": turn_id, "limit": limit, "deadline_epoch": admission_deadline}
    )
    if opened.get("id") != turn_id or opened.get("limit") != limit:
        raise ValueError(
            "evaluator did not acknowledge the requested admission contract"
        )
    started = time.time()
    try:
        atomic_json(route, {"url": gate.route_url, "token": opened["token"]})
        reason = await watch_turn(
            turn(
                prompt,
                agents={"actor": agents[("first_chaser", "second_chaser")[actor]]},
                envs=envs,
                params=FlowParams(),
            ),
            gate,
            turn_id,
            stop_deadline,
            poll,
        )
    finally:
        # A close failure propagates: no successor may overlap an unclosed admission.
        closed = await gate.call("close", {"id": turn_id})
        route.unlink(missing_ok=True)
    accepted = closed.get("accepted")
    if type(accepted) is not int or not 0 <= accepted <= limit:
        raise ValueError("evaluator count violates the requested cap")
    return {
        "id": turn_id,
        "actor": actor,
        "reason": reason,
        "accepted": accepted,
        "last_submission_id": closed.get("last_submission_id"),
        "started_epoch": started,
        "ended_epoch": time.time(),
    }


def outside(paths: tuple[Path, ...], workspace: Path) -> None:
    for path in paths:
        if (
            not path.is_absolute()
            or path.is_symlink()
            or path.resolve().is_relative_to(workspace)
        ):
            raise ValueError(
                "controller paths must be absolute and outside the agent workspace"
            )


def run_root(params: Params, owner: str) -> Path:
    if params.run_dir is not None:
        return Path(params.run_dir)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return Path.home() / ".fixed_interrupt_flame_chase" / f"{stamp}-{owner[:8]}"


def time_limit(params: Params, ctx: Any) -> float:
    """The params' wall clock, else the run budget's duration, else six hours."""
    if params.active_time_limit_seconds is not None:
        return params.active_time_limit_seconds
    duration = getattr(getattr(ctx, "budget", None), "duration", None)
    if duration is not None:
        return duration.total_seconds()
    return DEFAULT_TIME_LIMIT_SECONDS


def trusted_paths(
    params: Params, workspace: Path, owner: str
) -> tuple[Path, GateConfig]:
    root = run_root(params, owner)
    assert params.gate_config is not None
    config_path = Path(params.gate_config)
    outside((root, config_path), workspace)
    config = GateConfig.model_validate_json(config_path.read_text())
    for path in (config.control_key_file, config.ledger_file, config.candidates_dir):
        if (
            not path.is_absolute()
            or path.is_symlink()
            or path.resolve().is_relative_to(workspace)
        ):
            raise ValueError(
                "evaluator files must be absolute and outside the agent workspace"
            )
    return root, config


def admission(params: Params, workspace: Path, owner: str) -> tuple[Path, Any]:
    """The run directory and the gate: native MLE with a gate config, else FlowBench."""
    if params.gate_config is not None:
        root, config = trusted_paths(params, workspace, owner)
        gate = Gate(config)
        if gate.records():
            raise ValueError(
                "fixed_interrupt_flame_chase requires a fresh evaluator ledger"
            )
        return root, gate
    root = run_root(params, owner)
    outside((root,), workspace)
    return root, FlowBenchGate(
        workspace=workspace,
        evaluator_url=params.evaluator_url,
        store=root,
        build_timeout=params.build_timeout_seconds,
    )


async def execute(
    task: str, agents: Any, envs: Any, params: Params, *, ctx: Any, turn: Any
) -> dict:
    workspace = Path(envs["workspace"].workdir).resolve()
    total = time_limit(params, ctx)
    params.check_reserves(total)
    owner = secrets.token_hex(16)
    root, gate = admission(params, workspace, owner)
    native = params.gate_config is not None
    prompt = prompt_for(task, total, gate.instructions)
    root.mkdir(parents=True, exist_ok=False)
    shared = workspace / ".fixed-interrupt"
    # An existing route/ballot might be from an overlapping or interrupted run.
    # A FlowBench worker that is restarted starts a new run in a new container
    # process tree, so what the last one left there is stale rather than live.
    if not native and shared.is_dir() and not shared.is_symlink():
        shutil.rmtree(shared)
    shared.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__).parents[1] / "submit.py", shared / "submit.py")
    route = shared / "route.json"
    started = time.time()
    deadline = started + total
    exploration_end = deadline - params.review_reserve_seconds
    atomic_json(
        root / "contract.json",
        {
            **params.model_dump(),
            "backend": "native" if native else "flowbench",
            "active_time_limit_seconds": total,
            "run_dir": str(root),
            "started_epoch": started,
            "deadline_epoch": deadline,
            "owner": owner,
        },
    )
    gate.start()
    try:
        return await explore_and_review(
            gate=gate,
            route=route,
            shared=shared,
            root=root,
            turn=turn,
            agents=agents,
            envs=envs,
            params=params,
            prompt=prompt,
            owner=owner,
            deadline=deadline,
            exploration_end=exploration_end,
        )
    finally:
        gate.stop()


async def explore_and_review(
    *,
    gate: Any,
    route: Path,
    shared: Path,
    root: Path,
    turn: Any,
    agents: Any,
    envs: Any,
    params: Params,
    prompt: str,
    owner: str,
    deadline: float,
    exploration_end: float,
) -> dict:
    turns: list[dict] = []
    authors: dict[str, int] = {}
    records: list[dict] = []
    result: dict = {"status": "running", "selected_submission_id": None}
    try:
        while time.time() < exploration_end:
            index = len(turns)
            row = await run_turn(
                gate=gate,
                route=route,
                turn=turn,
                agents=agents,
                envs=envs,
                actor=index % 2,
                prompt=prompt,
                turn_id=f"{owner}:{index}",
                limit=params.max_valid_submissions_per_session,
                admission_deadline=exploration_end,
                stop_deadline=exploration_end,
                poll=params.poll_seconds,
            )
            current = gate.records()
            appended = current[len(records) :]
            if (
                len(appended) != row["accepted"]
                or current[: len(records)] != records
                or (
                    current
                    and current[-1]["submission_id"] != row["last_submission_id"]
                )
            ):
                raise ValueError(
                    "closed turn does not match the accepted-candidate archive"
                )
            authors.update({r["submission_id"]: index % 2 for r in appended})
            records = current
            turns.append(row)
            atomic_json(root / "turns.json", turns)
            await asyncio.sleep(
                min(params.rest_seconds, max(0, exploration_end - time.time()))
            )
        standing = records[-1]["submission_id"] if records else None
        result["selected_submission_id"] = standing
        review = {"reason": "review_noop", "standing_submission_id": standing}
        nominee = None
        finalize_attempted = False
        try:
            available = (
                deadline
                - time.time()
                - params.cleanup_reserve_seconds
                - params.finalize_reserve_seconds
            )
            if len(records) >= 2 and available > 0:
                reviewer = 1 - authors[standing]
                review_dir = shared / "review"
                (review_dir / "candidates").mkdir(parents=True)
                ballot = []
                for n, record in enumerate(records, 1):
                    (
                        review_dir / "candidates" / f"{n}{gate.candidate_suffix}"
                    ).write_bytes(gate.artifact(record))
                    ballot.append(
                        {
                            "submission_id": record["submission_id"],
                            "sequence": n,
                            "author": "you"
                            if authors[record["submission_id"]] == reviewer
                            else "peer",
                            "standing": record["submission_id"] == standing,
                        }
                    )
                atomic_json(
                    review_dir / "ballot.json",
                    {"candidates": ballot, "standing_submission_id": standing},
                )
                wall = min(
                    params.review_turn_seconds,
                    max(
                        0,
                        deadline
                        - time.time()
                        - params.cleanup_reserve_seconds
                        - params.finalize_reserve_seconds,
                    ),
                )
                if wall > 0:
                    review_prompt = (
                        f"{prompt}\n\nExploration is closed. You have {wall:g} seconds for this final review. "
                        "The peer wrote the standing candidate. Inspect .fixed-interrupt/review/ballot.json "
                        "and its candidates directory; no test-set scores are provided. Select only an "
                        "already accepted candidate by writing .fixed-interrupt/review/nomination.json "
                        'with {"nominate": "<submission_id>"}. No new submissions are accepted. '
                        "Silence or an invalid nomination retains the standing candidate.\n"
                    )
                    review_turn = await run_turn(
                        gate=gate,
                        route=route,
                        turn=turn,
                        agents=agents,
                        envs=envs,
                        actor=reviewer,
                        prompt=review_prompt,
                        turn_id=f"{owner}:review",
                        limit=0,
                        admission_deadline=deadline,
                        stop_deadline=time.time() + wall,
                        poll=params.poll_seconds,
                    )
                    review.update(
                        {
                            "reviewer": reviewer,
                            "turn": review_turn,
                            "reason": "review_silent",
                        }
                    )
                    nomination = review_dir / "nomination.json"
                    try:
                        nominee = (
                            json.loads(nomination.read_text()).get("nominate")
                            if not nomination.is_symlink()
                            else None
                        )
                    except (OSError, ValueError, AttributeError):
                        nominee = None
                    if isinstance(nominee, str) and nominee in authors:
                        if nominee == standing:
                            review["reason"] = "review_noop"
                        elif time.time() < deadline:
                            finalize_attempted = True
                            await gate.call(
                                "finalize",
                                {"submission_id": nominee},
                                timeout=deadline - time.time(),
                            )
                            result["selected_submission_id"] = nominee
                            review.update(
                                {
                                    "reason": "review_finalized",
                                    "nominated_submission_id": nominee,
                                }
                            )
        except Exception as error:
            review.update(
                {"reason": "review_error", "error_type": type(error).__name__}
            )
            # Keep the already accepted standing result. Never manufacture another ballot.
            # A failed finalize request can be ambiguous; reconcile its committed artifact.
            current = gate.records()
            if current != records:
                nominee_row = next(
                    (r for r in records if r["submission_id"] == nominee),
                    None,
                )
                if (
                    len(current) == len(records) + 1
                    and current[:-1] == records
                    and nominee_row is not None
                    and current[-1].get("artifact_sha256")
                    == nominee_row.get("artifact_sha256")
                ):
                    result["selected_submission_id"] = nominee_row["submission_id"]
                    review["reason"] = "review_finalized_reconciled"
                else:
                    raise ValueError(
                        "review failure left an unrecognized evaluator archive"
                    ) from error
            elif finalize_attempted:
                review["reason"] = "review_finalization_unconfirmed"
        atomic_json(root / "review.json", review)
        result.update(
            {
                "status": "incomplete"
                if review["reason"] == "review_finalization_unconfirmed"
                else "complete",
                "turns": len(turns),
                "accepted": len(records),
                "review": review,
            }
        )
        return result
    except BaseException as error:
        result.update({"status": "failed", "error_type": type(error).__name__})
        raise
    finally:
        route.unlink(missing_ok=True)
        result["ended_epoch"] = time.time()
        atomic_json(root / "result.json", result)
