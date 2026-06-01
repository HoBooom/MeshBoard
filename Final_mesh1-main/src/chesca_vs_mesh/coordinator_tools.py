"""Coordinator utilities for agent-owned CHESCA planner tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .official import configure_official_imports

configure_official_imports()
from checa.agent import Checa  # noqa: E402


@dataclass(frozen=True)
class CoordinatorDecision:
    step: int
    hour: int
    coordinator_id: int
    policy: str
    available_coordinators: tuple[int, ...]

    def to_dict(self) -> dict:
        return asdict(self)


class RoundRobinCoordinator:
    """Selects the temporary team leader deterministically by step."""

    policy = "round_robin"

    def select(
        self,
        step: int,
        hour: int,
        n_agents: int,
        unavailable: Iterable[int] | None = None,
    ) -> CoordinatorDecision:
        blocked = set(unavailable or [])
        available = tuple(i for i in range(n_agents) if i not in blocked)
        if not available:
            raise RuntimeError("No available coordinator agents.")
        coordinator_id = available[int(step) % len(available)]
        return CoordinatorDecision(
            step=int(step),
            hour=int(hour),
            coordinator_id=int(coordinator_id),
            policy=self.policy,
            available_coordinators=available,
        )


class CHESCAPlannerTool:
    """Agent-owned wrapper around the official CHESCA battery refinement.

    The selected coordinator owns this tool for protocol/logging purposes. The
    underlying calculation intentionally calls the same CHESCA method, so the
    baseline proposal is identical to the non-rotating commitment mesh.
    """

    name = "chesca_planner_tool"

    def refine_actions(self, owner_agent, hour, action_proposals):
        return Checa.refine_actions_with_battery_controller(
            owner_agent, hour, action_proposals
        )
