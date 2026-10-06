from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from hmz.flows import HarnessThrottled
from hmz.runtime.flowing.fakes import FakeAgentDriver, FakeEnvDriver, run_fake

from tests.kit import loaded

loaded("fixed_interrupt_flame_chase")
from fixed_interrupt_flame_chase._fixed_interrupt_flame_chase import runtime
from fixed_interrupt_flame_chase._fixed_interrupt_flame_chase.api import Params
from fixed_interrupt_flame_chase._fixed_interrupt_flame_chase.gate import (
    INSTRUCTIONS,
    Gate,
    GateConfig,
)
from fixed_interrupt_flame_chase.evaluator import guarded_types


@pytest.fixture
def native(tmp_path):
    base = ModuleType("synthetic_native")
    records = []

    class BaseState:
        def __init__(self, config):
            self.records = records
            self.lock = threading.RLock()

        def submit(self, artifact, artifact_hash):
            if artifact_hash == "invalid":
                return {"valid": False}
            if any(r["artifact_sha256"] == artifact_hash for r in records):
                return {"duplicate": True}
            result = self._score(artifact)
            row = self._record(result, artifact_hash)
            self._append(row)
            return row

        def _score(self, artifact):
            return {"valid": True, "raw_score": 0.5}

        def _record(self, result, artifact_hash):
            return {
                "submission_id": str(len(records) + 1),
                "artifact_sha256": artifact_hash,
                **result,
            }

        def _append(self, row):
            records.append(row)

        def _append_flowbench_score(self, row):
            pass

        def public_record(self, row):
            return {"submission_id": row["submission_id"]}

    base.State = BaseState
    base.Handler = type("Handler", (), {})
    base._CANDIDATES_DIR = tmp_path
    cls, _ = guarded_types(base, tmp_path / "turns.json", "test-only-control-key" * 2)
    config = {"feedback_mode": "blind", "submission_limit": None}
    state = cls(config)
    return state, lambda: cls(config)


def test_native_gate_serializes_concurrent_accepted_submits(native, tmp_path):
    state, _ = native
    opened = state.open_turn("one", 5, time.time() + 100)

    def submit(i):
        state.request_context.token = opened["token"]
        try:
            state.submit(tmp_path / "synthetic.csv", str(i))
            return True
        except OverflowError:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        accepted = list(pool.map(submit, range(40)))
    assert sum(accepted) == len(state.records) == 5
    assert state.turn_status()["exhausted"]


def test_invalid_duplicate_and_reopen_do_not_reset_count(native, tmp_path):
    state, reload = native
    deadline = time.time() + 100
    opened = state.open_turn("one", 3, deadline)
    state.request_context.token = opened["token"]
    state.submit(tmp_path, "invalid")
    state.submit(tmp_path, "one")
    state.submit(tmp_path, "one")
    assert state.turn_status()["accepted"] == 1
    restored = reload()
    assert restored.open_turn("one", 3, deadline) == opened
    assert restored.turn_status()["accepted"] == 1
    with pytest.raises(ValueError, match="previous turn"):
        restored.open_turn("two", 3, deadline)
    restored.close_turn("one")
    with pytest.raises(ValueError, match="cannot be reset"):
        restored.open_turn("two", 3, deadline + 1)


def test_post_deadline_score_is_not_committed(native, tmp_path, monkeypatch):
    state, _ = native
    clock = SimpleNamespace(now=100.0)
    from fixed_interrupt_flame_chase import evaluator

    monkeypatch.setattr(evaluator, "time", SimpleNamespace(time=lambda: clock.now))
    opened = state.open_turn("one", 5, 101)
    state.request_context.token = opened["token"]

    def score(_):
        clock.now = 102
        return {"valid": True, "raw_score": 0.5}

    monkeypatch.setattr(state, "_score", score)
    with pytest.raises(ValueError, match="global deadline"):
        state.submit(tmp_path, "one")
    assert state.records == []


def test_review_is_zero_admission_and_only_known_artifacts(native, tmp_path):
    state, _ = native
    deadline = time.time() + 100
    opened = state.open_turn("one", 5, deadline)
    state.request_context.token = opened["token"]
    for data in (b"one", b"two"):
        digest = hashlib.sha256(data).hexdigest()
        path = tmp_path / f"{digest}.csv"
        path.write_bytes(data)
        state.submit(path, digest)
    state.close_turn("one")
    review = state.open_turn("review", 0, deadline + 20)
    state.request_context.token = review["token"]
    assert not state.turn_status()["exhausted"]
    with pytest.raises(OverflowError):
        state.submit(tmp_path, "new")
    state.close_turn("review")
    with pytest.raises(ValueError, match="unknown submission"):
        state.finalize("unknown")
    assert state.finalize("1")["nominated_from"] == "1"
    assert state.records[-1]["artifact_sha256"] == state.records[0]["artifact_sha256"]


def test_review_score_cannot_commit_after_deadline(native, tmp_path, monkeypatch):
    state, _ = native
    clock = SimpleNamespace(now=100.0)
    from fixed_interrupt_flame_chase import evaluator

    monkeypatch.setattr(evaluator, "time", SimpleNamespace(time=lambda: clock.now))
    opened = state.open_turn("one", 5, 110)
    state.request_context.token = opened["token"]
    for data in (b"one", b"two"):
        digest = hashlib.sha256(data).hexdigest()
        path = tmp_path / f"{digest}.csv"
        path.write_bytes(data)
        state.submit(path, digest)
    state.close_turn("one")
    state.open_turn("review", 0, 120)
    state.close_turn("review")

    def score(_):
        clock.now = 121
        return {"valid": True, "raw_score": 0.5}

    monkeypatch.setattr(state, "_score", score)
    with pytest.raises(ValueError, match="deadline"):
        state.finalize("1")
    assert len(state.records) == 2


def test_native_flow_contract_and_budget_validation():
    declared = loaded("fixed_interrupt_flame_chase").describe()
    assert declared.name == "fixed_interrupt_flame_chase"
    assert declared.ref == "fixed_interrupt_flame_chase:fixed_interrupt_flame_chase"
    assert not declared.resumable
    assert [a.name for a in declared.agents] == ["first_chaser", "second_chaser"]
    assert all(not a.capabilities for a in declared.agents)
    assert (
        declared.params(
            gate_config="/gate.json", run_dir="/run"
        ).max_valid_submissions_per_session
        == 5
    )
    with pytest.raises(ValueError, match="reserve"):
        Params(gate_config="/gate.json", run_dir="/run", review_reserve_seconds=650)


def test_prompt_does_not_disclose_cap():
    prompt = runtime.prompt_for(
        "There is no medal-based stopping condition and no submission quota.", 21600
    )
    assert "no submission quota" not in prompt
    assert "cap" not in prompt and "5 accepted" not in prompt
    with pytest.raises(ValueError):
        runtime.prompt_for("no submission quota", 21600)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    key = tmp_path / "control.key"
    key.write_text("test-only-credential" * 3)
    config = {
        "url": "http://127.0.0.1:8080",
        "control_key_file": str(key),
        "ledger_file": str(tmp_path / "ledger.jsonl"),
        "candidates_dir": str(tmp_path / "candidates"),
    }
    config_path = tmp_path / "gate.json"
    config_path.write_text(json.dumps(config))
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(runtime, "time", SimpleNamespace(time=lambda: clock.now))

    class FakeGate:
        candidate_suffix = ".csv"
        instructions = INSTRUCTIONS

        def __init__(self, config):
            self.config = config
            self.route_url = config.url
            self.rows = []
            self.calls = []
            self.active = None
            self.baseline = 0
            self.cap_signal = False

        def records(self):
            return list(self.rows)

        def artifact(self, row):
            return b"synthetic-candidate"

        def start(self):
            self.calls.append(("start", None))

        def stop(self):
            self.calls.append(("stop", None))

        async def call(self, op, payload, **_):
            self.calls.append((op, payload))
            if op == "open":
                self.active = payload
                self.baseline = len(self.rows)
                return {**payload, "token": "test-only-turn"}
            if op == "status":
                await asyncio.sleep(0)
                return {
                    "id": self.active["id"],
                    "closed": False,
                    "exhausted": self.cap_signal,
                }
            if op == "close":
                if self.active["limit"]:
                    clock.now += 10
                return {
                    "accepted": len(self.rows) - self.baseline,
                    "last_submission_id": self.rows[-1]["submission_id"]
                    if self.rows
                    else None,
                }
            if op == "finalize":
                return {"nominated_from": payload["submission_id"]}
            raise AssertionError(op)

    gate = FakeGate(GateConfig.model_validate(config))
    monkeypatch.setattr(runtime, "Gate", lambda _: gate)
    params = {
        "gate_config": str(config_path),
        "run_dir": str(tmp_path / "run"),
        "active_time_limit_seconds": 100,
        "review_reserve_seconds": 80,
        "review_turn_seconds": 20,
        "finalize_reserve_seconds": 10,
        "cleanup_reserve_seconds": 10,
        "rest_seconds": 0,
        "poll_seconds": 0.001,
    }
    return SimpleNamespace(workspace=workspace, gate=gate, clock=clock, params=params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nominee,reason,selected",
    [
        ("1", "review_finalized", "1"),
        ("unknown", "review_silent", "2"),
        (None, "review_silent", "2"),
    ],
)
async def test_real_native_flow_fresh_sessions_shared_tree_and_blind_review(
    rig, nominee, reason, selected
):
    order = []

    def reply(name):
        def answer(prompt, **_):
            order.append(name)
            if "final review" in prompt:
                assert (
                    name == "first_chaser"
                )  # Opposite the author of the latest accepted candidate.
                assert "20 seconds" in prompt
                ballot = json.loads(
                    (rig.workspace / ".fixed-interrupt/review/ballot.json").read_text()
                )
                assert [row["author"] for row in ballot["candidates"]] == [
                    "you",
                    "peer",
                ]
                assert "raw_score" not in json.dumps(ballot)
                if nominee is not None:
                    (
                        rig.workspace / ".fixed-interrupt/review/nomination.json"
                    ).write_text(json.dumps({"nominate": nominee}))
            else:
                if name == "first_chaser":
                    (rig.workspace / "checkpoint").write_text("shared")
                else:
                    assert (rig.workspace / "checkpoint").read_text() == "shared"
                rig.gate.rows.append(
                    {"submission_id": str(len(rig.gate.rows) + 1), "raw_score": 0.5}
                )
            return "done"

        return answer

    agents = {
        name: FakeAgentDriver(reply=reply(name))
        for name in ("first_chaser", "second_chaser")
    }
    result = await run_fake(
        loaded("fixed_interrupt_flame_chase"),
        "Train the task",
        agents=agents,
        local=FakeEnvDriver(workdir=str(rig.workspace)),
        params=rig.params,
    )
    assert order == ["first_chaser", "second_chaser", "first_chaser"]
    assert all(
        len(session.prompts) == 1
        for agent in agents.values()
        for session in agent.sessions
    )
    assert result["review"]["reason"] == reason
    assert result["selected_submission_id"] == selected
    opens = [payload for op, payload in rig.gate.calls if op == "open"]
    assert [row["limit"] for row in opens] == [5, 5, 0]
    assert [row["deadline_epoch"] for row in opens] == [1020, 1020, 1100]
    assert not (rig.workspace / ".fixed-interrupt/route.json").exists()


@pytest.mark.asyncio
async def test_cap_interrupt_cancels_and_awaits_running_session(rig):
    cleaned = asyncio.Event()

    async def running():
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    rig.gate.active = {"id": "test"}
    rig.gate.cap_signal = True
    reason = await runtime.watch_turn(running(), rig.gate, "test", 1100, 0.001)
    assert reason == "submission_cap" and cleaned.is_set()


@pytest.mark.asyncio
async def test_provider_error_closes_admission_and_does_not_switch(rig):
    def broken(*args, **kwargs):
        raise HarnessThrottled("synthetic provider error")

    agents = {
        "first_chaser": FakeAgentDriver(reply=broken),
        "second_chaser": FakeAgentDriver(reply="unused"),
    }
    with pytest.raises(HarnessThrottled):
        await run_fake(
            loaded("fixed_interrupt_flame_chase"),
            "task",
            agents=agents,
            local=FakeEnvDriver(workdir=str(rig.workspace)),
            params=rig.params,
        )
    assert not agents["second_chaser"].sessions
    assert any(op == "close" for op, _ in rig.gate.calls)
    assert (
        json.loads((Path(rig.params["run_dir"]) / "result.json").read_text())["status"]
        == "failed"
    )


def test_candidate_hash_verified_before_review(tmp_path):
    key = tmp_path / "control.key"
    key.write_text("test-only-key" * 4)
    gate = Gate(
        GateConfig(
            url="http://localhost:8080",
            control_key_file=key,
            ledger_file=tmp_path / "ledger",
            candidates_dir=tmp_path,
        )
    )
    digest = hashlib.sha256(b"correct").hexdigest()
    (tmp_path / f"{digest}.csv").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        gate.artifact({"artifact_sha256": digest})


@pytest.mark.asyncio
@pytest.mark.parametrize("review_error", [False, True])
async def test_empty_option_preserves_standing_author_and_review_error_fallback(
    rig, review_error
):
    seen = []

    def first(prompt, **_):
        rig.gate.rows.extend([{"submission_id": "1"}, {"submission_id": "2"}])
        return "done"

    def second(prompt, **_):
        seen.append(prompt)
        if "final review" in prompt and review_error:
            raise HarnessThrottled("synthetic review error")
        return "done"

    result = await run_fake(
        loaded("fixed_interrupt_flame_chase"),
        "task",
        agents={"first_chaser": first, "second_chaser": second},
        local=FakeEnvDriver(workdir=str(rig.workspace)),
        params=rig.params,
    )
    assert len(seen) == 2 and "final review" in seen[-1]
    assert result["selected_submission_id"] == "2"
    assert result["review"]["reason"] == (
        "review_error" if review_error else "review_silent"
    )
    assert result["status"] == "complete"


@pytest.mark.asyncio
async def test_natural_return_wins_when_cap_is_also_reached(rig):
    finished = asyncio.get_running_loop().create_future()
    finished.set_result(None)
    rig.gate.cap_signal = True
    assert (
        await runtime.watch_turn(finished, rig.gate, "test", 1100, 0.001)
        == "natural_exit"
    )


@pytest.mark.asyncio
async def test_natural_return_during_status_poll_wins_cap_tie(rig):
    finished = asyncio.get_running_loop().create_future()

    async def status(*args, **kwargs):
        finished.set_result(None)
        return {"id": "test", "closed": False, "exhausted": True}

    rig.gate.call = status
    assert (
        await runtime.watch_turn(finished, rig.gate, "test", 1100, 0.001)
        == "natural_exit"
    )


@pytest.mark.asyncio
async def test_cleanup_timeout_stops_dispatch_without_unbounded_wait(rig):
    release = asyncio.Event()
    started = asyncio.Event()

    async def stubborn():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    running = asyncio.create_task(stubborn())
    await started.wait()
    rig.gate.active = {"id": "test"}
    rig.gate.cap_signal = True
    try:
        with pytest.raises(TimeoutError, match="no successor"):
            await runtime.watch_turn(
                running, rig.gate, "test", 1100, 0.001, cleanup=0.01
            )
    finally:
        release.set()
        await running


@pytest.mark.asyncio
async def test_unknown_finalization_completion_is_not_reported_complete(rig):
    original_call = rig.gate.call

    async def broken_finalize(operation, payload, **kwargs):
        if operation == "finalize":
            raise TimeoutError("synthetic transport timeout")
        return await original_call(operation, payload, **kwargs)

    rig.gate.call = broken_finalize

    def answer(prompt, **_):
        if "final review" in prompt:
            (rig.workspace / ".fixed-interrupt/review/nomination.json").write_text(
                '{"nominate":"1"}'
            )
        else:
            rig.gate.rows.append({"submission_id": str(len(rig.gate.rows) + 1)})
        return "done"

    result = await run_fake(
        loaded("fixed_interrupt_flame_chase"),
        "task",
        agents={"first_chaser": answer, "second_chaser": answer},
        local=FakeEnvDriver(workdir=str(rig.workspace)),
        params=rig.params,
    )
    assert result["status"] == "incomplete"
    assert result["selected_submission_id"] == "2"
    assert result["review"]["reason"] == "review_finalization_unconfirmed"
