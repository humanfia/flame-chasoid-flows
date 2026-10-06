"""The flame chase and its variants, as subflows of one module: `flame_chasoid:<flow>`.

| Flow | |
| --- | --- |
| `agent_cleanup_ralph_loop` | A Ralph loop whose workspace a cleaner agent distills between turns. |
| `agent_cleanup_flame_chase` | A flame chase whose workspace a cleaner agent distills between turns. |
| `fixed_interrupt` | Two fresh sessions alternating at accepted-experiment boundaries. |
| `parallel_git_pr` | Three report-driven lanes of alternating agents, merging by pull request. |
| `parallel` | The same three lanes, only lane 1 writing the tree. Hidden; runs by its ref. |

Each variant keeps its code in a private package of its own beside this file; importing its
flows here is what makes them flows of this module. A bare `flame_chasoid` is refused: name
the variant.
"""

from __future__ import annotations

from _agent_cleanup_flows import agent_cleanup_flame_chase, agent_cleanup_ralph_loop
from _fixed_interrupt.flow import fixed_interrupt, fixed_interrupt_turn
from _parallel_flame_chase.flow import parallel, parallel_lane_turn, parallel_plan
from _parallel_flame_chase_git_pr.flow import (
    parallel_git_pr,
    parallel_git_pr_lane_turn,
    parallel_git_pr_plan,
)

__all__ = [
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
]
