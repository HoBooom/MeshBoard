import client from './client';

export type CityLearnBaselineModel = 'basic_rbc' | 'optimized_rbc' | 'basic_battery_rbc' | 'sacrbc' | 'sac' | 'marlisa';
export type CityLearnAgentMeshMode =
  | 'not_configured'
  | 'demo_heuristic'
  | 'configured_agents'
  | 'grid_agent'
  | 'macro_mesh';

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
  baseline_action_value?: number;
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
    inference_runner_connected?: boolean;
    inference_error?: string | null;
    inference_model_name?: string;
    inference_model_class?: string;
  };
  step: number;
  points: CityLearnBoardPoint[];
  buildings: CityLearnBoardBuilding[];
}

// ── Grid-Agent (AM-api-001) ────────────────────────────────────────

export type CityLearnViolationType =
  | 'peak'
  | 'ramping'
  | 'soc'
  | 'mapping'
  | 'fairness'
  | 'invalid_action';

export type CityLearnActionMode = 'charge' | 'discharge' | 'hold';

export type CityLearnValidationStatus = 'approved' | 'rejected' | 'fallback';

export interface CityLearnViolation {
  type: CityLearnViolationType;
  building_id: string | null;
  severity: number;
  current_value: number;
  limit_value: number;
  description: string;
}

export interface CityLearnAction {
  building_id: string;
  action: number;
  mode: CityLearnActionMode;
  reason: string;
  expected_effect: string;
  confidence: number;
}

export interface CityLearnPlan {
  strategy_summary: string;
  actions: CityLearnAction[];
  risk_assessment: string;
}

export interface CityLearnValidationResult {
  approved: boolean;
  status: CityLearnValidationStatus;
  score_before: number;
  score_after: number;
  resolved_violations: CityLearnViolation[];
  remaining_violations: CityLearnViolation[];
  new_violations: CityLearnViolation[];
  clipped_actions: CityLearnAction[];
  forbidden_action_keys: string[];
  feedback: string;
}

export interface CityLearnControllableAsset {
  building_id: string;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  battery_soc: number;
  net_load_kwh: number;
  pv_generation_kwh: number;
  has_mapping: boolean;
}

export interface CityLearnTopologySummary {
  workspace_id: string;
  step: number;
  baseline_model: CityLearnBaselineModel;
  agent_mesh_mode: CityLearnAgentMeshMode;
  building_count: number;
  mapped_building_count: number;
  district_net_load_kwh: number;
  controllable_assets: CityLearnControllableAsset[];
}

export interface CityLearnPlanIteration {
  iteration: number;
  planner_kind: 'heuristic' | 'llm';
  planner_output: Record<string, unknown> | null;
  plan: CityLearnPlan;
  validation: CityLearnValidationResult;
  route_decision: string | null;
}

export interface CityLearnGridAgentAnalyzeResponse {
  run_id: string;
  requested_at: string;
  topology: CityLearnTopologySummary;
  initial_violations: CityLearnViolation[];
}

export interface CityLearnGridAgentPlanResponse {
  run_id: string;
  requested_at: string;
  topology: CityLearnTopologySummary;
  initial_violations: CityLearnViolation[];
  iterations: CityLearnPlanIteration[];
  final_plan: CityLearnPlan;
  validation: CityLearnValidationResult;
  operator_summary: string;
  forbidden_action_keys: string[];
}

// ── MACRO-Mesh (AM-macro-001/002/api-001) ─────────────────────────

export type CityLearnConflictType = 'over_discharge' | 'soc_risk' | 'fairness' | 'resource_contention';

export interface CityLearnBuildingProposal {
  building_id: string;
  round_index: number;
  proposed_action: number;
  confidence: number;
  rationale: string;
  expected_local_effect: string;
  kind: 'llm' | 'heuristic';
  raw_output_preview: string | null;
}

export interface CityLearnMeanFieldSummary {
  round_index: number;
  proposal_count: number;
  mean_action: number;
  stddev_action: number;
  mean_abs_action: number;
  discharge_count: number;
  charge_count: number;
  hold_count: number;
  critical_soc_ratio: number;
  expected_district_load_delta_kwh: number;
}

export interface CityLearnConflictReport {
  type: CityLearnConflictType;
  severity: number;
  building_ids: string[];
  description: string;
}

export interface CityLearnNegotiationRound {
  round_index: number;
  proposals: CityLearnBuildingProposal[];
  mean_field: CityLearnMeanFieldSummary;
  conflicts: CityLearnConflictReport[];
  feedback_by_building: Record<string, unknown>;
  elapsed_seconds: number;
}

export interface CityLearnMacroMeshNegotiateResponse {
  run_id: string;
  requested_at: string;
  topology: CityLearnTopologySummary;
  initial_violations: CityLearnViolation[];
  rounds: CityLearnNegotiationRound[];
  merged_plan: CityLearnPlan;
  plan_iteration_trace: CityLearnPlanIteration[];
  validation: CityLearnValidationResult;
  operator_summary: string;
  forbidden_action_keys: string[];
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

  runGridAgentPlan: async (params: {
    workspace_id: string;
    step: number;
    baseline_model: CityLearnBaselineModel;
    agent_mesh_mode: CityLearnAgentMeshMode;
    window?: number;
    max_iterations?: number;
    use_llm_planner?: boolean;
    forbidden_action_keys?: string[];
  }, opts?: { signal?: AbortSignal }): Promise<CityLearnGridAgentPlanResponse> => {
    const res = await client.post<CityLearnGridAgentPlanResponse>(
      '/citylearn/grid-agent/plan',
      params,
      { signal: opts?.signal },
    );
    return res.data;
  },

  runMacroMeshNegotiate: async (params: {
    workspace_id: string;
    step: number;
    baseline_model: CityLearnBaselineModel;
    agent_mesh_mode: CityLearnAgentMeshMode;
    window?: number;
    max_rounds?: number;
    use_llm_proposers?: boolean;
  }, opts?: { signal?: AbortSignal }): Promise<CityLearnMacroMeshNegotiateResponse> => {
    const res = await client.post<CityLearnMacroMeshNegotiateResponse>(
      '/citylearn/macro-mesh/negotiate',
      params,
      { signal: opts?.signal },
    );
    return res.data;
  },
};
