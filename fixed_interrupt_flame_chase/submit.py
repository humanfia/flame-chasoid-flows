"""Blind submission client; its route contains only the current turn's capability."""

from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("submit", "validate", "status"))
    parser.add_argument("artifact", nargs="?")
    args = parser.parse_args()
    route = json.loads(Path(__file__).with_name("route.json").read_text())
    url = urlsplit(route["url"])
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3600)
    headers = {"X-Turn-Token": route["token"]}
    if args.command == "status":
        connection.request("GET", "/session/status", headers=headers)
    elif args.artifact is None:
        # A task that builds its own submission (FlowBench's submit.sh) takes none.
        headers["Content-Length"] = "0"
        connection.request("POST", f"/{args.command}", body=b"", headers=headers)
    else:
        artifact = Path(args.artifact)
        if artifact.is_symlink() or not artifact.is_file():
            parser.error("artifact must be a regular file")
        headers.update(
            {"Content-Length": str(artifact.stat().st_size), "Content-Type": "text/csv"}
        )
        with artifact.open("rb") as stream:
            connection.request("POST", f"/{args.command}", body=stream, headers=headers)
    try:
        response = connection.getresponse()
        data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("evaluator response too large")
        print(json.dumps(json.loads(data), sort_keys=True))
        return 0 if 200 <= response.status < 300 else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
