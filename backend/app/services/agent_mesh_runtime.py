"""OpenSynCity 정전 MPC Mesh runtime bridge for the city-management board.

이 모듈은 연구 노트북 ``research/agent_mesh.ipynb`` 의 모델(에이전틱 메시 + 배터리 MPC +
정전 회복력)을 mesh_chesca board의 **새 시나리오(outage_mpc_mesh)** 로 그대로 재현한다.

핵심 설계(citylearn_sacrbc_inference.py와 동일한 패턴):
- mesh_chesca의 CHESCA 런타임은 vendored CityLearn 2.1b12를 쓰므로 별도 워커 프로세스에서만
  돈다. 반면 이 모델은 노트북과 동일하게 ``CityLearn_old_system`` (CityLearn 2.6.0b2)을 쓴다.
  이는 메인 API 프로세스가 이미 SACRBC 추론에 쓰는 바로 그 CityLearn이라 충돌이 없다 →
  **이 런타임은 메인 프로세스에서 in-process로 실행**한다(워커 불필요).
- 무거운 CityLearn import는 lazy. 의존성이 없으면 AgentMeshUnavailable을 던져 API가 깔끔한
  503을 돌려주게 한다.
- AgentMeshRunner가 (정전 주입된) CityLearn env를 step별로 증분 구동하고 per-step record를
  캐시한다. board는 CityLearn board와 호환되는 dataset/runtime/step/points/buildings +
  outage trace 블록(mesh_chesca 패널이 그대로 렌더)을 받는다.

모델 코드(ForecasterMPC / MPCBattery / MPCAgent / 메시 에이전트들 / OutageRiskAgent /
MASMPCAgent / enable_outages)는 노트북에서 인라인해 왔으며, board 구동에 필요한 최소한만
유지했다(주석/마크다운 제외, 동작 동일).
"""

from __future__ import annotations

import math
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# mesh_chesca와 동일한 시나리오 레지스트리를 단일 소스로 공유(상수만 import; citylearn 미적재).
from app.services.mesh_chesca_runtime import SCENARIOS as _ALL_SCENARIOS


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CITYLEARN_ROOT = PROJECT_ROOT / "CityLearn_old_system"
DATASET_ID = "citylearn_challenge_2022_phase_all"
DATASET_PATH = CITYLEARN_ROOT / "data" / "datasets" / DATASET_ID
SCHEMA_PATH = DATASET_PATH / "schema.json"

# 이 런타임이 구동하는 board 시나리오 id (mesh_chesca SCENARIOS에도 등록되어 있음).
SCENARIO_ID = "outage_mpc_mesh"

# 정전 시나리오 주입 파라미터 (노트북 §7과 동일: 저녁 피크, 동일 시드 → 공정 비교).
OUTAGE_KW = dict(saifi=80.0, caidi=180.0, start_hours=(17, 18, 19, 20), seed=0)


class AgentMeshUnavailable(RuntimeError):
    """Raised when the optional OpenSynCity (CityLearn_old_system) runtime cannot init."""


# ════════════════════════════════════════════════════════════════════════
# 노트북 인라인 모델 (research/agent_mesh.ipynb) — 동작 동일, 주석 축약
# ════════════════════════════════════════════════════════════════════════


@dataclass
class MPCConfig:
    horizon: int = 8
    carbon_weight: float = 1.0
    ramp_weight: float = 0.3
    soc_min: float = 0.0
    soc_max: float = 1.0


class ForecasterMPC:
    """건물별 순부하/요금/탄소를 '시간대 평균'으로 예측 (과거 정보만 → 미래 누설 없음)."""

    def __init__(self, n_buildings: int, horizon: int) -> None:
        self.n = n_buildings
        self.H = horizon
        self.net_hod = [[[] for _ in range(24)] for _ in range(n_buildings)]
        self.price_hod = [[] for _ in range(24)]
        self.carbon_hod = [[] for _ in range(24)]
        self.last_net = np.zeros(n_buildings)
        self.last_price = 0.0
        self.last_carbon = 0.0
        self.price_pred: List[float] = []

    def update(self, hour, load, solar, price, carbon, price_pred) -> None:
        h = int(hour) % 24
        net = np.asarray(load, dtype=float) - np.asarray(solar, dtype=float)
        for b in range(self.n):
            self.net_hod[b][h].append(float(net[b]))
            if len(self.net_hod[b][h]) > 60:
                self.net_hod[b][h] = self.net_hod[b][h][-60:]
        self.price_hod[h].append(float(price))
        self.carbon_hod[h].append(float(carbon))
        if len(self.price_hod[h]) > 60:
            self.price_hod[h] = self.price_hod[h][-60:]
            self.carbon_hod[h] = self.carbon_hod[h][-60:]
        self.last_net = net
        self.last_price = float(price)
        self.last_carbon = float(carbon)
        self.price_pred = [float(x) for x in price_pred]

    def net_forecast(self, b: int, hour) -> np.ndarray:
        out = [float(self.last_net[b])]
        for k in range(1, self.H):
            vals = self.net_hod[b][(int(hour) + k) % 24]
            out.append(float(np.mean(vals)) if vals else float(self.last_net[b]))
        return np.asarray(out)

    def price_forecast(self, hour) -> np.ndarray:
        out = [self.last_price]
        for k in range(1, self.H):
            if k <= len(self.price_pred):
                out.append(self.price_pred[k - 1])
            else:
                vals = self.price_hod[(int(hour) + k) % 24]
                out.append(float(np.mean(vals)) if vals else self.last_price)
        return np.asarray(out)

    def carbon_forecast(self, hour) -> np.ndarray:
        out = [self.last_carbon]
        for k in range(1, self.H):
            vals = self.carbon_hod[(int(hour) + k) % 24]
            out.append(float(np.mean(vals)) if vals else self.last_carbon)
        return np.asarray(out)


class MPCBattery:
    """건물 배터리 H시간 스케줄을 선형계획(LP)으로 최적화 → 첫 행동만 실행(receding horizon)."""

    def __init__(self, capacity, nominal_power, horizon=8, soc_min=0.0, soc_max=1.0,
                 carbon_weight=1.0, ramp_weight=0.3, wear_weight=0.001, reserve_penalty=20.0) -> None:
        self.capacity = float(capacity)
        self.nominal = float(nominal_power)
        self.H = int(horizon)
        self.soc_min = soc_min
        self.soc_max = soc_max
        self.carbon_weight = carbon_weight
        self.ramp_weight = ramp_weight
        self.wear_weight = wear_weight
        self.reserve_penalty = reserve_penalty
        self.ratio = self.nominal / max(self.capacity, 1e-6)

    def decide(self, soc, base_net, price, carbon, coupling=None, reserve_floor=0.0) -> float:
        actions, _ = self.solve(soc, base_net, price, carbon, coupling, reserve_floor)
        return float(actions[0])

    def solve(self, soc, base_net, price, carbon, coupling=None, reserve_floor=0.0):
        from scipy.optimize import linprog

        H = self.H
        na, nimp, nramp = H, H, H - 1
        use_reserve = reserve_floor > 1e-9
        nshort = H if use_reserve else 0
        N = na + nimp + nramp + nshort
        ia, iimp, iramp = 0, na, na + nimp
        ishort = na + nimp + nramp
        pi = np.zeros(H) if coupling is None else np.asarray(coupling, dtype=float)

        c = np.zeros(N)
        for t in range(H):
            c[iimp + t] = float(price[t]) + self.carbon_weight * float(carbon[t])
            c[ia + t] = float(pi[t]) * self.nominal
        for t in range(nramp):
            c[iramp + t] = self.ramp_weight
        for t in range(nshort):
            c[ishort + t] = self.reserve_penalty

        A: List[np.ndarray] = []
        b: List[float] = []

        def row(coeffs: Dict[int, float], rhs: float) -> None:
            r = np.zeros(N)
            for k, v in coeffs.items():
                r[k] = v
            A.append(r)
            b.append(rhs)

        for t in range(H):
            row({ia + t: self.nominal, iimp + t: -1.0}, -float(base_net[t]))
        for t in range(1, H):
            dbase = float(base_net[t] - base_net[t - 1])
            row({ia + t: self.nominal, ia + (t - 1): -self.nominal, iramp + (t - 1): -1.0}, -dbase)
            row({ia + t: -self.nominal, ia + (t - 1): self.nominal, iramp + (t - 1): -1.0}, dbase)
        for t in range(H):
            row({ia + k: self.ratio for k in range(t + 1)}, self.soc_max - soc)
            row({ia + k: -self.ratio for k in range(t + 1)}, soc - self.soc_min)
        if use_reserve:
            for t in range(H):
                r = {ia + k: -self.ratio for k in range(t + 1)}
                r[ishort + t] = -1.0
                row(r, soc - reserve_floor)

        bounds = [(-1.0, 1.0)] * na + [(0.0, None)] * nimp + [(0.0, None)] * nramp + [(0.0, None)] * nshort

        try:
            res = linprog(c, A_ub=np.asarray(A), b_ub=np.asarray(b), bounds=bounds, method="highs")
            if res.success:
                actions = np.clip(res.x[ia:ia + H], -1.0, 1.0)
                nets = np.asarray(base_net) + actions * self.nominal
                return actions, nets
        except Exception:
            pass
        return np.zeros(H), np.asarray(base_net, dtype=float)


class MPCAgent:
    """Phase 1 — 각 건물 LP를 풀어 행동 결정 (정전 대응 없는 기본형)."""

    def __init__(self, env: Any, config: Optional[MPCConfig] = None) -> None:
        self.env = env
        self.cfg = config or MPCConfig()
        self.n = len(env.buildings)
        on = env.observation_names[0]
        self._ix_load = [i for i, nm in enumerate(on) if nm == "non_shiftable_load"]
        self._ix_solar = [i for i, nm in enumerate(on) if nm == "solar_generation"]
        self._ix_soc = [i for i, nm in enumerate(on) if nm == "electrical_storage_soc"]
        self._ix_hour = on.index("hour") if "hour" in on else None
        self._ix_price = on.index("electricity_pricing") if "electricity_pricing" in on else None
        self._ix_carbon = on.index("carbon_intensity") if "carbon_intensity" in on else None
        self._ix_price_pred = [
            on.index(f"electricity_pricing_predicted_{k}")
            if f"electricity_pricing_predicted_{k}" in on else None
            for k in (1, 2, 3)
        ]
        self.capacity = np.array([b.electrical_storage.capacity for b in env.buildings], dtype=float)
        self.nominal = np.array(
            [float(getattr(b.electrical_storage, "nominal_power", 5.0)) for b in env.buildings]
        )
        self.controllers = [
            MPCBattery(
                self.capacity[b], self.nominal[b], horizon=self.cfg.horizon,
                soc_min=self.cfg.soc_min, soc_max=self.cfg.soc_max,
                carbon_weight=self.cfg.carbon_weight, ramp_weight=self.cfg.ramp_weight,
            )
            for b in range(self.n)
        ]
        self.fc = ForecasterMPC(self.n, self.cfg.horizon)
        self._step = 0

    def predict(self, observations, deterministic=None):
        obs = np.asarray(observations[0], dtype=float)
        hour = int(obs[self._ix_hour]) if self._ix_hour is not None else (self._step % 24) + 1
        load = np.array([obs[i] for i in self._ix_load])
        solar = np.array([obs[i] for i in self._ix_solar])
        soc = np.array([obs[i] for i in self._ix_soc])
        price = float(obs[self._ix_price]) if self._ix_price is not None else 0.0
        carbon = float(obs[self._ix_carbon]) if self._ix_carbon is not None else 0.0
        price_pred = [float(obs[i]) for i in self._ix_price_pred if i is not None]
        self.fc.update(hour, load, solar, price, carbon, price_pred)
        price_fc = self.fc.price_forecast(hour)
        carbon_fc = self.fc.carbon_forecast(hour)
        actions = np.zeros(self.n)
        for b in range(self.n):
            actions[b] = self.controllers[b].decide(float(soc[b]), self.fc.net_forecast(b, hour), price_fc, carbon_fc)
        self._step += 1
        return [np.clip(actions, -1.0, 1.0).astype(float).tolist()]


class Blackboard:
    def __init__(self) -> None:
        self.net_fc: Dict[int, Any] = {}
        self.states: Dict[int, Dict[str, float]] = {}
        self.price_fc = None
        self.carbon_fc = None
        self.roles: Dict[int, str] = {}
        self.lead: Dict[str, int] = {}
        self.reserve_floor = 0.0
        self.outage_risk = 0.0


class BuildingAgent:
    def __init__(self, b: int, controller: MPCBattery) -> None:
        self.b = b
        self.controller = controller
        self.last: Dict[str, Any] = {}

    def post(self, bb: Blackboard, soc, load, solar, net_fc) -> None:
        bb.states[self.b] = {"soc": float(soc), "load": float(load), "solar": float(solar)}
        bb.net_fc[self.b] = net_fc

    def act(self, bb: Blackboard) -> float:
        net = bb.net_fc[self.b]
        soc = bb.states[self.b]["soc"]
        actions, _ = self.controller.solve(soc, net, bb.price_fc, bb.carbon_fc, reserve_floor=bb.reserve_floor)
        a0 = float(actions[0])
        self.last = {"action": a0, "soc": soc, "net0": float(net[0]), "reserve": bb.reserve_floor}
        return a0

    def report(self, bb: Blackboard) -> Dict[str, Any]:
        role = bb.roles.get(self.b, "self_expert")
        a = self.last.get("action", 0.0)
        verb = "방전" if a < -1e-3 else ("충전" if a > 1e-3 else "유지")
        return {
            "agent": f"building_{self.b}", "role": role, "action": round(a, 3),
            "soc": round(self.last.get("soc", 0.0), 3),
            "reason": f"{verb} (a={a:+.2f}, SoC {self.last.get('soc', 0.0):.2f}, 예측 순부하 {self.last.get('net0', 0.0):.1f}kWh)",
        }


class SharedVarAgent:
    def __init__(self, name: str) -> None:
        self.name = name
        self.last = None

    def post(self, bb: Blackboard, forecast) -> None:
        if self.name == "price":
            bb.price_fc = forecast
        else:
            bb.carbon_fc = forecast
        self.last = forecast

    def report(self, bb: Blackboard) -> Dict[str, Any]:
        f = self.last
        nxt = [round(float(x), 3) for x in (f[1:4] if f is not None and len(f) > 3 else [])]
        return {
            "agent": f"{self.name}_agent", "role": f"{self.name}_lead",
            "forecast_next3": nxt, "reason": f"{self.name} 다음 3시간 예측 {nxt}",
        }


class RoleAssigner:
    def assign(self, bb: Blackboard, soc_high=0.6, soc_low=0.3) -> None:
        roles: Dict[int, str] = {}
        for b, st in bb.states.items():
            soc = st["soc"]
            net0 = float(bb.net_fc[b][0]) if b in bb.net_fc else 0.0
            if soc >= soc_high and net0 > 0:
                roles[b] = "relief_capable"
            elif net0 < 0 and soc < 0.9:
                roles[b] = "absorber"
            elif soc <= soc_low:
                roles[b] = "reserve_holder"
            else:
                roles[b] = "flexible"
        bb.roles = roles
        if bb.states:
            order = sorted(bb.states, key=lambda b: bb.states[b]["soc"])
            mid = order[len(order) // 2]
            bb.lead = {"price": mid, "carbon": mid}


class OutageRiskAgent:
    """정전을 예지해 reserve를 켜는 전문 에이전트 (관측만 사용 → causal)."""

    def __init__(self, horizon: int, max_reserve=0.4, anticipate=3, risk_threshold=0.5) -> None:
        self.H = horizon
        self.anticipate = int(min(anticipate, horizon))
        self.max_reserve = max_reserve
        self.risk_threshold = float(risk_threshold)
        self.hour_total = np.zeros(24)
        self.hour_outage = np.zeros(24)

    def observe(self, hour, outage_fraction) -> None:
        h = int(hour) % 24
        self.hour_total[h] += 1.0
        self.hour_outage[h] += float(outage_fraction)

    def _risky_hour(self, h) -> bool:
        freq = self.hour_outage / np.maximum(self.hour_total, 1.0)
        peak = float(freq.max())
        if peak <= 0.0:
            return False
        return float(freq[int(h) % 24]) >= self.risk_threshold * peak

    def assess(self, hour) -> Tuple[float, float]:
        risk = 1.0 if any(self._risky_hour(hour + k) for k in range(self.anticipate + 1)) else 0.0
        return risk, float(risk) * self.max_reserve

    def report(self, hour, risk, reserve_floor) -> Dict[str, Any]:
        return {
            "agent": "outage_risk_agent", "role": "outage_detector",
            "risk": round(risk, 3), "reserve_floor": round(reserve_floor, 3),
            "reason": (
                f"다가오는 {self.anticipate}시간 내 정전 위험 학습 → reserve {reserve_floor:.2f} 활성"
                if reserve_floor > 1e-3 else "정전 위험 낮음 → reserve 0 (= 평상시 MPC)"
            ),
        }


class MASMPCAgent(MPCAgent):
    """에이전트 소통 → 건물별 MPC. 정전 없으면 MPCAgent와 동일, 정전 시 reserve+긴급방전."""

    def __init__(self, env: Any, config: Optional[MPCConfig] = None, enable_reserve=True, max_reserve=0.4) -> None:
        super().__init__(env, config)
        self.building_agents = [BuildingAgent(b, self.controllers[b]) for b in range(self.n)]
        self.price_agent = SharedVarAgent("price")
        self.carbon_agent = SharedVarAgent("carbon")
        self.assigner = RoleAssigner()
        self.enable_reserve = enable_reserve
        self.risk_agent = OutageRiskAgent(self.cfg.horizon, max_reserve=max_reserve)
        self.reports: List[Dict[str, Any]] = []

    def predict(self, observations, deterministic=None):
        obs = np.asarray(observations[0], dtype=float)
        hour = int(obs[self._ix_hour]) if self._ix_hour is not None else (self._step % 24) + 1
        load = np.array([obs[i] for i in self._ix_load])
        solar = np.array([obs[i] for i in self._ix_solar])
        soc = np.array([obs[i] for i in self._ix_soc])
        price = float(obs[self._ix_price]) if self._ix_price is not None else 0.0
        carbon = float(obs[self._ix_carbon]) if self._ix_carbon is not None else 0.0
        price_pred = [float(obs[i]) for i in self._ix_price_pred if i is not None]
        self.fc.update(hour, load, solar, price, carbon, price_pred)

        bb = Blackboard()
        risk = reserve_floor = 0.0
        outage_now = [False] * self.n
        if self.enable_reserve:
            outage_now = [bool(getattr(b, "power_outage", False)) for b in self.env.buildings]
            self.risk_agent.observe(hour, float(np.mean([1.0 if o else 0.0 for o in outage_now])))
            risk, reserve_floor = self.risk_agent.assess(hour)
        bb.reserve_floor = reserve_floor
        bb.outage_risk = risk

        self.price_agent.post(bb, self.fc.price_forecast(hour))
        self.carbon_agent.post(bb, self.fc.carbon_forecast(hour))
        for b in range(self.n):
            self.building_agents[b].post(bb, float(soc[b]), float(load[b]), float(solar[b]), self.fc.net_forecast(b, hour))
        self.assigner.assign(bb)
        actions = np.array([self.building_agents[b].act(bb) for b in range(self.n)])

        n_deploy = 0
        for b in range(self.n):
            if outage_now[b]:
                nominal = max(self.controllers[b].nominal, 1e-6)
                need = float(load[b] - solar[b])
                actions[b] = float(np.clip(-need / nominal, -1.0, 1.0))
                self.building_agents[b].last["action"] = actions[b]
                n_deploy += 1

        # 자연어 소통 트레이스 (노트북 §6의 step_reports와 동일): 각 에이전트가 이번 step의
        # 판단 근거를 자연어로 게시한다. 긴급 방전 override 이후에 building report를 만들어
        # 실제 실행 행동이 반영되게 한다.
        step_reports = [
            self.risk_agent.report(hour, risk, reserve_floor),
            self.price_agent.report(bb),
            self.carbon_agent.report(bb),
        ]
        step_reports += [self.building_agents[b].report(bb) for b in range(self.n)]

        self._last_bb = bb
        self._last_outage_now = outage_now
        self.reports.append({
            "step": self._step, "hour": hour,
            "outage_risk": round(risk, 3), "reserve_floor": round(reserve_floor, 3),
            "emergency_deploy": n_deploy,
            "roles": dict(bb.roles),
            "reports": step_reports,
        })
        self._step += 1
        return [np.clip(actions, -1.0, 1.0).astype(float).tolist()]


def enable_outages(env: Any, saifi=80.0, caidi=180.0, start_hours=(17, 18, 19, 20), seed=0) -> Any:
    """모든 건물에 저녁 피크 정전을 주입. saifi=연 정전 횟수, caidi=평균 지속(분)."""
    from citylearn.power_outage import ReliabilityMetricsPowerOutage

    start_steps = [int(h) for h in start_hours]
    for i, b in enumerate(env.buildings):
        b.simulate_power_outage = True
        b.stochastic_power_outage = True
        m = ReliabilityMetricsPowerOutage(saifi=saifi, caidi=caidi, start_time_steps=start_steps)
        m.random_seed = seed + i
        b.stochastic_power_outage_model = m
    return env


# ════════════════════════════════════════════════════════════════════════
# Incremental board runner (mirrors SACRBCInferenceRunner)
# ════════════════════════════════════════════════════════════════════════

_ROLE_KO = {
    "relief_capable": "여유 방전 가능",
    "absorber": "잉여 흡수",
    "reserve_holder": "예비 보존",
    "flexible": "유연",
    "self_expert": "자기 전문",
}


class AgentMeshRunner:
    """OpenSynCity MASMPCAgent + 정전 주입 CityLearn env의 증분 rollout 캐시."""

    def __init__(self) -> None:
        if str(CITYLEARN_ROOT) not in sys.path:
            sys.path.insert(0, str(CITYLEARN_ROOT))

        try:
            from citylearn.citylearn import CityLearnEnv
        except Exception as exc:  # pragma: no cover - optional runtime deps
            raise AgentMeshUnavailable(str(exc)) from exc

        if not SCHEMA_PATH.exists():
            raise AgentMeshUnavailable(f"Missing dataset schema: {SCHEMA_PATH}")

        self._env = CityLearnEnv(str(SCHEMA_PATH), central_agent=True, random_seed=0)
        enable_outages(self._env, **OUTAGE_KW)
        self._observations, _ = self._env.reset()
        self._agent = MASMPCAgent(self._env, MPCConfig())
        self._building_names: List[str] = [b.name for b in self._env.buildings]
        self._records: List[Dict[str, Any]] = []
        self._terminated = False
        self._time_steps = int(getattr(self._env, "time_steps", 0) or 0)

    @property
    def total_steps(self) -> int:
        return self._time_steps

    @property
    def building_count(self) -> int:
        return len(self._building_names)

    def ensure_step(self, step: int) -> None:
        while len(self._records) <= step and not self._terminated:
            self._step_once()

    def get_record(self, step: int) -> Optional[Dict[str, Any]]:
        self.ensure_step(step)
        if 0 <= step < len(self._records):
            return self._records[step]
        return None

    def _step_once(self) -> None:
        step = len(self._records)
        actions = self._agent.predict(self._observations, deterministic=True)
        report = self._agent.reports[-1] if self._agent.reports else {}
        outage_now = list(getattr(self._agent, "_last_outage_now", [False] * self.building_count))
        next_observations, _, terminated, truncated, _ = self._env.step(actions)
        self._records.append(self._snapshot(step, actions, report, outage_now))
        self._observations = next_observations
        self._terminated = bool(terminated or truncated)

    def _snapshot(self, step: int, actions, report: Dict[str, Any], outage_now: List[bool]) -> Dict[str, Any]:
        roles: Dict[int, str] = report.get("roles", {}) or {}
        reserve_floor = float(report.get("reserve_floor", 0.0) or 0.0)
        outage_risk = float(report.get("outage_risk", 0.0) or 0.0)
        hour = int(report.get("hour", (step % 24) + 1))

        # 자연어 소통 트레이스: 각 에이전트의 한국어 역할 라벨 + outage 플래그를 덧붙여 board가
        # 그대로 표시할 수 있게 한다(노트북의 step_reports와 동일한 reason 문자열 보존).
        agent_reports: List[Dict[str, Any]] = []
        for rep in report.get("reports", []) or []:
            item = dict(rep)
            agent = str(item.get("agent", ""))
            if agent.startswith("building_"):
                try:
                    bidx = int(agent.split("_")[1])
                except (ValueError, IndexError):
                    bidx = -1
                item["role_ko"] = _ROLE_KO.get(item.get("role", ""), item.get("role", ""))
                item["outage"] = bool(outage_now[bidx]) if 0 <= bidx < len(outage_now) else False
            agent_reports.append(item)

        buildings: List[Dict[str, Any]] = []
        messages: List[Dict[str, Any]] = []
        district_baseline = 0.0
        district_mesh = 0.0
        for index, building in enumerate(self._env.buildings):
            load = self._series_value(building.non_shiftable_load, step)
            solar = abs(self._series_value(building.solar_generation, step))
            realized_net = self._series_value(building.net_electricity_consumption, step)
            soc = self._series_value(building.electrical_storage.soc, step)

            # baseline = 무제어 순부하(부하-태양광), agent_mesh = MPC mesh 적용 후 실제 그리드 수입.
            baseline_net = max(0.0, load - solar)
            mesh_net = max(0.0, realized_net)
            district_baseline += baseline_net
            district_mesh += mesh_net

            action_value = float(actions[0][index]) if actions and actions[0] and index < len(actions[0]) else 0.0
            role = roles.get(index, "flexible")
            is_outage = bool(outage_now[index]) if index < len(outage_now) else False
            intervention = is_outage or abs(action_value) > 0.02

            if is_outage:
                desc = f"정전 섬 고립 → 배터리 긴급 방전 ({load - solar:.2f} kWh 부담)"
            elif reserve_floor > 1e-3 and role == "reserve_holder":
                desc = f"정전 위험창 reserve {reserve_floor:.2f} 보존"
            elif abs(action_value) > 0.02:
                desc = f"[{_ROLE_KO.get(role, role)}] 배터리 {'충전' if action_value > 0 else '방전'} {action_value:+.2f}"
            else:
                desc = None

            buildings.append({
                "building_id": building.name,
                "baseline_net_load_kwh": round(baseline_net, 3),
                "agent_mesh_net_load_kwh": round(mesh_net, 3),
                "net_load_kwh": round(mesh_net, 3),
                "current_consumption_kwh": round(max(0.0, load), 3),
                "pv_generation_kwh": round(max(0.0, solar), 3),
                "battery_soc": round(min(1.0, max(0.0, soc)), 3),
                "battery_action": self._action_label(action_value),
                "battery_action_value": round(action_value, 4),
                "agent_intervention": intervention,
                "agent_action_description": desc,
            })
            messages.append({
                "step": step, "round_id": 0, "sender": index,
                "official_grid": round(baseline_net, 3), "proposed_grid": round(mesh_net, 3),
                "lower_grid": round(mesh_net, 3), "upper_grid": round(baseline_net, 3),
                "soc": round(min(1.0, max(0.0, soc)), 3),
                "district_proposal": round(district_mesh, 3), "district_target": round(reserve_floor, 3),
                "shadow_signal": round(outage_risk, 3), "recipient_count": self.building_count - 1,
                "role": role, "outage": is_outage,
            })

        changed = sum(1 for b in buildings if b["agent_intervention"])
        n_deploy = int(report.get("emergency_deploy", 0) or 0)
        negotiation = {
            "step": step, "hour": hour,
            "active_peers": self.building_count, "changed_peers": changed,
            "official_predicted_grid": round(district_baseline, 3),
            "negotiated_predicted_grid": round(district_mesh, 3),
            "predicted_grid_delta": round(district_mesh - district_baseline, 3),
            "district_target": round(reserve_floor, 3),
            "final_shadow_signal": round(outage_risk, 3),
            "logical_message_count": len(messages),
            "outage_risk": round(outage_risk, 3),
            "reserve_floor": round(reserve_floor, 3),
            "emergency_deploy": n_deploy,
        }

        return {
            "time_step": step,
            "baseline": round(district_baseline, 3),
            "agent_mesh": round(district_mesh, 3),
            "baseline_reward": round(-math.pow(max(district_baseline, 0.0), 1.05), 3),
            "agent_mesh_reward": round(-math.pow(max(district_mesh, 0.0), 1.05), 3),
            "buildings": buildings,
            "negotiation": negotiation,
            "messages": messages,
            "agent_reports": agent_reports,
        }

    @staticmethod
    def _series_value(series: Any, step: int) -> float:
        try:
            length = len(series)
        except TypeError:
            return 0.0
        if length == 0:
            return 0.0
        index = min(step, length - 1)
        try:
            return float(series[index])
        except (TypeError, ValueError, IndexError):
            return 0.0

    @staticmethod
    def _action_label(action: float) -> str:
        if action > 0.02:
            return "charging"
        if action < -0.02:
            return "discharging"
        return "idle"


# ── module-level cache (single runner; one dataset+scenario) ────────────

_runner: Optional[AgentMeshRunner] = None
_runner_error: Optional[str] = None
_lock = threading.RLock()


def _get_runner() -> Optional[AgentMeshRunner]:
    global _runner, _runner_error
    if _runner is not None or _runner_error is not None:
        return _runner
    with _lock:
        if _runner is not None or _runner_error is not None:
            return _runner
        try:
            _runner = AgentMeshRunner()
            _runner_error = None
        except Exception as exc:  # pragma: no cover - optional runtime deps
            _runner = None
            _runner_error = str(exc)
        return _runner


def runtime_status(*, connect: bool = False) -> Dict[str, Any]:
    runner = _get_runner() if connect else _runner
    return {
        "citylearn_root_detected": CITYLEARN_ROOT.exists(),
        "dataset": DATASET_ID,
        "scenario": SCENARIO_ID,
        "runner_connected": runner is not None,
        "total_steps": runner.total_steps if runner else None,
        "building_count": runner.building_count if runner else None,
        "runtime_error": _runner_error,
    }


def get_agent_mesh_board_snapshot(*, step: int, window: int = 72) -> Dict[str, Any]:
    """CityLearn-board 호환 snapshot + outage trace 블록(mesh_chesca 패널 재사용)."""
    runner = _get_runner()
    if runner is None:
        raise AgentMeshUnavailable(_runner_error or "OpenSynCity runtime unavailable")

    total = runner.total_steps or 1
    step = max(0, min(step, total - 1))
    window = max(1, min(window, 168))
    start = max(0, step - window + 1)

    with _lock:
        points: List[Dict[str, Any]] = []
        for point_step in range(start, step + 1):
            record = runner.get_record(point_step)
            if record is None:
                break
            points.append({
                "time_step": point_step,
                "time_label": f"T+{point_step}",
                "baseline": record["baseline"],
                "agent_mesh": record["agent_mesh"],
                "baseline_reward": record["baseline_reward"],
                "agent_mesh_reward": record["agent_mesh_reward"],
            })

        current = runner.get_record(step) or {"buildings": [], "negotiation": None, "messages": [], "agent_reports": []}
        buildings = [
            {
                **b,
                "history": [
                    {
                        "time_step": p["time_step"],
                        "net_load_kwh": p["agent_mesh"],
                        "baseline_net_load_kwh": p["baseline"],
                        "agent_mesh_net_load_kwh": p["agent_mesh"],
                        "pv_generation_kwh": 0.0,
                        "battery_soc": b.get("battery_soc", 0.0),
                    }
                    for p in points
                ],
            }
            for b in current.get("buildings", [])
        ]

    meta = _ALL_SCENARIOS.get(SCENARIO_ID, {})
    return {
        "dataset": {
            "id": DATASET_ID,
            "path": str(DATASET_PATH.relative_to(PROJECT_ROOT)),
            "total_steps": total,
            "central_agent": True,
            "active_actions": ["electrical_storage"],
        },
        "runtime": {
            "citylearn_data_connected": True,
            "citylearn_environment_step_connected": True,
            "baseline_runner_connected": True,
            "agent_mesh_action_api_connected": True,
            "source": "agent_mesh_real_runtime",
            "inference_runner_connected": True,
            **runtime_status(),
        },
        "step": step,
        "points": points,
        "buildings": buildings,
        "mesh_chesca": {
            "scenario": SCENARIO_ID,
            "scenario_label": meta.get("label", "OpenSynCity 정전 MPC Mesh"),
            "scenario_description": meta.get("description", ""),
            "available_scenarios": [
                {"id": sid, "label": m["label"], "description": m["description"]}
                for sid, m in _ALL_SCENARIOS.items()
            ],
            "negotiation": current.get("negotiation"),
            "messages": current.get("messages", []),
            "agent_reports": current.get("agent_reports", []),
        },
    }


__all__ = [
    "SCENARIO_ID",
    "DATASET_ID",
    "AgentMeshUnavailable",
    "get_agent_mesh_board_snapshot",
    "runtime_status",
]
