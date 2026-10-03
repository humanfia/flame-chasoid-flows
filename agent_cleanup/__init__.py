"""Coding turns in fresh sessions, with a cleaner agent distilling the workspace between them.

Two flows, named as `agent_cleanup:<flow>`: `ralph_loop`, one agent's Ralph loop, and
`flame_chase`, two agents alternating. Both drive the same loop in `_agent_cleanup`, and keep
their runs under the names the two flows had in flowverse, so storage stays where it was.
"""

from __future__ import annotations

from _agent_cleanup import Config, Worker, Workspace, drive
from hmz.flows import AgentCollection, EnvCollection, FlowContext, Outworlder, flow


class RalphLoopAgents(AgentCollection):
    agent: Worker
    cleaner: Worker
    human: Outworlder


class FlameChaseAgents(AgentCollection):
    first_chaser: Worker
    second_chaser: Worker
    cleaner: Worker
    human: Outworlder


class Envs(EnvCollection):
    workspace: Workspace


@flow(
    agents=RalphLoopAgents,
    envs=Envs,
    params=Config,
    description="A fresh-session Ralph loop whose periodic cleanup is performed by an agent.",
    resumable=True,
)
async def ralph_loop(
    task: str, *, agents: RalphLoopAgents, envs: Envs, params: Config, ctx: FlowContext
) -> None:
    await drive(
        "ralph_loop_agent_cleanup",
        (agents["agent"],),
        agents["cleaner"],
        agents["human"],
        task,
        params,
        ctx,
        envs["workspace"],
    )


@flow(
    agents=FlameChaseAgents,
    envs=Envs,
    params=Config,
    description=(
        "Two agents flame-chase a repository task while a cleaner distills the workspace "
        "between them."
    ),
    resumable=True,
)
async def flame_chase(
    task: str, *, agents: FlameChaseAgents, envs: Envs, params: Config, ctx: FlowContext
) -> None:
    await drive(
        "flame_chase_agent_cleanup",
        (agents["first_chaser"], agents["second_chaser"]),
        agents["cleaner"],
        agents["human"],
        task,
        params,
        ctx,
        envs["workspace"],
    )


__all__ = ["Envs", "FlameChaseAgents", "RalphLoopAgents", "flame_chase", "ralph_loop"]
