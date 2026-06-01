"""CHESCA mesh negotiation with explicit time-varying reserve contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .mesh_agent import MeshCheca, MeshConfig
from .official import configure_official_imports

configure_official_imports()
from checa.agent import Checa  # noqa: E402


@dataclass(frozen=True)
class ReserveContractConfig:
    """Configuration for communication that preserves CHESCA's SOC policy.

    The proposal space is governed by the official CHESCA minimum-SOC curve,
    rather than a reserve penalty fitted after seeing evaluation results.
    """

    rounds: int = 3
    offer_step: float = 0.04
    history_window: int = 168
    target_quantile: float = 0.65
    minimum_history: int = 12
    peak_weight: float = 1.00
    ramp_weight: float = 0.32
    price_weight: float = 0.10
    carbon_weight: float = 0.08
    wear_weight: float = 0.055
    action_deviation_weight: float = 0.025


@dataclass(frozen=True)
class ReserveOffer:
    sender: int
    offer_id: str
    battery_action: float
    battery_demand: float
    predicted_grid: float
    delta_from_official: float
    estimated_soc_after: float
    protected_reserve_soc: float
    reserve_margin_after: float
    discharge_flex_soc: float


class ReserveContractMeshCheca(MeshCheca):
    """Peer mesh whose messages cannot consume official CHESCA reserve.

    CHESCA remains the outside option. At every normal-operation step, each
    peer broadcasts flexibility around its official battery action. Additional
    discharge is offered only out of SOC above CHESCA's next-hour minimum SOC.
    Thus the distributed layer coordinates usable flexibility without undoing
    the baseline controller's outage reserve decision.
    """

    def __init__(
        self,
        env,
        params=None,
        contract_config: ReserveContractConfig | None = None,
        **kwargs,
    ):
        self.contract_config = contract_config or ReserveContractConfig()
        bridge_config = MeshConfig(
            rounds=self.contract_config.rounds,
            offer_step=self.contract_config.offer_step,
            history_window=self.contract_config.history_window,
            target_quantile=self.contract_config.target_quantile,
            minimum_history=self.contract_config.minimum_history,
            peak_weight=self.contract_config.peak_weight,
            ramp_weight=self.contract_config.ramp_weight,
            price_weight=self.contract_config.price_weight,
            carbon_weight=self.contract_config.carbon_weight,
            wear_weight=self.contract_config.wear_weight,
            action_deviation_weight=self.contract_config.action_deviation_weight,
        )
        super().__init__(env, params=params, mesh_config=bridge_config, **kwargs)

    def refine_actions_with_battery_controller(self, hour, action_proposals):
        """Negotiate only flexibility declared feasible under CHESCA reserve."""
        official_actions = Checa.refine_actions_with_battery_controller(
            self, hour, action_proposals
        )
        normal_peers = [
            b for b in range(self.n_buildings) if not self.outage_details[b]["outage_flag"]
        ]
        if not normal_peers:
            return official_actions

        official_net, official_battery = self._official_predicted_net(official_actions)
        protected_reserve = self._protected_reserve_soc(hour)
        offers = {
            b: self._contract_offers_for_peer(
                b,
                official_actions,
                official_net[b],
                official_battery[b],
                protected_reserve,
            )
            for b in normal_peers
        }
        selected = {b: self._official_offer(offers[b]) for b in normal_peers}
        target, last_district, scale = self._district_reference(official_net)
        fixed_net = float(
            sum(official_net[b] for b in range(self.n_buildings) if b not in normal_peers)
        )
        final_shadow = 0.0

        for round_id in range(self.contract_config.rounds):
            proposal = fixed_net + float(sum(selected[b].predicted_grid for b in normal_peers))
            final_shadow = self._contract_shadow_signal(proposal, target, last_district, scale)
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
                        "protected_reserve_soc": float(protected_reserve),
                        "official_reserve_margin": float(baseline.reserve_margin_after),
                        "offered_discharge_flex_soc": float(baseline.discharge_flex_soc),
                        "district_proposal": float(proposal),
                        "district_target": float(target),
                        "shadow_signal": float(final_shadow),
                        "recipient_count": int(recipient_count),
                    }
                )

            selected = {
                b: min(
                    offers[b],
                    key=lambda option: self._contract_peer_score(
                        option, self._official_offer(offers[b]), final_shadow, scale
                    ),
                )
                for b in normal_peers
            }

        negotiated_actions = official_actions.copy()
        changed_peers = 0
        relief_selected_peers = 0
        for b in normal_peers:
            chosen = selected[b]
            baseline = self._official_offer(offers[b])
            negotiated_actions[3 * b + 1] = chosen.battery_action
            self.predicted_battery_demand[b] = chosen.battery_demand
            if not np.isclose(chosen.battery_action, baseline.battery_action):
                changed_peers += 1
            if chosen.battery_action < baseline.battery_action - 1e-9:
                relief_selected_peers += 1

        official_district = float(np.sum(official_net))
        negotiated_district = fixed_net + float(
            sum(selected[b].predicted_grid for b in normal_peers)
        )
        logical_messages = (
            self.contract_config.rounds * len(normal_peers) * max(len(normal_peers) - 1, 0)
        )
        reserve_limited_peers = sum(
            int(self._official_offer(offers[b]).discharge_flex_soc <= 1e-9)
            for b in normal_peers
        )
        selected_margins = [selected[b].reserve_margin_after for b in normal_peers]
        official_margins = [
            self._official_offer(offers[b]).reserve_margin_after for b in normal_peers
        ]
        self.negotiation_log.append(
            {
                "step": int(self.seen_steps),
                "hour": int(hour),
                "active_peers": int(len(normal_peers)),
                "changed_peers": int(changed_peers),
                "relief_selected_peers": int(relief_selected_peers),
                "reserve_limited_peers": int(reserve_limited_peers),
                "protected_reserve_soc": float(protected_reserve),
                "official_reserve_margin_min": float(min(official_margins)),
                "selected_reserve_margin_min": float(min(selected_margins)),
                "selected_reserve_margin_mean": float(np.mean(selected_margins)),
                "official_predicted_grid": official_district,
                "negotiated_predicted_grid": negotiated_district,
                "predicted_grid_delta": negotiated_district - official_district,
                "district_target": float(target),
                "final_shadow_signal": float(final_shadow),
                "logical_message_count": int(logical_messages),
            }
        )
        return negotiated_actions

    def _protected_reserve_soc(self, hour: int) -> float:
        """Return the same next-step minimum SOC used by CHESCA tree search."""
        protected_hour = str((int(hour) + 1) % 24)
        return float(self.params["min_soc_per_hour"][protected_hour])

    def _contract_offers_for_peer(
        self,
        b: int,
        official_actions,
        official_net: float,
        official_battery: float,
        protected_reserve: float,
    ) -> list[ReserveOffer]:
        base_action = float(official_actions[3 * b + 1])
        low = float(self.env.action_space[0].low[3 * b + 1])
        high = float(self.env.action_space[0].high[3 * b + 1])
        official_soc = float(self.cur_battery_soc[b] + base_action)
        discharge_flex = max(official_soc - protected_reserve, 0.0)
        charge_flex = max(float(self.params["max_soc_normal"]) - official_soc, 0.0)
        step = self.contract_config.offer_step
        changes = [
            (-min(step, discharge_flex), "reserve_relief"),
            (-min(0.5 * step, discharge_flex), "reserve_relief_soft"),
            (0.0, "official_chesca"),
            (min(0.5 * step, charge_flex), "absorb_soft"),
            (min(step, charge_flex), "absorb"),
        ]
        offers: list[ReserveOffer] = []
        seen: set[tuple[float, float]] = set()
        for delta, offer_id in changes:
            action = float(np.clip(base_action + delta, low, high))
            estimated_soc_after = float(self.cur_battery_soc[b] + action)
            if action < base_action - 1e-9 and estimated_soc_after < protected_reserve - 1e-9:
                continue
            battery_demand, _ = self.compute_pred_battery_consumption(b, action)
            predicted_grid = official_net + battery_demand - official_battery
            key = (round(action, 8), round(float(battery_demand), 8))
            if key in seen:
                continue
            seen.add(key)
            offers.append(
                ReserveOffer(
                    sender=b,
                    offer_id=offer_id,
                    battery_action=action,
                    battery_demand=float(battery_demand),
                    predicted_grid=float(predicted_grid),
                    delta_from_official=float(predicted_grid - official_net),
                    estimated_soc_after=estimated_soc_after,
                    protected_reserve_soc=float(protected_reserve),
                    reserve_margin_after=float(estimated_soc_after - protected_reserve),
                    discharge_flex_soc=float(discharge_flex),
                )
            )
        return offers

    @staticmethod
    def _official_offer(offers: list[ReserveOffer]) -> ReserveOffer:
        return min(offers, key=lambda offer: abs(offer.delta_from_official))

    def _contract_shadow_signal(
        self, district_proposal: float, target: float, last_district: float, scale: float
    ) -> float:
        excess = (district_proposal - target) / scale
        ramp = (district_proposal - last_district) / scale
        price_z = self._standardized_signal(self.price_history)
        carbon_z = self._standardized_signal(self.carbon_history)
        return (
            self.contract_config.peak_weight * max(excess, 0.0)
            + self.contract_config.ramp_weight * ramp
            + self.contract_config.price_weight * price_z
            + self.contract_config.carbon_weight * carbon_z
        )

    def _contract_peer_score(
        self,
        option: ReserveOffer,
        official: ReserveOffer,
        shadow_signal: float,
        scale: float,
    ) -> float:
        return (
            shadow_signal * option.delta_from_official / scale
            + self.contract_config.wear_weight * abs(option.delta_from_official) / scale
            + self.contract_config.action_deviation_weight
            * abs(option.battery_action - official.battery_action)
        )

    def protocol_metadata(self) -> dict:
        return {
            "protocol": "chesca_time_varying_reserve_contract",
            "contract_config": asdict(self.contract_config),
            "protected_reserve_source": "params['min_soc_per_hour'][(hour + 1) % 24]",
            "constraint": (
                "A peer may offer additional discharge only from predicted SOC "
                "strictly above the official CHESCA next-hour reserve."
            ),
        }
