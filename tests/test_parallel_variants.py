from __future__ import annotations

from pathlib import Path
from typing import Any

from hmz.flows import Outworlder, PermissionKind, load
from hmz.runtime.flowing import finding, loading

FLOW = Path(__file__).parents[1] / "parallel_flame_chase"
SKILL = "parallel-flame-chase-git-pr"


def test_the_module_offers_the_flow_and_its_git_pr_variant() -> None:
    offered = [name for name, _ in finding._named(FLOW / "__init__.py", FLOW.name)]

    assert offered == ["parallel_flame_chase", "parallel_flame_chase:git_pr"]


def test_git_pr_turns_are_hidden_and_do_not_clash_with_the_flows() -> None:
    for name in ("git-pr-plan", "git-pr-lane-turn"):
        sub = load(f"{FLOW}:{name}").describe()
        assert sub.hidden
        assert not sub.resumable
        assert all(role.skills == (SKILL,) for role in sub.agents)
        assert [role.name for role in sub.envs] == ["workdir"]


def test_only_canonical_git_pr_lite_is_offered() -> None:
    names = set(loading.module_of(FLOW / "__init__.py", None).flows())
    flow: Any = load(f"{FLOW}:git_pr")
    declared = flow.describe()

    assert declared.name == "git_pr"
    assert declared.ref == "parallel_flame_chase:git_pr"
    assert names == {
        "parallel_flame_chase",
        "plan",
        "lane_turn",
        "git_pr",
        "git-pr-plan",
        "git-pr-lane-turn",
    }
    assert declared.resumable
    assert not declared.hidden
    assert [role.name for role in declared.agents] == [
        "orchestrator",
        "lane_1_actor_a",
        "lane_1_actor_b",
        "lane_2_actor_a",
        "lane_2_actor_b",
        "lane_3_actor_a",
        "lane_3_actor_b",
        "human",
    ]
    human = declared.agent("human")
    assert human.auto
    assert human.declared is Outworlder
    for role in declared.agents:
        if role.name == "human":
            continue
        assert not role.auto
        assert role.required
        assert role.harness is None
        assert role.capabilities == frozenset()
        assert role.skills == (SKILL,)
        expected = (
            PermissionKind.READ if role.name == "orchestrator" else PermissionKind.ALL
        )
        assert role.permission.user == expected
    [workspace] = declared.envs
    assert workspace.name == "workspace"
    assert workspace.auto
    assert (FLOW / "skills" / SKILL / "SKILL.md").is_file()

    params = declared.params
    assert set(params.model_fields) == {
        "rest_seconds",
        "resume_mode",
        "confirm_large_workspace_copies",
        "workspace_file_warning_threshold",
        "workspace_copy_warning_threshold_bytes",
        "git_pr_enabled",
        "global_knowledge_enabled",
        "experiment_memory_enabled",
        "token_efficient_enabled",
        "main_update_monitor_enabled",
    }
    assert params().model_dump() == {
        "rest_seconds": 1.0,
        "resume_mode": "auto",
        "confirm_large_workspace_copies": False,
        "workspace_file_warning_threshold": 5_000,
        "workspace_copy_warning_threshold_bytes": 1024**3,
        "git_pr_enabled": True,
        "global_knowledge_enabled": False,
        "experiment_memory_enabled": False,
        "token_efficient_enabled": False,
        "main_update_monitor_enabled": False,
    }

    removed = {
        "parallel_flame_chase_git_pr_adaptive_eval",
        "parallel_flame_chase_git_pr_main_monitor",
        "parallel_flame_chase_git_pr_token_efficient",
        "parallel_flame_chase_git_pr_token_efficient_main_monitor",
        "parallel_flame_chase_mission",
        "parallel_flame_chase_mission_control",
        "parallel_flame_chase_mission_lite",
        "parallel_flame_chase_report_share",
        "parallel_ralph_git_pr_2way",
        "parallel_ralph_git_pr_4way",
    }
    assert removed.isdisjoint(names)
