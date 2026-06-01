"""Evaluation entry point for commitment mesh ablations."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .commitment_mesh_agent import CommitmentConfig, CommitmentMeshCheca
from .evaluation import BenchmarkResult, BenchmarkSuite, ControllerRun, LeaderboardResult, WrapperEnv
from .official import official_working_directory


class CommitmentBenchmarkSuite(BenchmarkSuite):
    """Compare CHESCA, previous mesh, and commitment-mesh ablations."""

    COMMITMENT_CONTROLLERS = {
        "chesca_commitment_ledger_mesh": {
            "enable_ledger": True,
            "enable_recovery": False,
            "enable_budget": False,
        },
        "chesca_commitment_recovery_mesh": {
            "enable_ledger": True,
            "enable_recovery": True,
            "enable_budget": False,
        },
        "chesca_commitment_budget_mesh": {
            "enable_ledger": False,
            "enable_recovery": False,
            "enable_budget": True,
        },
        "chesca_commitment_full_mesh": {
            "enable_ledger": True,
            "enable_recovery": True,
            "enable_budget": True,
        },
    }
    SUPPORTED_CONTROLLERS = (
        "chesca_official",
        "chesca_mesh",
        *COMMITMENT_CONTROLLERS.keys(),
    )

    def __init__(
        self,
        output_directory: str | Path | None = None,
        mesh_config=None,
        commitment_config: CommitmentConfig | None = None,
        power_outage_seed: int | None = None,
    ):
        super().__init__(
            output_directory=output_directory,
            mesh_config=mesh_config,
            power_outage_seed=power_outage_seed,
        )
        self.commitment_config = commitment_config or CommitmentConfig()

    def compare_controllers(
        self,
        dataset_name: str = "citylearn_challenge_2023_phase_3_1",
        controllers: tuple[str, ...] | list[str] | None = None,
        episode_steps: int | None = None,
        tag: str = "commitment_ablation_v1",
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
        tag: str = "paper_public_private_commitment_v1",
    ) -> LeaderboardResult:
        result = super().compare_public_private_costs(
            controllers=list(controllers or ("chesca_official", "chesca_mesh", "chesca_commitment_full_mesh")),
            episode_steps=episode_steps,
            tag=tag,
        )
        metadata_path = result.output_directory / "public_private_metadata.json"
        with metadata_path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
        metadata.update(self._commitment_metadata())
        with metadata_path.open("w", encoding="utf-8") as target:
            json.dump(metadata, target, ensure_ascii=True, indent=2)
        return result

    def _run_controller(
        self, controller: str, dataset_name: str, episode_steps: int | None
    ) -> ControllerRun:
        if controller not in self.COMMITMENT_CONTROLLERS:
            return super()._run_controller(controller, dataset_name, episode_steps)

        config = self._config_for_controller(controller)
        with official_working_directory():
            env = self._make_environment(dataset_name, episode_steps)
            self._set_power_outage_seed(env)
            agent = CommitmentMeshCheca(
                WrapperEnv(env),
                commitment_config=config,
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
            summary.update(self._commitment_summary(negotiations))
        return ControllerRun(controller, summary, metrics, messages, negotiations)

    def _config_for_controller(self, controller: str) -> CommitmentConfig:
        flags = self.COMMITMENT_CONTROLLERS[controller]
        return replace(self.commitment_config, **flags)

    @staticmethod
    def _commitment_summary(negotiations: list[dict]) -> dict:
        return {
            "debt_created_soc_total": float(
                np.sum([row["debt_created_soc"] for row in negotiations])
            ),
            "debt_repaid_soc_total": float(
                np.sum([row["debt_repaid_soc"] for row in negotiations])
            ),
            "extra_discharge_soc_total": float(
                np.sum([row["extra_discharge_soc"] for row in negotiations])
            ),
            "extra_charge_soc_total": float(
                np.sum([row["extra_charge_soc"] for row in negotiations])
            ),
            "mean_total_debt_soc": float(
                np.mean([row["total_debt_soc"] for row in negotiations])
            ),
            "max_total_debt_soc": float(
                np.max([row["total_debt_soc"] for row in negotiations])
            ),
            "max_peer_debt_soc": float(
                np.max([row["max_debt_soc"] for row in negotiations])
            ),
            "recovery_action_steps": int(
                np.sum([row["recovery_selected_peers"] > 0 for row in negotiations])
            ),
            "relief_action_steps": int(
                np.sum([row["relief_selected_peers"] > 0 for row in negotiations])
            ),
            "mean_budget_use_soc": float(
                np.mean([row["mean_budget_use_soc"] for row in negotiations])
            ),
        }

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
        metadata.update(self._commitment_metadata())
        with metadata_path.open("w", encoding="utf-8") as target:
            json.dump(metadata, target, ensure_ascii=True, indent=2)

    def _commitment_metadata(self) -> dict:
        return {
            "commitment_base_config": asdict(self.commitment_config),
            "commitment_controllers": {
                name: asdict(self._config_for_controller(name))
                for name in self.COMMITMENT_CONTROLLERS
            },
            "commitment_note": (
                "Commitment controllers keep the previous peer negotiation cadence. "
                "Ledger, local recovery, and soft throughput budget are exposed as "
                "separate ablation switches so their effects can be measured independently."
            ),
        }
