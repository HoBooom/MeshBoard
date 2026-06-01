"""A CHESCA-compatible agent that negotiates battery flexibility peer-to-peer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from .official import configure_official_imports
from .protocol import FlexBroadcast, FlexOffer, NegotiationOutcome

configure_official_imports()
from checa.agent import Checa  # noqa: E402


@dataclass(frozen=True)
class MeshConfig:
    """Settings for the distributed coordination layer.

    The official CHESCA action is always available as each peer's outside
    option. Peers change only electrical storage actions; the official
    forecasting, outage, HVAC and DHW logic remain untouched.
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
    recovery_weight: float = 0.45
    wear_weight: float = 0.055
    reserve_weight: float = 0.40
    action_deviation_weight: float = 0.025


class MeshCheca(Checa):
    """Official CHESCA plus synchronous peer flexibility negotiation."""

    def __init__(self, env, params=None, mesh_config: MeshConfig | None = None, **kwargs):
        self.mesh_config = mesh_config or MeshConfig()
        self.message_log: list[dict] = []
        self.negotiation_log: list[dict] = []
        self.price_history: list[float] = []
        self.carbon_history: list[float] = []
        self._latest_observations: np.ndarray | None = None
        super().__init__(env, params=params, **kwargs)

    def register_reset(self, observations):
        self.message_log.clear()
        self.negotiation_log.clear()
        self.price_history.clear()
        self.carbon_history.clear()
        self.reset()
        return self.predict(observations)

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        self._latest_observations = np.asarray(observations[0], dtype=float)
        self.price_history.append(self._signal("electricity_pricing"))
        self.carbon_history.append(self._signal("carbon_intensity"))
        return super().predict(observations, deterministic=deterministic)

    def refine_actions_with_battery_controller(self, hour, action_proposals):
        """Use CHESCA actions as outside options, then negotiate flex offers."""
        official_actions = super().refine_actions_with_battery_controller(hour, action_proposals)
        normal_peers = [
            b for b in range(self.n_buildings) if not self.outage_details[b]["outage_flag"]
        ]
        if not normal_peers:
            return official_actions

        official_net, official_battery = self._official_predicted_net(official_actions)
        offers = {
            b: self._offers_for_peer(b, official_actions, official_net[b], official_battery[b])
            for b in normal_peers
        }
        selected = {b: self._official_offer(offers[b]) for b in normal_peers}
        target, last_district, scale = self._district_reference(official_net)
        fixed_net = float(
            sum(official_net[b] for b in range(self.n_buildings) if b not in normal_peers)
        )
        final_shadow = 0.0

        for round_id in range(self.mesh_config.rounds):
            proposal = fixed_net + float(sum(selected[b].predicted_grid for b in normal_peers))
            final_shadow = self._shadow_signal(proposal, target, last_district, scale)
            recipient_count = max(len(normal_peers) - 1, 0)

            for b in normal_peers:
                options = offers[b]
                self.message_log.append(
                    FlexBroadcast(
                        step=self.seen_steps,
                        round_id=round_id,
                        sender=b,
                        official_grid=float(official_net[b]),
                        proposed_grid=float(selected[b].predicted_grid),
                        lower_grid=float(min(o.predicted_grid for o in options)),
                        upper_grid=float(max(o.predicted_grid for o in options)),
                        soc=float(self.cur_battery_soc[b]),
                        district_proposal=proposal,
                        district_target=target,
                        shadow_signal=final_shadow,
                        recipient_count=recipient_count,
                    ).to_dict()
                )

            selected = {
                b: min(
                    offers[b],
                    key=lambda option: self._peer_score(
                        option, self._official_offer(offers[b]), final_shadow, scale
                    ),
                )
                for b in normal_peers
            }

        negotiated_actions = official_actions.copy()
        changed_peers = 0
        for b in normal_peers:
            chosen = selected[b]
            baseline = self._official_offer(offers[b])
            negotiated_actions[3 * b + 1] = chosen.battery_action
            self.predicted_battery_demand[b] = chosen.battery_demand
            if not np.isclose(chosen.battery_action, baseline.battery_action):
                changed_peers += 1

        official_district = float(np.sum(official_net))
        negotiated_district = fixed_net + float(
            sum(selected[b].predicted_grid for b in normal_peers)
        )
        logical_messages = self.mesh_config.rounds * len(normal_peers) * max(len(normal_peers) - 1, 0)
        self.negotiation_log.append(
            NegotiationOutcome(
                step=self.seen_steps,
                hour=int(hour),
                active_peers=len(normal_peers),
                changed_peers=changed_peers,
                official_predicted_grid=official_district,
                negotiated_predicted_grid=negotiated_district,
                predicted_grid_delta=negotiated_district - official_district,
                district_target=target,
                final_shadow_signal=final_shadow,
                logical_message_count=logical_messages,
            ).to_dict()
        )
        return negotiated_actions

    def _signal(self, name: str) -> float:
        if self._latest_observations is None or name not in self.observation_names_b:
            return 0.0
        return float(self._latest_observations[self.observation_names_b.index(name)])

    def _official_predicted_net(self, official_actions) -> tuple[np.ndarray, np.ndarray]:
        predicted_net = np.zeros(self.n_buildings)
        predicted_battery = np.zeros(self.n_buildings)
        for b in range(self.n_buildings):
            battery_demand, _ = self.compute_pred_battery_consumption(
                b, official_actions[3 * b + 1]
            )
            predicted_battery[b] = battery_demand
            predicted_net[b] = (
                self.forecasts[b]["non_shiftable_load"][0]
                + self.predicted_cooling_demand[b]
                + self.predicted_dhw_device_demand[b]
                + battery_demand
                - self.forecasts[b]["solar_generation"][0]
            )
        return predicted_net, predicted_battery

    def _offers_for_peer(
        self, b: int, official_actions, official_net: float, official_battery: float
    ) -> list[FlexOffer]:
        base_action = float(official_actions[3 * b + 1])
        step = self.mesh_config.offer_step
        changes = [
            (-step, "relief"),
            (-0.5 * step, "relief_soft"),
            (0.0, "official_chesca"),
            (0.5 * step, "absorb_soft"),
            (step, "absorb"),
        ]
        offers: list[FlexOffer] = []
        seen: set[tuple[float, float]] = set()
        for delta, offer_id in changes:
            action = float(
                np.clip(
                    base_action + delta,
                    self.env.action_space[0].low[3 * b + 1],
                    self.env.action_space[0].high[3 * b + 1],
                )
            )
            battery_demand, _ = self.compute_pred_battery_consumption(b, action)
            predicted_grid = official_net + battery_demand - official_battery
            key = (round(action, 8), round(float(battery_demand), 8))
            if key in seen:
                continue
            seen.add(key)
            offers.append(
                FlexOffer(
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
                )
            )
        return offers

    @staticmethod
    def _official_offer(offers: list[FlexOffer]) -> FlexOffer:
        return min(offers, key=lambda offer: abs(offer.delta_from_official))

    def _district_reference(self, official_net: np.ndarray) -> tuple[float, float, float]:
        lengths = [len(history) for history in self.elec_consumption_history]
        history_length = min(lengths) if lengths else 0
        if history_length == 0:
            district_history = np.asarray([float(np.sum(official_net))])
        else:
            district_history = np.sum(
                np.asarray([history[-history_length:] for history in self.elec_consumption_history]),
                axis=0,
            )
        window = district_history[-self.mesh_config.history_window :]
        if len(window) < self.mesh_config.minimum_history:
            target = float(np.sum(official_net))
        else:
            target = float(np.quantile(window, self.mesh_config.target_quantile))
        last_district = float(window[-1])
        scale = max(float(np.std(window)), abs(target) * 0.10, 1.0)
        return target, last_district, scale

    def _shadow_signal(
        self, district_proposal: float, target: float, last_district: float, scale: float
    ) -> float:
        excess = (district_proposal - target) / scale
        ramp = (district_proposal - last_district) / scale
        price_z = self._standardized_signal(self.price_history)
        carbon_z = self._standardized_signal(self.carbon_history)
        reserve_deficit = float(
            np.mean(np.maximum(self.mesh_config.reserve_soc - self.cur_battery_soc, 0.0))
        )
        recovery = (
            self.mesh_config.recovery_weight
            * reserve_deficit
            * max((target - district_proposal) / scale, 0.0)
        )
        return (
            self.mesh_config.peak_weight * max(excess, 0.0)
            + self.mesh_config.ramp_weight * ramp
            + self.mesh_config.price_weight * price_z
            + self.mesh_config.carbon_weight * carbon_z
            - recovery
        )

    @staticmethod
    def _standardized_signal(history: list[float]) -> float:
        if len(history) < 4:
            return 0.0
        values = np.asarray(history[-168:], dtype=float)
        spread = max(float(np.std(values)), 1e-6)
        return float((values[-1] - np.mean(values)) / spread)

    def _peer_score(
        self, option: FlexOffer, official: FlexOffer, shadow_signal: float, scale: float
    ) -> float:
        reserve_penalty = max(self.mesh_config.reserve_soc - option.estimated_soc_after, 0.0)
        official_reserve_penalty = max(
            self.mesh_config.reserve_soc - official.estimated_soc_after, 0.0
        )
        return (
            shadow_signal * option.delta_from_official / scale
            + self.mesh_config.wear_weight * abs(option.delta_from_official) / scale
            + self.mesh_config.reserve_weight * (reserve_penalty - official_reserve_penalty)
            + self.mesh_config.action_deviation_weight
            * abs(option.battery_action - official.battery_action)
        )
