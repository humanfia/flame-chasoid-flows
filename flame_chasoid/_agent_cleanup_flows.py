"""`flame_chasoid:agent_cleanup_*`: coding turns in fresh sessions, with a cleaner agent
distilling the workspace between them.

Two flows: `agent_cleanup_ralph_loop`, one agent's Ralph loop, and
`agent_cleanup_flame_chase`, two agents alternating. Both drive the same loop in
`_agent_cleanup`, and keep their runs under the names the two flows first had in flowverse,
so a workspace's archived history stays where it was.

Imported into the flow's entry point, which is what makes these flows of the
`flame_chasoid` module rather than of this private one.
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
    name="agent_cleanup_ralph_loop",
    resumable=True,
)
async def agent_cleanup_ralph_loop(
    task: str, *, agents: RalphLoopAgents, envs: Envs, params: Config, ctx: FlowContext
) -> None:
    await drive(
        "flame_chasoid:agent_cleanup_ralph_loop",
        (agents["agent"],),
        agents["cleaner"],
        agents["human"],
        task,
        params,
        ctx,
        envs["workspace"],
        kept_under="ralph_loop_agent_cleanup",
    )


@flow(
    agents=FlameChaseAgents,
    envs=Envs,
    params=Config,
    description=(
        "Two agents flame-chase a repository task while a cleaner distills the workspace "
        "between them."
    ),
    name="agent_cleanup_flame_chase",
    resumable=True,
)
async def agent_cleanup_flame_chase(
    task: str, *, agents: FlameChaseAgents, envs: Envs, params: Config, ctx: FlowContext
) -> None:
    await drive(
        "flame_chasoid:agent_cleanup_flame_chase",
        (agents["first_chaser"], agents["second_chaser"]),
        agents["cleaner"],
        agents["human"],
        task,
        params,
        ctx,
        envs["workspace"],
        kept_under="flame_chase_agent_cleanup",
    )


__all__ = [
    "Envs",
    "FlameChaseAgents",
    "RalphLoopAgents",
    "agent_cleanup_flame_chase",
    "agent_cleanup_ralph_loop",
]
