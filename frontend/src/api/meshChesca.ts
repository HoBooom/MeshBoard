import client from './client';
import type { CityLearnBoardBuilding, CityLearnBoardPoint } from './citylearn';

// MESH-CHESCA: 팀원 실험(Final_mesh1-main)의 실제 CHESCA-vs-Mesh 런타임을 구동하는 board API.
// 스냅샷은 CityLearn board와 호환되는 dataset/runtime/step/points/buildings + mesh_chesca trace 블록.

export type MeshChescaScenarioId =
  | 'chesca_official'
  | 'chesca_mesh'
  | 'reserve_contract_mesh'
  | 'commitment_mesh'
  | 'round_robin_commitment'
  // OpenSynCity 정전 MPC mesh: 별도 런타임(CityLearn 2022 phase_all + 정전 주입).
  | 'outage_mpc_mesh';

export interface MeshChescaScenario {
  id: MeshChescaScenarioId | string;
  label: string;
  description: string;
}

export interface MeshChescaFlexMessage {
  step: number;
  round_id: number;
  sender: number;
  official_grid: number;
  proposed_grid: number;
  lower_grid: number;
  upper_grid: number;
  soc: number;
  district_proposal: number;
  district_target: number;
  shadow_signal: number;
  recipient_count: number;
  // commitment 변형에서 추가되는 필드(optional)
  debt_soc?: number;
  budget_use_soc?: number;
  // outage_mpc_mesh 변형에서 추가되는 필드(optional)
  role?: string;
  outage?: boolean;
}

export interface MeshChescaNegotiation {
  step: number;
  hour: number;
  active_peers: number;
  changed_peers: number;
  official_predicted_grid: number;
  negotiated_predicted_grid: number;
  predicted_grid_delta: number;
  district_target: number;
  final_shadow_signal: number;
  logical_message_count: number;
  // commitment/round-robin 변형에서 추가되는 필드(optional)
  total_debt_soc?: number;
  debt_created_soc?: number;
  debt_repaid_soc?: number;
  // outage_mpc_mesh 변형에서 추가되는 필드(optional)
  outage_risk?: number;
  reserve_floor?: number;
  emergency_deploy?: number;
}

// outage_mpc_mesh 전용: 각 에이전트가 매 step 게시하는 자연어 판단 근거(노트북 step_reports).
export interface MeshChescaAgentReport {
  agent: string;
  role: string;
  reason: string;
  role_ko?: string;
  outage?: boolean;
  action?: number;
  soc?: number;
  risk?: number;
  reserve_floor?: number;
  forecast_next3?: number[];
  // 로컬 Qwen narration: llm=true면 LLM 생성 문장, reason_template은 원본 결정론적 문장.
  llm?: boolean;
  reason_template?: string;
}

export interface MeshChescaBoardSnapshot {
  dataset: { id: string; path: string; total_steps: number; central_agent: boolean; active_actions: string[] };
  runtime: Record<string, unknown> & {
    runner_connected?: boolean;
    runtime_error?: string | null;
    building_count?: number | null;
  };
  step: number;
  points: CityLearnBoardPoint[];
  buildings: CityLearnBoardBuilding[];
  mesh_chesca: {
    scenario: string;
    scenario_label: string;
    scenario_description: string;
    available_scenarios: MeshChescaScenario[];
    negotiation: MeshChescaNegotiation | null;
    messages: MeshChescaFlexMessage[];
    // outage_mpc_mesh 전용: 에이전트 자연어 소통 트레이스(다른 시나리오에선 비어 있음).
    agent_reports?: MeshChescaAgentReport[];
  };
}

export const meshChescaApi = {
  getScenarios: async (): Promise<{
    default_scenario: string;
    default_dataset: string;
    scenarios: MeshChescaScenario[];
    datasets: string[];
  }> => {
    const res = await client.get('/mesh-chesca/scenarios');
    return res.data;
  },

  getBoard: async (
    params: { step: number; scenario: string; dataset?: string; window?: number },
    opts?: { signal?: AbortSignal },
  ): Promise<MeshChescaBoardSnapshot> => {
    const res = await client.get<MeshChescaBoardSnapshot>('/mesh-chesca/board', {
      params,
      signal: opts?.signal,
    });
    return res.data;
  },

  // outage_mpc_mesh: board snapshot을 만들고 에이전트 자연어 소통을 메시지 피드로 발행한 뒤
  // snapshot을 반환(+ published_messages). 다른 시나리오는 발행 없이 snapshot만 돌려준다.
  publishBoard: async (
    params: { workspace_id: string; step: number; scenario: string; window?: number },
    opts?: { signal?: AbortSignal },
  ): Promise<MeshChescaBoardSnapshot & { published_messages?: number }> => {
    const res = await client.post<MeshChescaBoardSnapshot & { published_messages?: number }>(
      '/mesh-chesca/publish',
      null,
      { params, signal: opts?.signal },
    );
    return res.data;
  },
};
