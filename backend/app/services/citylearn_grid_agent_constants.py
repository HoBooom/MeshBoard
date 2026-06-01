"""Grid-Agent deterministic 엔진의 임계값/가중치 상수.

설계 근거: docs/architecture/01_paper_grid_agent.md §7 (Scoring 공식).
값 자체는 phase_all 데이터셋 통계와 도메인 직관에 기반한 초기값이며,
Phase 4의 KPI 측정 결과로 미세조정될 수 있다.
"""

from __future__ import annotations

# ── Violation thresholds ────────────────────────────────────────────

# District-level 피크/램핑 임계값 (kWh).
PEAK_THRESHOLD_KWH = 55.0
RAMP_THRESHOLD_KWH = 20.0

# Building SOC violation 경계. 더 안쪽(0.20/0.90)은 action 정책용 soft bound,
# 더 바깥(0.15/0.95)은 violation 판정용 hard bound로 분리한다.
SOC_HARD_LOWER = 0.15
SOC_HARD_UPPER = 0.95
SOC_SOFT_LOWER = 0.20
SOC_SOFT_UPPER = 0.90

# Fairness violation: plan 내 |action| 표준편차 임계값.
FAIRNESS_STD_THRESHOLD = 0.45

# ── Scoring weights ─────────────────────────────────────────────────

PEAK_PENALTY_WEIGHT = 2.0
RAMP_PENALTY_WEIGHT = 1.5
FAIRNESS_PENALTY_WEIGHT = 1.0
SOC_PENALTY_PER_BUILDING = 10.0

# ── Sandbox 적용 계수 ───────────────────────────────────────────────

# 하나의 action unit이 변경시키는 SOC 비율. action=1.0 → SOC +0.10.
SOC_DELTA_PER_UNIT_ACTION = 0.10

# Battery가 한 step에 흡수/방출 가능한 net load 영향 (kWh).
# action=±1.0 → net_load ±BATTERY_POWER_KWH.
BATTERY_POWER_KWH = 3.2

# ── Heuristic planner thresholds ────────────────────────────────────

# Building이 자체 peak 기여로 분류되는 net load 하한 (kWh).
BUILDING_HIGH_LOAD_KWH = 4.5

# Building이 충전 후보로 분류되기 위한 net load 상한 (kWh).
BUILDING_LOW_LOAD_KWH = 1.5

# 결정적 charge/discharge 기본 강도. 너무 공격적이면 SOC violation 유발.
HEURISTIC_DISCHARGE_ACTION = -0.4
HEURISTIC_CHARGE_ACTION = 0.3

# Heuristic confidence 기본값.
HEURISTIC_CONFIDENCE = 0.6

# ── Engine 운영 한도 ────────────────────────────────────────────────

DEFAULT_BOARD_WINDOW = 24
MAX_BUILDINGS = 17
