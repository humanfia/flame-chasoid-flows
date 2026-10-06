from __future__ import annotations

from pathlib import Path

import pytest
from hmz.flows import FlowNotFound
from hmz.runtime.flowing import finding, loading
from hmz.runtime.flowing.engine import load_flow

FLOW = Path(__file__).parents[1] / "flame_chasoid"


def test_the_module_holds_every_variant_as_a_subflow() -> None:
    names = set(loading.module_of(FLOW / "__init__.py", None).flows())

    assert names == {
        "agent_cleanup_flame_chase",
        "agent_cleanup_ralph_loop",
        "fixed_interrupt",
        "fixed_interrupt_turn",
        "parallel",
        "parallel_git_pr",
        "parallel_git_pr_lane_turn",
        "parallel_git_pr_plan",
        "parallel_lane_turn",
        "parallel_plan",
    }


def test_the_module_offers_its_variants_by_name_and_no_bare_one() -> None:
    offered = [name for name, _ in finding._named(FLOW / "__init__.py", FLOW.name)]

    # The turns are hidden, and so is `parallel`: only its Git PR variant is offered.
    assert offered == [
        "flame_chasoid:agent_cleanup_flame_chase",
        "flame_chasoid:agent_cleanup_ralph_loop",
        "flame_chasoid:fixed_interrupt",
        "flame_chasoid:parallel_git_pr",
    ]
    with pytest.raises(FlowNotFound, match="flame_chasoid:<flow>"):
        load_flow(str(FLOW), caller_globals={})
