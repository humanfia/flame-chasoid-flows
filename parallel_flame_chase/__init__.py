"""Run the report-driven Parallel Flame Chase without mission audits.

`parallel_flame_chase` is the flow a bare ref names; `parallel_flame_chase:git_pr` is the
fixed Git PR Lite variant, defined in `_parallel_flame_chase_git_pr` and held here. Only
the variant is offered where a person picks a flow; the bare flow still runs by its ref.
"""

from __future__ import annotations

from _parallel_flame_chase.core.api import (
    Agents,
    Envs,
    Params,
    PlanAgents,
    TurnAgents,
    TurnEnvs,
)
from _parallel_flame_chase.core.models import InitialPlan, LaneReport
from _parallel_flame_chase.lanes.runtime import run_initial_plan, run_lane_session
from _parallel_flame_chase.runtime import execute
from _parallel_flame_chase_git_pr.flow import git_pr, git_pr_lane_turn, git_pr_plan
from hmz.flows import FlowContext, FlowParams, flow


@flow(agents=Agents, envs=Envs, params=Params, hidden=True, resumable=True)
async def parallel_flame_chase(
    task: str, *, agents: Agents, envs: Envs, params: Params, ctx: FlowContext
) -> None:
    """Three report-driven lanes of alternating actors, planned once by a coordinator."""
    await execute(agents, envs, task, params, ctx, planner=plan, lane_turn=lane_turn)


@flow(agents=PlanAgents, envs=TurnEnvs, params=FlowParams, hidden=True)
async def plan(
    task: str,
    *,
    agents: PlanAgents,
    envs: TurnEnvs,
    params: FlowParams,
    ctx: FlowContext,
) -> InitialPlan:
    """The coordinator's initial three-lane plan, in up to three fresh sessions."""
    return await run_initial_plan(agents["coordinator"], envs["place"], task)


@flow(agents=TurnAgents, envs=TurnEnvs, params=FlowParams, hidden=True)
async def lane_turn(
    task: str,
    *,
    agents: TurnAgents,
    envs: TurnEnvs,
    params: FlowParams,
    ctx: FlowContext,
) -> LaneReport:
    """One lane actor turn in a fresh session, its report repaired in that session."""
    return await run_lane_session(agents["actor"], envs["place"], task)


__all__ = [
    "Agents",
    "Envs",
    "Params",
    "git_pr",
    "git_pr_lane_turn",
    "git_pr_plan",
    "lane_turn",
    "parallel_flame_chase",
    "plan",
]
