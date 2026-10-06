from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from hmz.runtime.flowing.fakes import FakeEnvDriver, run_fake

from tests.kit import loaded

loaded("fixed_interrupt_flame_chase")
from fixed_interrupt_flame_chase._fixed_interrupt_flame_chase import (
    flowbench,
    runtime,
)
from fixed_interrupt_flame_chase._fixed_interrupt_flame_chase.api import Params
from fixed_interrupt_flame_chase._fixed_interrupt_flame_chase.flowbench import (
    FlowBenchGate,
    Refused,
)

#: Builds a fresh submission every run, or one the evaluator reports an error for.
SUBMIT_SH = """\
set -euo pipefail
rm -f "$1"
if [ -f broken ]; then echo "does not build" >&2; exit 3; fi
if [ -f wrong ]; then echo bad > "$1"; exit 0; fi
head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \\n' > "$1"
"""


@pytest.fixture
def evaluator():
    """A FlowBench evaluator: multipart in, one record out, an error for `bad`."""
    uploads: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            assert self.path == "/submit"
            boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
            body = self.rfile.read(int(self.headers["Content-Length"]))
            data = body.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--" + boundary, 1)[0]
            uploads.append(data)
            report = {"error": "wrong output"} if data.startswith(b"bad") else {}
            record = {
                "datetime": "2026-10-03T00:00:00",
                "score": len(uploads),
                "report": report,
            }
            payload = json.dumps(record).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{server.server_address[1]}", uploads=uploads
    )
    server.shutdown()
    server.server_close()


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "submit.sh").write_text(SUBMIT_SH)
    return root


def started(workspace, evaluator, tmp_path):
    gate = FlowBenchGate(
        workspace=workspace, evaluator_url=evaluator.url, store=tmp_path / "run"
    )
    gate.start()
    return gate


def test_all_params_default_so_a_harness_without_p_can_run_it():
    declared = loaded("fixed_interrupt_flame_chase").describe()
    params = declared.params()
    assert params.gate_config is None and params.run_dir is None
    assert params.evaluator_url == "http://evaluator"


def test_time_limit_prefers_params_then_budget_then_six_hours():
    budget = SimpleNamespace(budget=SimpleNamespace(duration=timedelta(hours=2)))
    assert runtime.time_limit(Params(), budget) == 7200
    assert runtime.time_limit(Params(active_time_limit_seconds=3600), budget) == 3600
    assert runtime.time_limit(Params(), SimpleNamespace(budget=None)) == 21600
    with pytest.raises(ValueError, match="no exploration time"):
        Params().check_reserves(600)


def test_concurrent_submits_cannot_overshoot_the_cap(workspace, evaluator, tmp_path):
    gate = started(workspace, evaluator, tmp_path)
    try:
        token = gate.open_turn("one", 3, time.time() + 100)["token"]

        def submit(_):
            try:
                return gate.submit(token)[1]["accepted"]
            except Refused:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(pool.map(submit, range(8)))
        assert sum(accepted) == 3 == len(gate.records()) == len(evaluator.uploads)
        assert gate.turn_status()["exhausted"]
        for row in gate.records():
            assert gate.artifact(row) in evaluator.uploads
    finally:
        gate.stop()


def test_errors_builds_and_duplicates_are_not_experiments(
    workspace, evaluator, tmp_path
):
    gate = started(workspace, evaluator, tmp_path)
    try:
        token = gate.open_turn("one", 5, time.time() + 100)["token"]
        (workspace / "broken").touch()
        with pytest.raises(Refused, match="does not build"):
            gate.submit(token)
        (workspace / "broken").unlink()
        (workspace / "wrong").touch()
        status, body = gate.submit(token)
        assert status == 422 and not body["accepted"]
        assert body["record"]["report"]["error"] == "wrong output"
        assert gate.turn_status()["accepted"] == 0
        (workspace / "submit.sh").write_text('echo same > "$1"\n')
        assert gate.submit(token)[1]["accepted"]
        assert gate.submit(token)[1] == {"accepted": False, "duplicate": True}
        assert gate.turn_status()["accepted"] == 1
        assert gate.validate(token)[1]["valid"]
        gate.close_turn("one")
        with pytest.raises(Refused, match="inactive_turn"):
            gate.submit(token)
    finally:
        gate.stop()


def test_actor_client_reaches_the_gate_and_paths_are_refused(
    workspace, evaluator, tmp_path
):
    gate = started(workspace, evaluator, tmp_path)
    try:
        shared = workspace / ".fixed-interrupt"
        shared.mkdir()
        client = runtime.Path(runtime.__file__).parents[1] / "submit.py"
        (shared / "submit.py").write_bytes(client.read_bytes())
        token = gate.open_turn("one", 1, time.time() + 100)["token"]
        (shared / "route.json").write_text(
            json.dumps({"url": gate.route_url, "token": token})
        )

        def run(*args):
            done = subprocess.run(
                [sys.executable, ".fixed-interrupt/submit.py", *args],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            return done.returncode, json.loads(done.stdout)

        (workspace / "artifact.csv").write_text("x")
        code, body = run("submit", "artifact.csv")
        assert code == 1 and "without a path" in body["error"]
        code, body = run("submit")
        assert code == 0 and body["accepted"] and body["record"]["score"] == 1
        assert run("status") == (0, {"accepted": 1, "closed": False, "exhausted": True})
        code, body = run("submit")
        assert code == 1 and body["error"] == "submission not accepted"
    finally:
        gate.stop()


@pytest.mark.asyncio
async def test_flowbench_flow_caps_turns_reviews_and_refinalizes(
    workspace, evaluator, tmp_path, monkeypatch
):
    clock = SimpleNamespace(now=time.time())
    fake = SimpleNamespace(time=lambda: clock.now)
    monkeypatch.setattr(runtime, "time", fake)
    monkeypatch.setattr(flowbench, "time", fake)
    stale = workspace / ".fixed-interrupt"
    stale.mkdir()
    (stale / "route.json").write_text("{}")  # left by a worker that was restarted
    order, outputs = [], []

    def client(*args):
        done = subprocess.run(
            [sys.executable, ".fixed-interrupt/submit.py", *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        outputs.append((args, done.returncode, done.stdout))
        return done.returncode

    def reply(name):
        def answer(prompt, **_):
            order.append(name)
            if "final review" in prompt:
                ballot = json.loads((stale / "review/ballot.json").read_text())
                assert [c["author"] for c in ballot["candidates"]] == [
                    "you",
                    "you",
                    "peer",
                ]
                assert sorted(
                    p.name for p in (stale / "review/candidates").iterdir()
                ) == [
                    "1",
                    "2",
                    "3",
                ]
                (stale / "review/nomination.json").write_text('{"nominate": "1"}')
                return "done"
            assert "python3 .fixed-interrupt/submit.py submit`" in prompt
            assert "PATH.csv" not in prompt
            if name == "first_chaser":
                assert [client("submit"), client("submit"), client("submit")] == [
                    0,
                    0,
                    1,
                ]
            else:
                (workspace / "wrong").touch()
                assert client("submit") == 1
                (workspace / "wrong").unlink()
                assert client("validate") == 0
                assert client("submit") == 0
            clock.now += 15
            return "done"

        return answer

    result = await run_fake(
        loaded("fixed_interrupt_flame_chase"),
        "Optimize the kernel.",
        agents={name: reply(name) for name in ("first_chaser", "second_chaser")},
        local=FakeEnvDriver(workdir=str(workspace)),
        params={
            "run_dir": str(tmp_path / "run"),
            "evaluator_url": evaluator.url,
            "max_valid_submissions_per_session": 2,
            "active_time_limit_seconds": 100,
            "review_reserve_seconds": 80,
            "review_turn_seconds": 20,
            "finalize_reserve_seconds": 10,
            "cleanup_reserve_seconds": 10,
            "rest_seconds": 0,
            "poll_seconds": 0.001,
        },
    )
    assert order == ["first_chaser", "second_chaser", "first_chaser"], outputs
    assert result["status"] == "complete"
    assert result["accepted"] == 3
    assert result["review"]["reason"] == "review_finalized"
    assert result["selected_submission_id"] == "1"
    # Three accepted, one scored with an error, and the nominee scored again last.
    assert len(evaluator.uploads) == 5
    assert evaluator.uploads[-1] == evaluator.uploads[0]
    ledger = [
        json.loads(line)
        for line in (tmp_path / "run/ledger.jsonl").read_text().splitlines()
    ]
    assert [row["submission_id"] for row in ledger] == ["1", "2", "3", "4"]
    assert ledger[-1]["artifact_sha256"] == ledger[0]["artifact_sha256"]
    contract = json.loads((tmp_path / "run/contract.json").read_text())
    assert contract["backend"] == "flowbench"
    assert not (stale / "route.json").exists()
