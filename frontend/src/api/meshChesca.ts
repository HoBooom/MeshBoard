import client from './client';
import type { CityLearnBoardBuilding, CityLearnBoardPoint } from './citylearn';

// MESH-CHESCA: 팀원 실험(Final_mesh1-main)의 실제 CHESCA-vs-Mesh 런타임을 구동하는 board API.
// 스냅샷은 CityLearn board와 호환되는 dataset/runtime/step/points/buildings + mesh_chesca trace 블록.

export type MeshChescaScenarioId =
  | 'chesca_official'
  | 'chesca_mesh'
  | 'reserve_contract_mesh'
  | 'commitment_mesh'
  | 'round_robin_commitment';

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
};
