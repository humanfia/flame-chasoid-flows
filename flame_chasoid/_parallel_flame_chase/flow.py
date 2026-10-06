"""`flame_chasoid:parallel`: the report-driven Parallel Flame Chase without mission
audits, with its two hidden turns.

Only its Git PR variant, `flame_chasoid:parallel_git_pr`, is offered where a person picks a
flow; this one still runs by its ref. Imported into the flow's entry point, which is what
makes these flows of the `flame_chasoid` module rather than of this private package.
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
from hmz.flows import FlowContext, FlowParams, flow


@flow(
    agents=Agents,
    envs=Envs,
    params=Params,
    name="parallel",
    hidden=True,
    resumable=True,
)
async def parallel(
    task: str, *, agents: Agents, envs: Envs, params: Params, ctx: FlowContext
) -> None:
    """Three report-driven lanes of alternating actors, planned once by a coordinator."""
    await execute(
        agents,
        envs,
        task,
        params,
        ctx,
        planner=parallel_plan,
        lane_turn=parallel_lane_turn,
    )


@flow(
    agents=PlanAgents,
    envs=TurnEnvs,
    params=FlowParams,
    name="parallel_plan",
    hidden=True,
)
async def parallel_plan(
    task: str,
    *,
    agents: PlanAgents,
    envs: TurnEnvs,
    params: FlowParams,
    ctx: FlowContext,
) -> InitialPlan:
    """The coordinator's initial three-lane plan, in up to three fresh sessions."""
    return await run_initial_plan(agents["coordinator"], envs["place"], task)


@flow(
    agents=TurnAgents,
    envs=TurnEnvs,
    params=FlowParams,
    name="parallel_lane_turn",
    hidden=True,
)
async def parallel_lane_turn(
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
    "parallel",
    "parallel_lane_turn",
    "parallel_plan",
]
