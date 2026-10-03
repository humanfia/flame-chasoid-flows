"""Admission over a FlowBench cell's own evaluator, enforced in the flow process.

A FlowBench task scores whatever its `submit.sh` builds, uploaded to the cell's
evaluator. That evaluator knows nothing of turns, so the turn contract the native
MLE gate enforces -- one open turn, a token, an accepted cap and a shared deadline
-- is enforced here instead, by a loopback service the actor's `submit.py` talks
to. An experiment is a build of `submit.sh` that the evaluator scored without an
`error` in its report, which is how every FlowBench task reports a submission it
could not score.

This is the same trust boundary the native README describes for a local run: the
actors run as the same OS user, so the cap is organizational rather than secret.
What it does guarantee is that the count is the evaluator's answer, taken one
experiment at a time, so concurrent submits cannot overshoot it.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import json
import math
import os
import secrets
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

#: What the actor is told, appended to the task like the native instructions.
INSTRUCTIONS = (
    "Run an experiment with `python3 .fixed-interrupt/submit.py submit`: it builds "
    "this workspace's submission with `submit.sh` and has the evaluator score it. "
    "`python3 .fixed-interrupt/submit.py validate` only builds it."
)

#: The most of a build's output handed back to the actor when it fails.
_OUTPUT_TAIL = 4000
_CHUNK = 1 << 20


class Refused(Exception):
    """A request the turn contract does not admit, answered with its status."""

    def __init__(self, status: HTTPStatus, error: str):
        super().__init__(error)
        self.status = status


class FlowBenchGate:
    """The native gate's control surface, over a FlowBench evaluator."""

    candidate_suffix = ""
    instructions = INSTRUCTIONS

    def __init__(
        self,
        *,
        workspace: Path,
        evaluator_url: str,
        store: Path,
        build_timeout: float = 900,
    ):
        parsed = urlsplit(evaluator_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("evaluator URL must be an http:// URL")
        self.workspace = workspace
        self.evaluator = parsed
        self.store = store
        self.build_timeout = build_timeout
        self.lock = threading.RLock()  # turn and ledger state; never held while scoring
        self.scoring = threading.Lock()  # one experiment at a time, as the cap needs
        self.turns: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if not (self.workspace / "submit.sh").is_file():
            raise ValueError("a FlowBench workspace has a submit.sh")
        (self.store / "candidates").mkdir(parents=True, exist_ok=False)
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def do_GET(self) -> None:
                if self.path != "/session/status":
                    return self._send(HTTPStatus.NOT_FOUND, {"error": "unknown path"})
                self._answer(lambda: gate.session_status(self._token()))

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                if length:
                    return self._send(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "error": "this task builds its own submission with submit.sh; "
                            "run the command without a path"
                        },
                    )
                if self.path == "/submit":
                    self._answer(lambda: gate.submit(self._token()))
                elif self.path == "/validate":
                    self._answer(lambda: gate.validate(self._token()))
                else:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "unknown path"})

            def _token(self) -> str:
                return self.headers.get("X-Turn-Token", "")

            def _answer(self, work: Any) -> None:
                try:
                    status, body = work()
                except Refused as refused:
                    status, body = refused.status, {"error": str(refused)}
                self._send(status, body)

            def _send(self, status: HTTPStatus, body: dict) -> None:
                data = json.dumps(body, sort_keys=True).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    @property
    def route_url(self) -> str:
        if self.server is None:
            raise RuntimeError("admission service is not running")
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    # -- control plane, the flow's side -----------------------------------------

    async def call(self, operation: str, payload: dict, timeout: float = 5) -> dict:
        if operation == "open":
            return self.open_turn(
                payload["id"], payload["limit"], payload["deadline_epoch"]
            )
        if operation == "close":
            return self.close_turn(payload["id"])
        if operation == "status":
            return self.turn_status()
        if operation == "finalize":
            return await asyncio.wait_for(
                asyncio.to_thread(self.finalize, str(payload["submission_id"])),
                timeout,
            )
        raise ValueError(f"unknown control operation: {operation}")

    def current(self) -> dict[str, Any]:
        if not self.turns:
            raise ValueError("no active turn")
        return self.turns[-1]

    def open_turn(self, turn_id: str, limit: int, deadline: float) -> dict[str, Any]:
        with self.lock:
            if not turn_id or type(limit) is not int or limit < 0:
                raise ValueError("invalid turn contract")
            if limit == 0 and not self.turns:
                raise ValueError("selection turn before any submission turn")
            if not math.isfinite(deadline) or deadline <= time.time():
                raise ValueError("expired deadline")
            if any(t["id"] == turn_id for t in self.turns):
                raise ValueError("turn identity reused")
            if self.turns and not self.current()["closed"]:
                raise ValueError("previous turn has not closed")
            budgets = [t["deadline_epoch"] for t in self.turns if t["limit"] > 0]
            if budgets and limit > 0 and deadline != min(budgets):
                raise ValueError("global deadline cannot be reset")
            if budgets and limit == 0 and deadline < min(budgets):
                raise ValueError("selection deadline precedes the budget")
            turn = {
                "id": turn_id,
                "token": secrets.token_urlsafe(32),
                "baseline": len(self.rows),
                "limit": limit,
                "deadline_epoch": deadline,
                "closed": False,
            }
            self.turns.append(turn)
            return dict(turn)

    def close_turn(self, turn_id: str) -> dict[str, Any]:
        with self.lock:
            turn = self.current()
            if turn["id"] != turn_id:
                raise ValueError("wrong turn")
            turn["closed"] = True
            turn["end_sequence"] = len(self.rows)
            return self.turn_status()

    def turn_status(self) -> dict[str, Any]:
        with self.lock:
            turn = self.current()
            count = len(self.rows) - turn["baseline"]
            return {
                "id": turn["id"],
                "accepted": count,
                "limit": turn["limit"],
                "closed": turn["closed"],
                # A zero-limit (review) turn is never exhausted: it owes a file.
                "exhausted": turn["limit"] > 0 and count >= turn["limit"],
                "selection": turn["limit"] == 0,
                "last_submission_id": self.rows[-1]["submission_id"]
                if self.rows
                else None,
            }

    def records(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(row) for row in self.rows]

    def artifact(self, record: dict) -> bytes:
        digest = record["artifact_sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("invalid candidate digest")
        path = self.store / "candidates" / digest
        if path.is_symlink() or not path.is_file():
            raise ValueError("candidate must be a retained regular file")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("candidate digest mismatch")
        return data

    def finalize(self, submission_id: str) -> dict[str, Any]:
        """Re-score an accepted candidate so it is the last record, as natively."""
        with self.scoring:
            with self.lock:
                if not self.turns or not self.current()["closed"]:
                    raise ValueError("finalize requires the last turn to be closed")
                if any(turn.get("finalized") for turn in self.turns):
                    raise ValueError("already finalized")
                deadline = self.current()["deadline_epoch"]
                source = next(
                    (r for r in self.rows if r["submission_id"] == submission_id), None
                )
                if source is None:
                    raise ValueError("unknown submission")
                if source is self.rows[-1]:
                    raise ValueError("nominee is already the last record")
            data = self.artifact(source)
            left = deadline - time.time()
            if left <= 0:
                raise ValueError("finalization deadline expired")
            record = self.upload(data, timeout=left)
            if _error(record) is not None:
                raise ValueError(f"nominee did not score: {_error(record)}")
            with self.lock:
                if time.time() >= deadline:
                    raise ValueError("finalization deadline expired")
                row = self._append(source["artifact_sha256"], record, data=None)
                row["nominated_from"] = submission_id
                self.current()["finalized"] = True
            return {
                "nominated_from": submission_id,
                "artifact_sha256": source["artifact_sha256"],
                "submission_id": row["submission_id"],
            }

    # -- data plane, the actor's side ---------------------------------------------

    def authorize(self, token: str) -> dict[str, Any]:
        with self.lock:
            turn = self.turns[-1] if self.turns else None
            if (
                turn is None
                or not token
                or not hmac.compare_digest(token, turn["token"])
                or turn["closed"]
            ):
                raise Refused(HTTPStatus.FORBIDDEN, "inactive_turn")
            if time.time() >= turn["deadline_epoch"]:
                raise Refused(HTTPStatus.FORBIDDEN, "global deadline")
            return turn

    def session_status(self, token: str) -> tuple[HTTPStatus, dict]:
        self.authorize(token)
        status = self.turn_status()
        # The cap is the measurement: the actor sees what it can count anyway.
        return HTTPStatus.OK, {
            k: status[k] for k in ("accepted", "closed", "exhausted")
        }

    def validate(self, token: str) -> tuple[HTTPStatus, dict]:
        turn = self.authorize(token)
        data = self.build(turn["deadline_epoch"])
        return HTTPStatus.OK, {"valid": True, "bytes": len(data)}

    def submit(self, token: str) -> tuple[HTTPStatus, dict]:
        with self.scoring:
            turn = self.authorize(token)
            with self.lock:
                if len(self.rows) - turn["baseline"] >= turn["limit"]:
                    raise Refused(HTTPStatus.CONFLICT, "submission not accepted")
            data = self.build(turn["deadline_epoch"])
            digest = hashlib.sha256(data).hexdigest()
            with self.lock:
                if any(row["artifact_sha256"] == digest for row in self.rows):
                    return HTTPStatus.OK, {"accepted": False, "duplicate": True}
            left = turn["deadline_epoch"] - time.time()
            if left <= 0:
                raise Refused(HTTPStatus.FORBIDDEN, "global deadline")
            try:
                record = self.upload(data, timeout=left)
            except (OSError, ValueError, http.client.HTTPException) as error:
                raise Refused(
                    HTTPStatus.BAD_GATEWAY,
                    f"evaluator: {type(error).__name__}: {error}",
                ) from error
            error = _error(record)
            with self.lock:
                # A score that lands after its turn closed, or after the deadline,
                # stays in the evaluator's history but is not this turn's experiment.
                if turn is not self.current() or turn["closed"]:
                    return HTTPStatus.CONFLICT, {
                        "accepted": False,
                        "error": "turn closed while scoring",
                        "record": record,
                    }
                if time.time() >= turn["deadline_epoch"]:
                    return HTTPStatus.CONFLICT, {
                        "accepted": False,
                        "error": "global deadline",
                        "record": record,
                    }
                if error is not None:
                    return HTTPStatus.UNPROCESSABLE_ENTITY, {
                        "accepted": False,
                        "record": record,
                    }
                row = self._append(digest, record, data=data)
            return HTTPStatus.OK, {
                "accepted": True,
                "submission_id": row["submission_id"],
                "record": record,
            }

    # -- the task and the evaluator ---------------------------------------------------

    def build(self, deadline: float) -> bytes:
        """What the workspace's `submit.sh` makes, which is all a FlowBench cell uploads."""
        timeout = min(self.build_timeout, deadline - time.time())
        if timeout <= 0:
            raise Refused(HTTPStatus.FORBIDDEN, "global deadline")
        with tempfile.TemporaryDirectory(prefix="fixed-interrupt-") as scratch:
            target = Path(scratch) / "submission"
            try:
                done = subprocess.run(
                    ["bash", "submit.sh", str(target)],
                    cwd=self.workspace,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as expired:
                raise Refused(
                    HTTPStatus.UNPROCESSABLE_ENTITY, "submit.sh did not finish in time"
                ) from expired
            output = (done.stdout + done.stderr).decode(errors="replace")
            if done.returncode != 0 or not target.is_file():
                raise Refused(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    f"submit.sh failed ({done.returncode}): {output[-_OUTPUT_TAIL:]}",
                )
            return target.read_bytes()

    def upload(self, data: bytes, *, timeout: float) -> dict[str, Any]:
        """POSTs one submission to the evaluator as FlowBench's worker does."""
        boundary = secrets.token_hex(16)
        head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="submission"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        connection = http.client.HTTPConnection(
            self.evaluator.hostname, self.evaluator.port, timeout=timeout
        )
        try:
            connection.putrequest("POST", self.evaluator.path.rstrip("/") + "/submit")
            connection.putheader(
                "Content-Type", f"multipart/form-data; boundary={boundary}"
            )
            connection.putheader(
                "Content-Length", str(len(head) + len(data) + len(tail))
            )
            connection.endheaders()
            connection.send(head)
            for start in range(0, len(data), _CHUNK):
                connection.send(data[start : start + _CHUNK])
            connection.send(tail)
            response = connection.getresponse()
            body = response.read(4 * 1024 * 1024 + 1)
        finally:
            connection.close()
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("evaluator response too large")
        record = json.loads(body)
        if not 200 <= response.status < 300 or not isinstance(record, dict):
            raise ValueError(f"evaluator answered {response.status}: {body[:500]!r}")
        if "score" not in record:
            raise ValueError("evaluator record has no score")
        return record

    def _append(
        self, digest: str, record: dict[str, Any], *, data: bytes | None
    ) -> dict[str, Any]:
        """Commits one accepted record; called with the state lock held."""
        if data is not None:
            path = self.store / "candidates" / digest
            if not path.exists():
                path.write_bytes(data)
        row = {
            "submission_id": str(len(self.rows) + 1),
            "artifact_sha256": digest,
            "turn": self.current()["id"],
            "score": record.get("score"),
            "datetime": record.get("datetime"),
        }
        with (self.store / "ledger.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.rows.append(row)
        return row


def _error(record: dict[str, Any]) -> str | None:
    report = record.get("report")
    if isinstance(report, dict) and report.get("error"):
        return str(report["error"])
    return None
