from __future__ import annotations

import math

from hmz.flows import Agent, AgentCollection, EnvCollection, FlowParams, LocalEnv
from pydantic import ConfigDict, Field, model_validator


class Agents(AgentCollection):
    first_chaser: Agent
    second_chaser: Agent


class Envs(EnvCollection):
    workspace: LocalEnv


class TurnAgents(AgentCollection):
    actor: Agent


#: The wall clock when neither the params nor the run's budget set one.
DEFAULT_TIME_LIMIT_SECONDS = 21600.0


class Params(FlowParams):
    """Every field has a default, so a harness that passes no `-p` can run it.

    `gate_config` picks the admission backend: the native MLE evaluator when it
    is given, otherwise the FlowBench evaluator at `evaluator_url`, driven
    through the workspace's own `submit.sh`.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    gate_config: str | None = Field(
        default=None,
        description="Absolute path to the trusted native evaluator connection JSON; "
        "unset for a FlowBench task.",
    )
    run_dir: str | None = Field(
        default=None,
        description="New absolute controller output directory, outside the workspace; "
        "a fresh one under ~/.fixed_interrupt_flame_chase/ when unset.",
    )
    evaluator_url: str = Field(
        default="http://evaluator",
        description="The FlowBench evaluator, used when no gate_config is given.",
    )
    max_valid_submissions_per_session: int = Field(default=5, ge=1, strict=True)
    active_time_limit_seconds: float | None = Field(
        default=None,
        gt=0,
        description="The whole run's wall clock, review included; the run budget's "
        "duration when unset, else six hours.",
    )
    review_reserve_seconds: float = Field(default=900, gt=0)
    review_turn_seconds: float = Field(default=600, gt=0)
    finalize_reserve_seconds: float = Field(default=60, gt=0)
    cleanup_reserve_seconds: float = Field(default=35, gt=0)
    build_timeout_seconds: float = Field(
        default=900, gt=0, description="How long one FlowBench submit.sh may run."
    )
    poll_seconds: float = Field(default=0.25, gt=0, le=5)
    rest_seconds: float = Field(default=1, ge=0, le=60)

    @model_validator(mode="after")
    def review_fits(self) -> Params:
        if self.active_time_limit_seconds is not None:
            self.check_reserves(self.active_time_limit_seconds)
        else:
            self.check_reserves(math.inf)
        return self

    def check_reserves(self, total: float) -> None:
        """Whether review fits the reserve and the reserve fits `total` seconds."""
        owed = (
            self.review_turn_seconds
            + self.finalize_reserve_seconds
            + self.cleanup_reserve_seconds
        )
        if owed >= self.review_reserve_seconds:
            raise ValueError(
                "review reserve must exceed reviewer, cleanup and finalization time"
            )
        if self.review_reserve_seconds >= total:
            raise ValueError("review reserve leaves no exploration time")
