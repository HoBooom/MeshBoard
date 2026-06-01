"""Colab-friendly evaluation of official CHESCA against CHESCA+Mesh."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .mesh_agent import MeshCheca, MeshConfig
from .official import (
    official_agent_class,
    official_reward_class,
    official_working_directory,
    project_root,
    schema_path,
)


class WrapperEnv:
    """The same restricted environment view provided by official CHESCA."""

    def __init__(self, env):
        self.observation_names = env.observation_names
        self.action_names = env.action_names
        self.observation_space = env.observation_space
        self.action_space = env.action_space
        self.time_steps = env.time_steps
        self.seconds_per_time_step = None
        self.random_seed = None
        self.episode_tracker = None
        self.buildings_metadata = env.get_metadata()["buildings"]

    def get_metadata(self):
        return {"buildings": self.buildings_metadata}


@dataclass
class ControllerRun:
    controller: str
    summary: dict[str, Any]
    challenge_metrics: dict[str, Any]
    messages: list[dict[str, Any]]
    negotiations: list[dict[str, Any]]


@dataclass
class BenchmarkResult:
    summary: pd.DataFrame
    citylearn_metrics: pd.DataFrame
    messages: pd.DataFrame
    negotiations: pd.DataFrame
    output_directory: Path


@dataclass
class LeaderboardResult:
    """Public/private leaderboard reproduction across the bundled schemas."""

    runs: pd.DataFrame
    summary: pd.DataFrame
    paper_table: pd.DataFrame
    output_directory: Path


class BenchmarkSuite:
    """Run official source code and mesh extension on the bundled schemas."""

    SUPPORTED_CONTROLLERS = ("chesca_official", "chesca_mesh")
    PAPER_SPLITS = {
        "public": (
            "citylearn_challenge_2023_phase_2_online_evaluation_1",
            "citylearn_challenge_2023_phase_2_online_evaluation_2",
            "citylearn_challenge_2023_phase_2_online_evaluation_3",
        ),
        "private": (
            "citylearn_challenge_2023_phase_3_1",
            "citylearn_challenge_2023_phase_3_2",
            "citylearn_challenge_2023_phase_3_3",
        ),
    }
    CHALLENGE_WEIGHTS = {
        "comfort_cost": 0.30,
        "emissions_cost": 0.10,
        "grid_cost": 0.30,
        "resilience_cost": 0.30,
    }

    def __init__(
        self,
        output_directory: str | Path | None = None,
        mesh_config: MeshConfig | None = None,
        power_outage_seed: int | None = None,
    ):
        self.output_directory = Path(output_directory or project_root() / "results")
        self.mesh_config = mesh_config or MeshConfig()
        self.power_outage_seed = power_outage_seed

    def compare_controllers(
        self,
        dataset_name: str = "citylearn_challenge_2023_phase_3_1",
        controllers: tuple[str, ...] | list[str] = SUPPORTED_CONTROLLERS,
        episode_steps: int | None = None,
        tag: str = "chesca_official_vs_mesh",
    ) -> BenchmarkResult:
        requested = list(controllers)
        unknown = sorted(set(requested) - set(self.SUPPORTED_CONTROLLERS))
        if unknown:
            raise ValueError(f"Unknown controllers: {unknown}. Supported: {self.SUPPORTED_CONTROLLERS}")

        runs = [
            self._run_controller(controller, dataset_name, episode_steps)
            for controller in requested
        ]
        summary = pd.DataFrame([run.summary for run in runs])
        challenge = pd.DataFrame(
            [{"controller": run.controller, **run.challenge_metrics} for run in runs]
        )
        messages = pd.DataFrame(
            [
                {"controller": run.controller, **message}
                for run in runs
                for message in run.messages
            ]
        )
        negotiations = pd.DataFrame(
            [
                {"controller": run.controller, **negotiation}
                for run in runs
                for negotiation in run.negotiations
            ]
        )
        summary = self._add_relative_changes(summary, reference="chesca_official")
        output = self.output_directory / dataset_name / tag
        self._save_result(output, dataset_name, episode_steps, summary, challenge, messages, negotiations)
        return BenchmarkResult(summary, challenge, messages, negotiations, output)

    def compare_public_private_costs(
        self,
        controllers: tuple[str, ...] | list[str] = SUPPORTED_CONTROLLERS,
        episode_steps: int | None = None,
        tag: str = "paper_public_private_cost",
    ) -> LeaderboardResult:
        """Evaluate paper-style Public Cost and Private Cost.

        Public uses the three phase-2 online evaluation schemas (three buildings)
        and private uses the three phase-3 schemas (six buildings). Each set has
        identical load data with three bundled outage seeds; the reported cost
        is the mean of those runs, matching the challenge evaluation structure.
        """
        run_frames = []
        for split, datasets in self.PAPER_SPLITS.items():
            for run_id, dataset_name in enumerate(datasets, start=1):
                result = self.compare_controllers(
                    dataset_name=dataset_name,
                    controllers=controllers,
                    episode_steps=episode_steps,
                    tag=tag,
                )
                frame = result.summary.copy()
                frame.insert(0, "run_id", run_id)
                frame.insert(0, "dataset", dataset_name)
                frame.insert(0, "split", split)
                run_frames.append(frame)

        runs = pd.concat(run_frames, ignore_index=True)
        columns = [
            "challenge_cost",
            "comfort_cost",
            "emissions_cost",
            "grid_cost",
            "resilience_cost",
        ]
        summary = (
            runs.groupby(["split", "controller"], as_index=False)[columns]
            .mean()
            .rename(columns={"challenge_cost": "leaderboard_cost"})
        )
        summary = self._add_split_reference_change(summary)
        paper_table = (
            summary.pivot(index="controller", columns="split", values="leaderboard_cost")
            .rename(columns={"private": "Private Cost", "public": "Public Cost"})
            .reset_index()
        )
        for split, label in (("private", "Private Cost"), ("public", "Public Cost")):
            changes = summary.loc[
                summary["split"] == split,
                ["controller", "leaderboard_cost_change_vs_chesca_pct"],
            ].rename(
                columns={
                    "leaderboard_cost_change_vs_chesca_pct": f"{label} Change vs CHESCA (%)"
                }
            )
            paper_table = paper_table.merge(changes, on="controller", how="left")
        paper_table = paper_table[
            [
                "controller",
                "Private Cost",
                "Public Cost",
                "Private Cost Change vs CHESCA (%)",
                "Public Cost Change vs CHESCA (%)",
            ]
        ]
        output = self.output_directory / tag
        output.mkdir(parents=True, exist_ok=True)
        runs.to_csv(output / "public_private_runs.csv", index=False)
        summary.to_csv(output / "public_private_summary.csv", index=False)
        paper_table.to_csv(output / "paper_table.csv", index=False)
        with (output / "public_private_metadata.json").open("w", encoding="utf-8") as target:
            json.dump(
                {
                    "public_datasets": list(self.PAPER_SPLITS["public"]),
                    "private_datasets": list(self.PAPER_SPLITS["private"]),
                    "controllers": list(controllers),
                    "episode_steps": episode_steps,
                    "challenge_weights": self.CHALLENGE_WEIGHTS,
                    "grid_submetrics_equal_weight": [
                        "ramping_average",
                        "daily_one_minus_load_factor_average",
                        "daily_peak_average",
                        "annual_peak_average",
                    ],
                    "resilience_submetrics_equal_weight": [
                        "one_minus_thermal_resilience_proportion",
                        "power_outage_normalized_unserved_energy_total",
                    ],
                },
                target,
                ensure_ascii=True,
                indent=2,
            )
        return LeaderboardResult(
            runs=runs, summary=summary, paper_table=paper_table, output_directory=output
        )

    def _run_controller(
        self, controller: str, dataset_name: str, episode_steps: int | None
    ) -> ControllerRun:
        with official_working_directory():
            env = self._make_environment(dataset_name, episode_steps)
            self._set_power_outage_seed(env)
            wrapper = WrapperEnv(env)
            if controller == "chesca_official":
                agent = official_agent_class()(wrapper)
            else:
                agent = MeshCheca(wrapper, mesh_config=self.mesh_config)

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

        messages = list(getattr(agent, "message_log", []))
        negotiations = list(getattr(agent, "negotiation_log", []))
        return ControllerRun(controller, summary, metrics, messages, negotiations)

    def _make_environment(self, dataset_name: str, episode_steps: int | None):
        from citylearn.citylearn import CityLearnEnv

        original_schema = schema_path(dataset_name)
        reward = official_reward_class()
        if episode_steps is None:
            schema: str | dict = str(original_schema)
        else:
            with original_schema.open("r", encoding="utf-8") as source:
                schema = json.load(source)
            start = int(schema.get("simulation_start_time_step", 0))
            schema["simulation_end_time_step"] = start + int(episode_steps)
            schema["root_directory"] = str(original_schema.parent)
        return CityLearnEnv(schema, reward_function=reward)

    def _set_power_outage_seed(self, env) -> None:
        if self.power_outage_seed is None:
            return
        for building in env.buildings:
            model = getattr(building, "stochastic_power_outage_model", None)
            if model is not None:
                model.random_seed = self.power_outage_seed

    @staticmethod
    def _reset(env):
        result = env.reset()
        if isinstance(result, tuple) and len(result) == 2:
            return result[0]
        return result

    @staticmethod
    def _step(env, actions) -> tuple[Any, bool]:
        result = env.step(actions)
        if len(result) == 5:
            observations, _, terminated, truncated, _ = result
            return observations, bool(terminated or truncated)
        observations, _, done, _ = result
        return observations, bool(done)

    @staticmethod
    def _flatten_challenge_metrics(metrics: Any) -> dict[str, Any]:
        if not isinstance(metrics, dict):
            return {"challenge_metrics": str(metrics)}
        flattened: dict[str, Any] = {}
        for key, value in metrics.items():
            if isinstance(value, dict) and "value" in value:
                flattened[key] = value["value"]
            elif np.isscalar(value):
                flattened[key] = value
            else:
                flattened[key] = str(value)
        return flattened

    def _challenge_cost(self, metrics: dict[str, Any]) -> dict[str, float]:
        """Calculate the CityLearn 2023 weighted leaderboard objective."""
        comfort = self._required_metric(metrics, "discomfort_proportion")
        emissions = self._required_metric(metrics, "carbon_emissions_total")
        grid = float(
            np.mean(
                [
                    self._required_metric(metrics, "ramping_average"),
                    self._required_metric(metrics, "daily_one_minus_load_factor_average"),
                    self._required_metric(metrics, "daily_peak_average"),
                    self._required_metric(metrics, "annual_peak_average", "all_time_peak_average"),
                ]
            )
        )
        resilience = float(
            np.mean(
                [
                    self._required_metric(metrics, "one_minus_thermal_resilience_proportion"),
                    self._required_metric(
                        metrics, "power_outage_normalized_unserved_energy_total"
                    ),
                ]
            )
        )
        formula_cost = (
            self.CHALLENGE_WEIGHTS["comfort_cost"] * comfort
            + self.CHALLENGE_WEIGHTS["emissions_cost"] * emissions
            + self.CHALLENGE_WEIGHTS["grid_cost"] * grid
            + self.CHALLENGE_WEIGHTS["resilience_cost"] * resilience
        )
        official_cost = metrics.get("average_score")
        if official_cost is not None and not np.isclose(float(official_cost), formula_cost, atol=1e-5):
            raise ValueError(
                f"Calculated challenge cost {formula_cost} differs from CityLearn "
                f"average_score {official_cost}."
            )
        cost = float(official_cost) if official_cost is not None else float(formula_cost)
        return {
            "challenge_cost": cost,
            "comfort_cost": comfort,
            "emissions_cost": emissions,
            "grid_cost": grid,
            "resilience_cost": resilience,
        }

    @staticmethod
    def _required_metric(metrics: dict[str, Any], *keys: str) -> float:
        for key in keys:
            if key in metrics:
                return float(metrics[key])
        available = ", ".join(sorted(metrics))
        expected = " or ".join(f"'{key}'" for key in keys)
        raise KeyError(
            f"CityLearn challenge output has no {expected} metric. Available metrics: {available}"
        )

    def _native_summary(self, env, controller: str, steps: int, elapsed: float, agent) -> dict:
        district_net = self._district_series(env, ("net_electricity_consumption",))
        import_series = np.maximum(district_net, 0.0)
        cost = self._district_series(
            env, ("net_electricity_consumption_cost", "electricity_consumption_cost"), required=False
        )
        carbon = self._district_series(
            env,
            ("net_electricity_consumption_emission", "carbon_emissions", "carbon_emission"),
            required=False,
        )
        negotiations = list(getattr(agent, "negotiation_log", []))
        changed_steps = sum(int(row["changed_peers"] > 0) for row in negotiations)
        logical_messages = sum(int(row["logical_message_count"]) for row in negotiations)
        return {
            "controller": controller,
            "steps": int(steps),
            "grid_import_kwh": float(np.sum(import_series)),
            "total_cost": float(np.sum(cost)) if cost is not None else np.nan,
            "carbon_kg": float(np.sum(carbon)) if carbon is not None else np.nan,
            "peak_kwh": float(np.max(import_series)),
            "ramping_kwh": float(np.sum(np.abs(np.diff(district_net)))),
            "agent_time_seconds": float(elapsed),
            "agreement_steps": int(len(negotiations)),
            "changed_trade_steps": int(changed_steps),
            "changed_trade_step_pct": (
                100.0 * changed_steps / len(negotiations) if negotiations else 0.0
            ),
            "predicted_grid_delta_mean": (
                float(np.mean([row["predicted_grid_delta"] for row in negotiations]))
                if negotiations
                else 0.0
            ),
            "message_count": int(logical_messages),
        }

    @staticmethod
    def _district_series(env, attributes: tuple[str, ...], required: bool = True):
        for attribute in attributes:
            if hasattr(env, attribute):
                values = np.asarray(getattr(env, attribute), dtype=float)
                if values.size > 0:
                    return values
        per_building = []
        for building in env.buildings:
            for attribute in attributes:
                if hasattr(building, attribute):
                    per_building.append(np.asarray(getattr(building, attribute), dtype=float))
                    break
        if per_building:
            return np.sum(np.asarray(per_building), axis=0)
        if required:
            raise AttributeError(f"None of {attributes} are exposed by the CityLearn environment.")
        return None

    @staticmethod
    def _add_relative_changes(summary: pd.DataFrame, reference: str) -> pd.DataFrame:
        if reference not in set(summary["controller"]):
            return summary
        ref = summary.loc[summary["controller"] == reference].iloc[0]
        for column in (
            "challenge_cost",
            "comfort_cost",
            "emissions_cost",
            "grid_cost",
            "resilience_cost",
            "grid_import_kwh",
            "total_cost",
            "carbon_kg",
            "peak_kwh",
            "ramping_kwh",
        ):
            base = ref[column]
            change_column = f"{column}_change_vs_chesca_pct"
            if pd.isna(base) or np.isclose(base, 0.0):
                summary[change_column] = np.nan
            else:
                summary[change_column] = 100.0 * (summary[column] - base) / base
        return summary

    @staticmethod
    def _add_split_reference_change(summary: pd.DataFrame) -> pd.DataFrame:
        reference = summary.loc[
            summary["controller"] == "chesca_official", ["split", "leaderboard_cost"]
        ].rename(columns={"leaderboard_cost": "_reference_cost"})
        summary = summary.merge(reference, on="split", how="left")
        summary["leaderboard_cost_change_vs_chesca_pct"] = (
            100.0
            * (summary["leaderboard_cost"] - summary["_reference_cost"])
            / summary["_reference_cost"]
        )
        return summary.drop(columns="_reference_cost")

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
        output.mkdir(parents=True, exist_ok=True)
        summary.to_csv(output / "summary.csv", index=False)
        challenge.to_csv(output / "citylearn_challenge_metrics.csv", index=False)
        messages.to_csv(output / "mesh_messages.csv", index=False)
        negotiations.to_csv(output / "mesh_negotiations.csv", index=False)
        metadata = {
            "dataset_name": dataset_name,
            "episode_steps": episode_steps,
            "official_schema": str(schema_path(dataset_name)),
            "controllers": list(summary["controller"]),
            "power_outage_seed": self.power_outage_seed,
            "mesh_config": asdict(self.mesh_config),
            "reproduction_note": (
                "chesca_official loads the unmodified CHESCA-main SubmissionAgent. "
                "chesca_mesh preserves that agent as an outside option and adds peer battery negotiation."
            ),
        }
        with (output / "run_metadata.json").open("w", encoding="utf-8") as target:
            json.dump(metadata, target, ensure_ascii=True, indent=2)
