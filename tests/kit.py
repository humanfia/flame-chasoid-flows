from __future__ import annotations

from pathlib import Path
from typing import Any

from hmz.runtime.flowing.engine import load_flow

ROOT = Path(__file__).parents[1]


def loaded(name: str) -> Any:
    """The flow in `<name>/` at the repository's root, as `hmz exec -f` finds it."""
    return load_flow(str(ROOT / name), caller_globals={})
