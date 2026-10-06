"""Adapter to the paper's trusted native MLE evaluator admission protocol."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, field_validator


class GateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    control_key_file: Path
    ledger_file: Path
    candidates_dir: Path

    @field_validator("url")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.path not in {"", "/"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "gate URL must be a local HTTP endpoint without credentials or path"
            )
        return value.rstrip("/")


#: What the actor is told about submitting, appended to the task.
INSTRUCTIONS = (
    "Submit prediction files with "
    "`python3 .fixed-interrupt/submit.py submit PATH.csv`; use its `validate` command "
    "for format validation. Evaluator feedback is blind."
)


class Gate:
    candidate_suffix = ".csv"
    instructions = INSTRUCTIONS

    def __init__(self, config: GateConfig):
        self.config = config
        self.key = config.control_key_file.read_text().strip()
        if len(self.key) < 32:
            raise ValueError("control key must contain at least 32 characters")

    @property
    def route_url(self) -> str:
        """Where the actor's `submit.py` reaches the evaluator."""
        return self.config.url

    def start(self) -> None:
        """The native evaluator is a service of its own, started beside the flow."""

    def stop(self) -> None:
        pass

    async def call(self, operation: str, payload: dict, timeout: float = 5) -> dict:
        def request() -> dict:
            req = Request(
                f"{self.config.url}/turn/{operation}",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-Control-Key": self.key},
                method="POST",
            )
            with urlopen(req, timeout=timeout) as response:
                body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise ValueError("evaluator control response too large")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise TypeError("invalid evaluator control response")
            return result

        return await asyncio.to_thread(request)

    def records(self) -> list[dict[str, Any]]:
        path = self.config.ledger_file
        rows = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
        # Read only after close: a submission append must not race this read.
        ids = [row["submission_id"] for row in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate accepted submission identity")
        return rows

    def artifact(self, record: dict) -> bytes:
        digest = record["artifact_sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("invalid candidate digest")
        path = self.config.candidates_dir / f"{digest}.csv"
        if path.is_symlink() or not path.is_file():
            raise ValueError("candidate must be a retained regular file")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("candidate digest mismatch")
        return data
