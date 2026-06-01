"""Commitment-based CHESCA peer mesh with ablation switches."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .mesh_agent import MeshCheca, MeshConfig
from .official import configure_official_imports

configure_official_imports()
from checa.agent import Checa  # noqa: E402


@dataclass(frozen=True)
class CommitmentConfig:
    """Settings for commitment-style peer communication.

    All units marked ``soc`` are fractions of battery state of charge. The
    commitment layer only accounts for mesh-induced deviations from official
    CHESCA actions, not the full CHESCA battery trajectory.
    """

    rounds: int = 3
    offer_step: float = 0.04
    history_window: int = 168
    target_quantile: float = 0.65
    minimum_history: int = 12
    reserve_soc: float = 0.55
    peak_weight: float = 1.00
    ramp_weight: float = 0.32
    price_weight: float = 0.10
    carbon_weight: float = 0.08
    recovery_weight: float = 0.42
    wear_weight: float = 0.055
    reserve_weight: float = 0.40
    action_deviation_weight: float = 0.025
    debt_weight: float = 0.18
    budget_weight: float = 0.12
    max_debt_soc: float = 0.18
    soft_budget_soc: float = 0.22
    budget_window_steps: int = 24
    recovery_shadow_threshold: float = 0.05
    enable_ledger: bool = True
    enable_recovery: bool = True
    enable_budget: bool = True


@dataclass(frozen=True)
class CommitmentOffer:
    sender: int
    offer_id: str
    battery_action: float
    battery_demand: float
    predicted_grid: float
    delta_from_official: float
    estimated_soc_after: float
    extra_action_soc: float
    relief_soc: float
    charge_soc: float
    projected_debt_soc: float
    projected_budget_use_soc: float


class CommitmentMeshCheca(MeshCheca):
    """CHESCA plus peer negotiation with explicit discharge commitments."""

    def __init__(
        self,
        env,
        params=None,
        commitment_config: CommitmentConfig | None = None,
        **kwargs,
    ):
        self.commitment_config = commitment_config or CommitmentConfig()
        bridge_config = MeshConfig(
            rounds=self.commitment_config.rounds,
            offer_step=self.commitment_config.offer_step,
            history_window=self.commitment_config.history_window,
            target_quantile=self.commitment_config.target_quantile,
            minimum_history=self.commitment_config.minimum_history,
            reserve_soc=self.commitment_config.reserve_soc,
            peak_weight=self.commitment_config.peak_weight,
            ramp_weight=self.commitment_config.ramp_weight,
            price_weight=self.commitment_config.price_weight,
            carbon_weight=self.commitment_config.carbon_weight,
            recovery_weight=self.commitment_config.recovery_weight,
            wear_weight=self.commitment_config.wear_weight,
            reserve_weight=self.commitment_config.reserve_weight,
            action_deviation_weight=self.commitment_config.action_deviation_weight,
        )
        self.recovery_debt_soc: np.ndarray | None = None
        self._extra_discharge_history: list[list[float]] = []
        self._extra_charge_history: list[list[float]] = []
        super().__init__(env, params=params, mesh_config=bridge_config, **kwargs)
        self._reset_commitments()

    def register_reset(self, observations):
        self._reset_commitments()
        return super().register_reset(observations)

    def refine_actions_with_battery_controller(self, hour, action_proposals):
        """Use CHESCA as outside option, then negotiate commitment offers."""
        official_actions = Checa.refine_actions_with_battery_controller(
            self, hour, action_proposals
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
                "final_shadow_signal": float(final_shadow),
                "logical_message_count": int(logical_messages),
            }
        )
        return negotiated_actions

    def _reset_commitments(self) -> None:
        n_buildings = getattr(self, "n_buildings", 0)
        self.recovery_debt_soc = np.zeros(n_buildings, dtype=float)
        self._extra_discharge_history = [[] for _ in range(n_buildings)]
        self._extra_charge_history = [[] for _ in range(n_buildings)]

    def _commitment_offers_for_peer(
        self, b: int, official_actions, official_net: float, official_battery: float
    ) -> list[CommitmentOffer]:
        base_action = float(official_actions[3 * b + 1])
        step = self.commitment_config.offer_step
        changes = [
            (-step, "relief"),
            (-0.5 * step, "relief_soft"),
            (0.0, "official_chesca"),
            (0.5 * step, "absorb_soft"),
            (step, "absorb"),
        ]
        offers: list[CommitmentOffer] = []
        seen: set[tuple[float, float]] = set()
        for delta, offer_id in changes:
            action = float(
                np.clip(
                    base_action + delta,
                    self.env.action_space[0].low[3 * b + 1],
                    self.env.action_space[0].high[3 * b + 1],
                )
            )
            extra_action = action - base_action
            relief_soc = max(-extra_action, 0.0)
            charge_soc = max(extra_action, 0.0)
            projected_debt = self._projected_debt(b, relief_soc, charge_soc)
            projected_budget = self._recent_budget_use(b) + abs(extra_action)
            battery_demand, _ = self.compute_pred_battery_consumption(b, action)
            predicted_grid = official_net + battery_demand - official_battery
            key = (round(action, 8), round(float(battery_demand), 8))
            if key in seen:
                continue
            seen.add(key)
            offers.append(
                CommitmentOffer(
                    sender=b,
                    offer_id=offer_id,
                    battery_action=action,
                    battery_demand=float(battery_demand),
                    predicted_grid=float(predicted_grid),
                    delta_from_official=float(predicted_grid - official_net),
                    estimated_soc_after=float(
                        np.clip(
                            self.cur_battery_soc[b] + action,
                            self.min_battery_soc[b],
                            self.params["max_soc_normal"],
                        )
                    ),
                    extra_action_soc=float(extra_action),
                    relief_soc=float(relief_soc),
                    charge_soc=float(charge_soc),
                    projected_debt_soc=float(projected_debt),
                    projected_budget_use_soc=float(projected_budget),
                )
            )
        return offers

    @staticmethod
    def _official_offer(offers: list[CommitmentOffer]) -> CommitmentOffer:
        return min(offers, key=lambda offer: abs(offer.delta_from_official))

    def _commitment_peer_score(
        self,
        option: CommitmentOffer,
        official: CommitmentOffer,
        shadow_signal: float,
        scale: float,
        building_index: int,
    ) -> float:
        reserve_penalty = max(
            self.commitment_config.reserve_soc - option.estimated_soc_after, 0.0
        )
        official_reserve_penalty = max(
            self.commitment_config.reserve_soc - official.estimated_soc_after, 0.0
        )
        score = (
            shadow_signal * option.delta_from_official / scale
            + self.commitment_config.wear_weight * abs(option.delta_from_official) / scale
            + self.commitment_config.reserve_weight
            * (reserve_penalty - official_reserve_penalty)
            + self.commitment_config.action_deviation_weight
            * abs(option.battery_action - official.battery_action)
        )

        if self.commitment_config.enable_ledger and option.relief_soc > 0.0:
            debt_ratio = min(
                self.recovery_debt_soc[building_index]
                / max(self.commitment_config.max_debt_soc, 1e-6),
                2.0,
            )
            score += (
                self.commitment_config.debt_weight
                * debt_ratio
                * option.relief_soc
                / max(self.commitment_config.offer_step, 1e-6)
            )

        if self.commitment_config.enable_recovery and option.charge_soc > 0.0:
            repayable = min(option.charge_soc, self.recovery_debt_soc[building_index])
            opportunity = max(
                self.commitment_config.recovery_shadow_threshold - shadow_signal,
                0.0,
            )
            score -= (
                self.commitment_config.recovery_weight
                * repayable
                / max(self.commitment_config.offer_step, 1e-6)
                * min(opportunity, 1.0)
            )

        if self.commitment_config.enable_budget:
            over_budget = max(
                option.projected_budget_use_soc - self.commitment_config.soft_budget_soc,
                0.0,
            )
            score += (
                self.commitment_config.budget_weight
                * over_budget
                / max(self.commitment_config.soft_budget_soc, 1e-6)
                * abs(option.extra_action_soc)
                / max(self.commitment_config.offer_step, 1e-6)
            )
        return score

    def _projected_debt(self, b: int, relief_soc: float, charge_soc: float) -> float:
        if not self.commitment_config.enable_ledger:
            return 0.0
        debt = float(self.recovery_debt_soc[b])
        debt += relief_soc
        if self.commitment_config.enable_recovery:
            debt -= min(charge_soc, debt)
        return max(debt, 0.0)

    def _update_commitment_state(
        self, b: int, relief_soc: float, charge_soc: float
    ) -> tuple[float, float]:
        created = 0.0
        repaid = 0.0
        if self.commitment_config.enable_ledger:
            self.recovery_debt_soc[b] += relief_soc
            created = relief_soc
            if self.commitment_config.enable_recovery:
                repaid = min(charge_soc, self.recovery_debt_soc[b])
                self.recovery_debt_soc[b] -= repaid
        self._append_budget_history(b, relief_soc, charge_soc)
        return created, repaid

    def _append_budget_history(self, b: int, relief_soc: float, charge_soc: float) -> None:
        self._extra_discharge_history[b].append(float(relief_soc))
        self._extra_charge_history[b].append(float(charge_soc))
        window = max(int(self.commitment_config.budget_window_steps), 1)
        del self._extra_discharge_history[b][:-window]
        del self._extra_charge_history[b][:-window]

    def _recent_budget_use(self, b: int) -> float:
        if b >= len(self._extra_discharge_history):
            return 0.0
        return float(sum(self._extra_discharge_history[b]) + sum(self._extra_charge_history[b]))

    def protocol_metadata(self) -> dict:
        return {
            "protocol": "commitment_mesh",
            "commitment_config": asdict(self.commitment_config),
            "ablation_flags": {
                "enable_ledger": self.commitment_config.enable_ledger,
                "enable_recovery": self.commitment_config.enable_recovery,
                "enable_budget": self.commitment_config.enable_budget,
            },
        }
