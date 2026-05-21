import client from './client';

export type CityLearnBaselineModel = 'basic_rbc' | 'optimized_rbc' | 'basic_battery_rbc' | 'sacrbc' | 'sac' | 'marlisa';
export type CityLearnAgentMeshMode = 'not_configured' | 'demo_heuristic' | 'configured_agents';

export interface CityLearnBoardPoint {
  time_step: number;
  time_label: string;
  baseline: number;
  agent_mesh: number;
  baseline_reward: number;
  agent_mesh_reward: number;
}

export interface CityLearnBoardBuilding {
  building_id: string;
  baseline_net_load_kwh: number;
  agent_mesh_net_load_kwh: number;
  current_consumption_kwh: number;
  battery_soc: number;
  battery_action: 'charging' | 'discharging' | 'idle';
  pv_generation_kwh: number;
  agent_intervention: boolean;
  agent_action_description: string | null;
  net_load_kwh: number;
  history: Array<{
    time_step: number;
    net_load_kwh: number;
    baseline_net_load_kwh: number;
    agent_mesh_net_load_kwh: number;
    pv_generation_kwh: number;
    battery_soc: number;
  }>;
}

export interface CityLearnBoardSnapshot {
  dataset: {
    id: string;
    path: string;
    total_steps: number;
    central_agent: boolean;
    active_actions: string[];
  };
  runtime: {
    citylearn_data_connected: boolean;
    citylearn_environment_step_connected: boolean;
    baseline_runner_connected: boolean;
    agent_mesh_action_api_connected: boolean;
    source: string;
    inference_bundle_path?: string;
    inference_bundle_detected?: boolean;
    inference_model_name?: string;
    inference_model_class?: string;
  };
  step: number;
  points: CityLearnBoardPoint[];
  buildings: CityLearnBoardBuilding[];
}

export const citylearnApi = {
  getBoardSnapshot: async (params: {
    step: number;
    baseline_model: CityLearnBaselineModel;
    agent_mesh_mode: CityLearnAgentMeshMode;
    window?: number;
  }): Promise<CityLearnBoardSnapshot> => {
    const res = await client.get<CityLearnBoardSnapshot>('/citylearn/board', { params });
    return res.data;
  },
};
