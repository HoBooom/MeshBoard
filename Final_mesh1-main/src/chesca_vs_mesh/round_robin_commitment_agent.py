"""Round-robin coordinator version of the commitment mesh."""

from __future__ import annotations

import numpy as np

from .commitment_mesh_agent import CommitmentConfig, CommitmentMeshCheca
from .coordinator_tools import CHESCAPlannerTool, RoundRobinCoordinator


class RoundRobinCommitmentMeshCheca(CommitmentMeshCheca):
    """Commitment mesh where the baseline planner is owned by a rotating peer.

    This class preserves the exact commitment action logic. The only semantic
    change is protocol-level: a round-robin coordinator is selected each step
    and is logged as the agent that used the CHESCA planner tool to create the
    baseline proposal.
    """

    def __init__(
        self,
        env,
        params=None,
        commitment_config: CommitmentConfig | None = None,
        unavailable_coordinators: tuple[int, ...] | list[int] | None = None,
        **kwargs,
    ):
        self.coordinator_selector = RoundRobinCoordinator()
        self.planner_tool = CHESCAPlannerTool()
        self.unavailable_coordinators = tuple(unavailable_coordinators or ())
        self.coordinator_log: list[dict] = []
        super().__init__(
            env,
            params=params,
            commitment_config=commitment_config,
            **kwargs,
        )

    def register_reset(self, observations):
        self.coordinator_log.clear()
        return super().register_reset(observations)

    def refine_actions_with_battery_controller(self, hour, action_proposals):
        decision = self.coordinator_selector.select(
            step=self.seen_steps,
            hour=hour,
            n_agents=self.n_buildings,
            unavailable=self.unavailable_coordinators,
        )
        official_actions = self.planner_tool.refine_actions(self, hour, action_proposals)
        self.coordinator_log.append(
            {
                **decision.to_dict(),
                "planner_tool": self.planner_tool.name,
                "role": "baseline_proposal_owner",
            }
        )

        normal_peers = [
            b for b in range(self.n_buildings) if not self.outage_details[b]["outage_flag"]
        ]
        if not normal_peers:
            return official_actions

        official_net, official_battery = self._official_predicted_net(official_actions)
        offers = {
            b: self._commitment_offers_for_peer(
                b, official_actions, official_net[b], official_battery[b]
            )
            for b in normal_peers
        }
        selected = {b: self._official_offer(offers[b]) for b in normal_peers}
        target, last_district, scale = self._district_reference(official_net)
        fixed_net = float(
            sum(official_net[b] for b in range(self.n_buildings) if b not in normal_peers)
        )
        final_shadow = 0.0

        for round_id in range(self.commitment_config.rounds):
            proposal = fixed_net + float(sum(selected[b].predicted_grid for b in normal_peers))
            final_shadow = self._shadow_signal(proposal, target, last_district, scale)
            recipient_count = max(len(normal_peers) - 1, 0)

            for b in normal_peers:
                options = offers[b]
                baseline = self._official_offer(options)
                self.message_log.append(
                    {
                        "step": int(self.seen_steps),
                        "round_id": int(round_id),
                        "coordinator_id": int(decision.coordinator_id),
                        "coordinator_policy": decision.policy,
                        "planner_tool": self.planner_tool.name,
                        "sender": int(b),
                        "official_grid": float(official_net[b]),
                        "proposed_grid": float(selected[b].predicted_grid),
                        "lower_grid": float(min(o.predicted_grid for o in options)),
                        "upper_grid": float(max(o.predicted_grid for o in options)),
                        "soc": float(self.cur_battery_soc[b]),
                        "debt_soc": float(self.recovery_debt_soc[b]),
                        "budget_use_soc": float(self._recent_budget_use(b)),
                        "official_projected_debt_soc": float(baseline.projected_debt_soc),
                        "district_proposal": float(proposal),
                        "district_target": float(target),
                        "shadow_signal": float(final_shadow),
                        "recipient_count": int(recipient_count),
                    }
                )

            selected = {
                b: min(
                    offers[b],
                    key=lambda option: self._commitment_peer_score(
                        option, self._official_offer(offers[b]), final_shadow, scale, b
                    ),
                )
                for b in normal_peers
            }

        negotiated_actions = official_actions.copy()
        changed_peers = 0
        relief_selected_peers = 0
        recovery_selected_peers = 0
        debt_created = 0.0
        debt_repaid = 0.0
        extra_discharge_total = 0.0
        extra_charge_total = 0.0

        for b in range(self.n_buildings):
            if b not in normal_peers:
                self._append_budget_history(b, 0.0, 0.0)

        for b in normal_peers:
            chosen = selected[b]
            baseline = self._official_offer(offers[b])
            negotiated_actions[3 * b + 1] = chosen.battery_action
            self.predicted_battery_demand[b] = chosen.battery_demand
            if not np.isclose(chosen.battery_action, baseline.battery_action):
                changed_peers += 1

            extra_delta = chosen.battery_action - baseline.battery_action
            relief_soc = max(-extra_delta, 0.0)
            charge_soc = max(extra_delta, 0.0)
            if relief_soc > 1e-9:
                relief_selected_peers += 1
            if charge_soc > 1e-9:
                recovery_selected_peers += 1

            created, repaid = self._update_commitment_state(b, relief_soc, charge_soc)
            debt_created += created
            debt_repaid += repaid
            extra_discharge_total += relief_soc
            extra_charge_total += charge_soc

        official_district = float(np.sum(official_net))
        negotiated_district = fixed_net + float(
            sum(selected[b].predicted_grid for b in normal_peers)
        )
        logical_messages = (
            self.commitment_config.rounds
            * len(normal_peers)
            * max(len(normal_peers) - 1, 0)
        )
        self.negotiation_log.append(
            {
                "step": int(self.seen_steps),
                "hour": int(hour),
                "coordinator_id": int(decision.coordinator_id),
                "coordinator_policy": decision.policy,
                "planner_tool": self.planner_tool.name,
                "active_peers": int(len(normal_peers)),
                "changed_peers": int(changed_peers),
                "relief_selected_peers": int(relief_selected_peers),
                "recovery_selected_peers": int(recovery_selected_peers),
                "debt_created_soc": float(debt_created),
                "debt_repaid_soc": float(debt_repaid),
                "extra_discharge_soc": float(extra_discharge_total),
                "extra_charge_soc": float(extra_charge_total),
                "total_debt_soc": float(np.sum(self.recovery_debt_soc)),
                "max_debt_soc": float(np.max(self.recovery_debt_soc)),
                "mean_budget_use_soc": float(
                    np.mean([self._recent_budget_use(b) for b in range(self.n_buildings)])
                ),
                "official_predicted_grid": official_district,
                "negotiated_predicted_grid": negotiated_district,
                "predicted_grid_delta": negotiated_district - official_district,
                "district_target": float(target),
                "final_shadow_signal": final_shadow,
                "logical_message_count": int(logical_messages),
            }
        )
        return negotiated_actions

    def protocol_metadata(self) -> dict:
        metadata = super().protocol_metadata()
        metadata.update(
            {
                "coordinator_policy": self.coordinator_selector.policy,
                "planner_tool": self.planner_tool.name,
                "unavailable_coordinators": list(self.unavailable_coordinators),
                "performance_expectation": (
                    "Actions are expected to match chesca_commitment_full_mesh "
                    "when no coordinators are unavailable."
                ),
            }
        )
        return metadata
