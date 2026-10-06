"""`flame_chasoid:fixed_interrupt`: two fresh native sessions alternate at
accepted-experiment boundaries, with its hidden turn.

Imported into the flow's entry point, which is what makes these flows of the
`flame_chasoid` module rather than of this private package.
"""

from __future__ import annotations

from hmz.flows import FlowContext, FlowParams, flow

from .api import Agents, Envs, Params, TurnAgents
from .runtime import execute


@flow(agents=Agents, envs=Envs, params=Params, name="fixed_interrupt")
async def fixed_interrupt(
    task: str, *, agents: Agents, envs: Envs, params: Params, ctx: FlowContext
) -> dict:
    """Hidden fixed-k interruption and one blind final-selection turn, within one wall budget.

    Experiments are admitted by the native MLE evaluator when `gate_config` is given,
    and otherwise by a FlowBench cell's evaluator through the workspace's `submit.sh`.
    """
    return await execute(task, agents, envs, params, ctx=ctx, turn=fixed_interrupt_turn)


@flow(
    agents=TurnAgents,
    envs=Envs,
    params=FlowParams,
    name="fixed_interrupt_turn",
    hidden=True,
)
async def fixed_interrupt_turn(
    task: str, *, agents: TurnAgents, envs: Envs, params: FlowParams, ctx: FlowContext
) -> None:
    """Exactly one ordinary session; the subflow scope closes it before the next turn."""
    actor = agents["actor"]
    session = await actor.spawn()
    await actor.run(task, session=session, env=envs["workspace"])


__all__ = ["Agents", "Envs", "Params", "fixed_interrupt", "fixed_interrupt_turn"]
