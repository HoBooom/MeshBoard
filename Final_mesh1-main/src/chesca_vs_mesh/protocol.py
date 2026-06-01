"""Typed messages exchanged by the CHESCA-based peer mesh."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FlexOffer:
    sender: int
    offer_id: str
    battery_action: float
    battery_demand: float
    predicted_grid: float
    delta_from_official: float
    estimated_soc_after: float


@dataclass(frozen=True)
class FlexBroadcast:
    step: int
    round_id: int
    sender: int
    official_grid: float
    proposed_grid: float
    lower_grid: float
    upper_grid: float
    soc: float
    district_proposal: float
    district_target: float
    shadow_signal: float
    recipient_count: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NegotiationOutcome:
    step: int
    hour: int
    active_peers: int
    changed_peers: int
    official_predicted_grid: float
    negotiated_predicted_grid: float
    predicted_grid_delta: float
    district_target: float
    final_shadow_signal: float
    logical_message_count: int

    def to_dict(self) -> dict:
        return asdict(self)
