"""Evaluation entry point for the reserve-contract CHESCA mesh experiment."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluation import BenchmarkResult, BenchmarkSuite, ControllerRun, LeaderboardResult, WrapperEnv
from .official import official_working_directory
from .reserve_mesh_agent import ReserveContractConfig, ReserveContractMeshCheca


class ReserveBenchmarkSuite(BenchmarkSuite):
    """Compare official CHESCA, the earlier mesh, and reserve-contract mesh."""

    SUPPORTED_CONTROLLERS = (
        "chesca_official",
        "chesca_mesh",
        "chesca_reserve_contract_mesh",
    )

    def __init__(
        self,
        output_directory: str | Path | None = None,
        mesh_config=None,
        reserve_config: ReserveContractConfig | None = None,
        power_outage_seed: int | None = None,
    ):
        super().__init__(
            output_directory=output_directory,
            mesh_config=mesh_config,
            power_outage_seed=power_outage_seed,
        )
        self.reserve_config = reserve_config or ReserveContractConfig()

    def compare_controllers(
        self,
        dataset_name: str = "citylearn_challenge_2023_phase_3_1",
        controllers: tuple[str, ...] | list[str] | None = None,
        episode_steps: int | None = None,
        tag: str = "reserve_contract_comparison_v1",
    ) -> BenchmarkResult:
        return super().compare_controllers(
            dataset_name=dataset_name,
            controllers=list(controllers or self.SUPPORTED_CONTROLLERS),
            episode_steps=episode_steps,
            tag=tag,
        )

    def compare_public_private_costs(
        self,
        controllers: tuple[str, ...] | list[str] | None = None,
        episode_steps: int | None = None,
        tag: str = "paper_public_private_reserve_contract_v1",
    ) -> LeaderboardResult:
        result = super().compare_public_private_costs(
            controllers=list(controllers or self.SUPPORTED_CONTROLLERS),
            episode_steps=episode_steps,
            tag=tag,
        )
        metadata_path = result.output_directory / "public_private_metadata.json"
        with metadata_path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
        metadata.update(self._reserve_metadata())
        with metadata_path.open("w", encoding="utf-8") as target:
            json.dump(metadata, target, ensure_ascii=True, indent=2)
        return result

    def _run_controller(
        self, controller: str, dataset_name: str, episode_steps: int | None
    ) -> ControllerRun:
        if controller != "chesca_reserve_contract_mesh":
            return super()._run_controller(controller, dataset_name, episode_steps)

        with official_working_directory():
            env = self._make_environment(dataset_name, episode_steps)
            self._set_power_outage_seed(env)
            agent = ReserveContractMeshCheca(
                WrapperEnv(env),
                contract_config=self.reserve_config,
            )
            observations = self._reset(env)
            start = time.perf_counter()
            actions = agent.register_reset(observations)
            done = False
            step_count = 0
            while not done:
                observations, done = self._step(env, actions)
                step_count += 1
                if not done:
                    actions = agent.predict(observations)
            elapsed = time.perf_counter() - start
            metrics = self._flatten_challenge_metrics(env.evaluate_citylearn_challenge())
            summary = self._native_summary(env, controller, step_count, elapsed, agent)
            summary.update(self._challenge_cost(metrics))

        messages = list(agent.message_log)
        negotiations = list(agent.negotiation_log)
        if negotiations:
            summary.update(
                {
                    "reserve_limited_step_pct": float(
                        100.0
                        * np.mean([row["reserve_limited_peers"] > 0 for row in negotiations])
                    ),
                    "reserve_limited_peer_mean": float(
                        np.mean([row["reserve_limited_peers"] for row in negotiations])
                    ),
                    "selected_reserve_margin_min": float(
                        np.min([row["selected_reserve_margin_min"] for row in negotiations])
                    ),
                }
            )
        return ControllerRun(controller, summary, metrics, messages, negotiations)

    def _save_result(
        self,
        output: Path,
        dataset_name: str,
        episode_steps: int | None,
        summary: pd.DataFrame,
        challenge: pd.DataFrame,
        messages: pd.DataFrame,
        negotiations: pd.DataFrame,
    ) -> None:
        super()._save_result(
            output,
            dataset_name,
            episode_steps,
            summary,
            challenge,
            messages,
            negotiations,
        )
        metadata_path = output / "run_metadata.json"
        with metadata_path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
        metadata.update(self._reserve_metadata())
        with metadata_path.open("w", encoding="utf-8") as target:
            json.dump(metadata, target, ensure_ascii=True, indent=2)

    def _reserve_metadata(self) -> dict:
        return {
            "reserve_contract_config": asdict(self.reserve_config),
            "reserve_contract_note": (
                "chesca_reserve_contract_mesh preserves CHESCA's time-varying "
                "next-hour minimum SOC as a hard limit on additional discharge offers. "
                "It is a protocol constraint, not a cost fitted to evaluation seeds."
            ),
        }
