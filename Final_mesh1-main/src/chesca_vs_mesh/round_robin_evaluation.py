"""Evaluation for the round-robin coordinator commitment mesh."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .commitment_evaluation import CommitmentBenchmarkSuite
from .commitment_mesh_agent import CommitmentConfig
from .evaluation import BenchmarkResult, ControllerRun, LeaderboardResult, WrapperEnv
from .official import official_working_directory
from .round_robin_commitment_agent import RoundRobinCommitmentMeshCheca


class RoundRobinBenchmarkSuite(CommitmentBenchmarkSuite):
    """Adds a round-robin coordinator controller without changing old suites."""

    ROUND_ROBIN_CONTROLLER = "chesca_round_robin_commitment_full_mesh"
    SUPPORTED_CONTROLLERS = (
        *CommitmentBenchmarkSuite.SUPPORTED_CONTROLLERS,
        ROUND_ROBIN_CONTROLLER,
    )

    def __init__(
        self,
        output_directory: str | Path | None = None,
        mesh_config=None,
        commitment_config: CommitmentConfig | None = None,
        power_outage_seed: int | None = None,
        unavailable_coordinators: tuple[int, ...] | list[int] | None = None,
    ):
        super().__init__(
            output_directory=output_directory,
            mesh_config=mesh_config,
            commitment_config=commitment_config,
            power_outage_seed=power_outage_seed,
        )
        self.unavailable_coordinators = tuple(unavailable_coordinators or ())

    def compare_controllers(
        self,
        dataset_name: str = "citylearn_challenge_2023_phase_3_1",
        controllers: tuple[str, ...] | list[str] | None = None,
        episode_steps: int | None = None,
        tag: str = "round_robin_commitment_v1",
    ) -> BenchmarkResult:
        return super().compare_controllers(
            dataset_name=dataset_name,
            controllers=list(
                controllers
                or (
                    "chesca_official",
                    "chesca_commitment_full_mesh",
                    self.ROUND_ROBIN_CONTROLLER,
                )
            ),
            episode_steps=episode_steps,
            tag=tag,
        )

    def compare_public_private_costs(
        self,
        controllers: tuple[str, ...] | list[str] | None = None,
        episode_steps: int | None = None,
        tag: str = "paper_public_private_round_robin_commitment_v1",
    ) -> LeaderboardResult:
        result = super().compare_public_private_costs(
            controllers=list(
                controllers
                or (
                    "chesca_official",
                    "chesca_commitment_full_mesh",
                    self.ROUND_ROBIN_CONTROLLER,
                )
            ),
            episode_steps=episode_steps,
            tag=tag,
        )
        metadata_path = result.output_directory / "public_private_metadata.json"
        with metadata_path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
        metadata.update(self._round_robin_metadata())
        with metadata_path.open("w", encoding="utf-8") as target:
            json.dump(metadata, target, ensure_ascii=True, indent=2)
        return result

    def _run_controller(
        self, controller: str, dataset_name: str, episode_steps: int | None
    ) -> ControllerRun:
        if controller != self.ROUND_ROBIN_CONTROLLER:
            return super()._run_controller(controller, dataset_name, episode_steps)

        with official_working_directory():
            env = self._make_environment(dataset_name, episode_steps)
            self._set_power_outage_seed(env)
            agent = RoundRobinCommitmentMeshCheca(
                WrapperEnv(env),
                commitment_config=self._config_for_controller(
                    "chesca_commitment_full_mesh"
                ),
                unavailable_coordinators=self.unavailable_coordinators,
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
            summary["coordinator_switches"] = int(len(agent.coordinator_log))
            summary["unique_coordinators"] = int(
                len({row["coordinator_id"] for row in agent.coordinator_log})
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
        metadata.update(self._round_robin_metadata())
        with metadata_path.open("w", encoding="utf-8") as target:
            json.dump(metadata, target, ensure_ascii=True, indent=2)

    def _round_robin_metadata(self) -> dict:
        return {
            "round_robin_controller": self.ROUND_ROBIN_CONTROLLER,
            "unavailable_coordinators": list(self.unavailable_coordinators),
            "round_robin_note": (
                "A building agent is selected by round-robin each step as the "
                "temporary coordinator. That coordinator owns the CHESCA planner "
                "tool that creates the baseline proposal. With no unavailable "
                "coordinators, the action path should match chesca_commitment_full_mesh."
            ),
            "commitment_config": asdict(self.commitment_config),
        }
