"""Two fresh native sessions alternate at accepted-experiment boundaries."""

from __future__ import annotations

from hmz.flows import FlowContext, FlowParams, flow

from ._fixed_interrupt_flame_chase.api import Agents, Envs, Params, TurnAgents
from ._fixed_interrupt_flame_chase.runtime import execute


@flow(agents=Agents, envs=Envs, params=Params)
async def fixed_interrupt_flame_chase(
    task: str, *, agents: Agents, envs: Envs, params: Params, ctx: FlowContext
) -> dict:
    """Hidden fixed-k interruption and one blind final-selection turn, within one wall budget.

    Experiments are admitted by the native MLE evaluator when `gate_config` is given,
    and otherwise by a FlowBench cell's evaluator through the workspace's `submit.sh`.
    """
    return await execute(task, agents, envs, params, ctx=ctx, turn=turn)


@flow(agents=TurnAgents, envs=Envs, params=FlowParams, hidden=True)
async def turn(
    task: str, *, agents: TurnAgents, envs: Envs, params: FlowParams, ctx: FlowContext
) -> None:
    """Exactly one ordinary session; the subflow scope closes it before the next turn."""
    actor = agents["actor"]
    session = await actor.spawn(env=envs["workspace"])
    await actor.run(task, session=session)


__all__ = ["Agents", "Envs", "Params", "fixed_interrupt_flame_chase", "turn"]
