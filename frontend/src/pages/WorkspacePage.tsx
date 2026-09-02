import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Background,
  Connection,
  Controls,
  Edge,
  EdgeMouseHandler,
  MarkerType,
  MiniMap,
  Node,
  NodeChange,
  NodeMouseHandler,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import '@xyflow/react/dist/style.css';
import { agentsApi, AgentCreatePayload, ToolDescriptor } from '../api/agents';
import {
  CityLearnBoardSnapshot,
  CityLearnGridAgentPlanResponse,
  CityLearnMacroMeshNegotiateResponse,
  citylearnApi,
} from '../api/citylearn';
import { meshChescaApi, MeshChescaBoardSnapshot } from '../api/meshChesca';
import { AgentCard, getAgents } from '../api/marketplace';
import {
  Goal,
  PublishMessageResult,
  Workspace,
  WorkspaceAccessRequest,
  WorkspaceDetail,
  WorkspaceJoinable,
  WorkspaceMessage,
  workspacesApi,
} from '../api/workspaces';
import { useAuthStore } from '../stores/authStore';

const CATEGORIES = ['All', 'HR', 'IT', 'Sales', 'Security', 'Finance'];

type EnvironmentTemplate = {
  id: string;
  name: string;
  description?: string;
  status: 'available' | 'coming_soon';
  highlighted?: boolean;
	  metadata?: {
	    buildings: number;
	    time_steps: number;
	    interval: string;
	    dataset_year: number;
	    dataset_id?: string;
	    dataset_path?: string;
	    features: string[];
	  };
	};

type CityLearnBuildingNode = {
  id: string;
  battery_capacity: number;
  pv_power: number;
};

type CityLearnBuildingAssignment = {
  building_id: string;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  metadata?: Record<string, unknown>;
};

type CityLearnCentralControllerAgent = {
  agent_id: string;
  agent_name: string;
};

type CityLearnAgentBuildingMapping = {
  central_controller_agents: CityLearnCentralControllerAgent[];
  buildings: CityLearnBuildingAssignment[];
};

type TopologyGraphItem = {
  id: string;
  dbNodeId: string;
  refId: string;
  name: string;
  role: string;
  type: string;
  status: 'active' | 'processing' | 'idle' | 'error';
  messageCount: number;
  eventCount: number;
  version: string;
  tools: string[];
  visibility: string;
  nodeType: 'user' | 'agent';
  incoming: number;
  outgoing: number;
  canEditTopology: boolean;
  buildingId?: string;
};

type WorkspaceMode = 'messaging' | 'map' | 'board';

type CityLearnSimulationStatus = 'idle' | 'running' | 'paused' | 'completed';

type CityLearnTickRate = {
  label: string;
  realSecondsPerStep: number;
};

type CityLearnSimulationState = {
  step: number;
  status: CityLearnSimulationStatus;
  tickRate: CityLearnTickRate;
  // grid_agent mode 전용 추적 필드. 다른 mode에서는 사용되지 않는다.
  lastGridAgentRun: CityLearnGridAgentPlanResponse | null;
  pendingGridAgentStep: number | null;
  gridAgentError: string | null;
  forbiddenActionKeys: string[];
  // macro_mesh mode 전용 추적 필드 (AM-macro-ui-001)
  lastMacroMeshRun: CityLearnMacroMeshNegotiateResponse | null;
  pendingMacroMeshStep: number | null;
  macroMeshError: string | null;
};

type CityLearnPowerPoint = {
  time_step: number;
  time_label: string;
  baseline: number;
  agent_mesh: number;
  baseline_reward: number;
  agent_mesh_reward: number;
};

type CityLearnMetric = {
  id: string;
  label: string;
  unit: string;
  baseline: number;
  agentMesh: number;
  improvement: number;
  improvementLabel: string;
  tone: 'blue' | 'green' | 'yellow' | 'red';
};

type CityLearnBatteryAction = 'charging' | 'discharging' | 'idle';

type CityLearnBaselineModel = 'basic_rbc' | 'optimized_rbc' | 'basic_battery_rbc' | 'sacrbc' | 'sac' | 'marlisa';

type CityLearnAgentMeshMode = 'not_configured' | 'demo_heuristic' | 'configured_agents' | 'deterministic' | 'llm_planner' | 'macro_mesh' | 'macro_mesh_v2';

type CityLearnBoardMetricView = 'power' | 'reward';

type CityLearnHeatmapCompareMode = 'baseline' | 'agent_mesh' | 'delta';

type CityLearnBuildingStatus = {
  building_id: string;
  baseline_net_load_kwh: number;
  agent_mesh_net_load_kwh: number;
  current_consumption_kwh: number;
  battery_soc: number;
  battery_action: CityLearnBatteryAction;
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
};

const ENVIRONMENT_TEMPLATES: EnvironmentTemplate[] = [
  {
    id: 'citylearn-2022',
    name: '도시 관리 (CityLearn - 2022 Data)',
    description: '17개 빌딩의 전력 소비, 태양광 발전, 배터리 충방전을 포함하는 스마트 시티 전력 관리 시뮬레이션',
    status: 'available',
    highlighted: true,
    metadata: {
	      buildings: 17,
	      time_steps: 8760,
	      interval: '1 hour',
	      dataset_year: 2022,
	      dataset_id: 'citylearn_challenge_2022_phase_all',
	      dataset_path: 'CityLearn_old_system/data/datasets/citylearn_challenge_2022_phase_all',
	      features: ['electrical_storage', 'pv'],
	    },
  },
  {
    id: 'mesh_chesca',
    name: '도시관리 mesh_chesca',
    description: 'CityLearn 2023 기반 CHESCA 컨트롤러 위에 P2P flex 협상(mesh)을 얹은 다건물 에너지 관리. 실제 CHESCA 런타임을 step별로 구동하며 official vs negotiated 부하와 peer 협상 trace를 보여줍니다.',
    status: 'available',
    highlighted: true,
    metadata: {
      buildings: 6,
      time_steps: 2208,
      interval: '1 hour',
      dataset_year: 2023,
      dataset_id: 'citylearn_challenge_2023_phase_3_1',
      dataset_path: 'Final_mesh1-main/CHESCA-main/data/schemas/citylearn_challenge_2023_phase_3_1',
      features: ['electrical_storage', 'pv', 'dhw_storage', 'cooling_device', 'mesh_negotiation'],
    },
  },
  { id: 'smart-factory', name: '스마트 팩토리', status: 'coming_soon' },
  { id: 'logistics-center', name: '물류센터', status: 'coming_soon' },
  { id: 'energy-grid', name: '에너지 그리드', status: 'coming_soon' },
];

const MESH_CHESCA_TEMPLATE_ID = 'mesh_chesca';
const MESH_CHESCA_DATASET = 'citylearn_challenge_2023_phase_3_1';
const MESH_CHESCA_SCENARIO_FALLBACK: Array<{ id: string; label: string; description: string }> = [
  { id: 'chesca_official', label: 'CHESCA Official (baseline)', description: '공식 CHESCA, mesh 협상 없음' },
  { id: 'chesca_mesh', label: 'CHESCA + Mesh', description: 'peer flex 협상' },
  { id: 'reserve_contract_mesh', label: 'Reserve Contract Mesh', description: 'outage reserve 보존 협상' },
  { id: 'commitment_mesh', label: 'Commitment Mesh', description: '과방전 debt/budget ledger' },
  { id: 'round_robin_commitment', label: 'Round-Robin Coordinator', description: 'planner 소유권 회전' },
  { id: 'outage_mpc_mesh', label: 'OpenSynCity 정전 MPC Mesh', description: '정전 회복력 MPC mesh (CityLearn 2022 + 정전 주입)' },
];

const CITYLEARN_DATASET_ID = 'citylearn_challenge_2022_phase_all';
const CITYLEARN_DATASET_PATH = 'CityLearn_old_system/data/datasets/citylearn_challenge_2022_phase_all';
const CITYLEARN_TOTAL_STEPS = 8760;
const CITYLEARN_START_DATE = new Date('2022-01-01T00:00:00');
const CITYLEARN_TICK_RATES: CityLearnTickRate[] = [
  { label: '0.2x', realSecondsPerStep: 5 },
  { label: '0.5x', realSecondsPerStep: 2 },
  { label: '1x', realSecondsPerStep: 1 },
  { label: '2x', realSecondsPerStep: 0.5 },
  { label: '5x', realSecondsPerStep: 0.2 },
  { label: '10x', realSecondsPerStep: 0.1 },
];
const CITYLEARN_DEFAULT_TICK_RATE = CITYLEARN_TICK_RATES[2];

const CITYLEARN_BASELINE_MODELS: Array<{
  id: CityLearnBaselineModel;
  label: string;
  status: 'demo' | 'not_connected';
  description: string;
  peakMitigation: number;
}> = [
  {
    id: 'basic_rbc',
    label: 'BasicRBC',
    status: 'demo',
    description: '시간 기반 충방전 rule baseline. 현재 Board의 기본 비교 기준입니다.',
    peakMitigation: 0,
  },
  {
    id: 'optimized_rbc',
    label: 'OptimizedRBC',
    status: 'demo',
    description: '구간별 방전 강도를 더 세분화한 rule baseline 시나리오입니다.',
    peakMitigation: 0.05,
  },
  {
    id: 'basic_battery_rbc',
    label: 'BasicBatteryRBC',
    status: 'demo',
    description: 'PV 활용 시간대 충전에 더 가까운 rule baseline 시나리오입니다.',
    peakMitigation: 0.04,
  },
  {
    id: 'sacrbc',
    label: 'SACRBC checkpoint',
    status: 'demo',
    description: 'best_inference_bundle.pt artifact가 확인된 SACRBC 모델입니다. 현재 Board API는 artifact 연결 상태를 표시하고, env step 추론은 다음 단계에서 붙입니다.',
    peakMitigation: 0.09,
  },
  {
    id: 'sac',
    label: 'SAC',
    status: 'not_connected',
    description: 'CityLearn SAC 코드는 존재하지만 현재 Board runtime에는 연결되어 있지 않습니다.',
    peakMitigation: 0.09,
  },
  {
    id: 'marlisa',
    label: 'MARLISA',
    status: 'not_connected',
    description: 'CityLearn MARLISA 코드는 존재하지만 현재 Board runtime에는 연결되어 있지 않습니다.',
    peakMitigation: 0.12,
  },
];

const CITYLEARN_AGENT_MESH_MODES: Array<{
  id: CityLearnAgentMeshMode;
  label: string;
  status: 'demo' | 'needs_setup';
  description: string;
  peakMitigation: number;
}> = [
  {
    id: 'not_configured',
    label: 'Not configured',
    status: 'needs_setup',
    description: '워크스페이스에 자체 Agent-Mesh 실행 정책이 아직 설정되지 않았습니다. Board는 참고용 preview를 표시합니다.',
    peakMitigation: 0.02,
  },
  {
    id: 'demo_heuristic',
    label: 'Demo heuristic',
    status: 'demo',
    description: 'Coordinator/Guard/Building Agent 구조를 흉내낸 deterministic preview입니다.',
    peakMitigation: 0.18,
  },
  {
    id: 'configured_agents',
    label: 'Configured agents',
    status: 'needs_setup',
    description: '할당된 building agents를 기준으로 보여주는 모드입니다. 실제 action API는 아직 연결되어 있지 않습니다.',
    peakMitigation: 0.13,
  },
  {
    id: 'deterministic',
    label: 'Deterministic (규칙 기반, LLM 없음)',
    status: 'demo',
    description: 'Play 시 매 step마다 백엔드 Grid-Agent plan API를 LLM 없이 호출합니다(결정적 규칙). 응답이 빠르고 재현 가능합니다. 한 step의 응답이 끝나야 다음 step으로 진행합니다.',
    peakMitigation: 0.16,
  },
  {
    id: 'llm_planner',
    label: 'LLM Planner (City Grid Coordinator)',
    status: 'demo',
    description: 'Play 시 매 step마다 City Grid Coordinator LLM이 plan을 제안하고, 검증 실패 시 forbidden_action_keys를 누적하며 최대 3회 재계획합니다. LLM 응답 시간이 한 step의 소요시간이 되므로 tick rate(1x/2x/5x)는 비활성화됩니다.',
    peakMitigation: 0.18,
  },
  {
    id: 'macro_mesh',
    label: 'MACRO-Mesh (분산 협상, round 1/2)',
    status: 'demo',
    description: 'Play 시 매 step마다 17개 Building Battery Agent가 병렬로 proposal을 발의하고 (asyncio.gather), Coordinator가 mean_field/conflict를 산출해 round 2 재제안을 유도합니다. 메시지 피드에 라운드별 trace가 누적됩니다.',
    peakMitigation: 0.20,
  },
  {
    id: 'macro_mesh_v2',
    label: 'MACRO-Mesh v2 (rollout + Introspector)',
    status: 'demo',
    description: 'MACRO-Mesh에 논문(MACRO-LLM)의 CoProposer rollout 검증과 Introspector(LLM semantic-gradient 자기반성)를 복원한 버전입니다. 협상 결과를 k-step rollout으로 검증해 최선 후보를 채택하고, step 간 전략을 누적해 다음 협상에 주입합니다(빌딩 수 증가·돌발상황에서 v1 대비 조정 안정성↑).',
    peakMitigation: 0.22,
  },
];

// grid_agent / macro_mesh mode timeout. Sonnet 4.6으로 17 building 병렬 협상이 ~4분.
// backend LLM_INVOKE_TIMEOUT_SECONDS(360s)와 동일. timeout 도달 시 simulation paused.
const GRID_AGENT_STEP_TIMEOUT_MS = 360_000;

const CITYLEARN_BUILDING_NODES: CityLearnBuildingNode[] = [
  { id: 'Building_1', battery_capacity: 6.4, pv_power: 12.0 },
  { id: 'Building_2', battery_capacity: 6.4, pv_power: 4.0 },
  { id: 'Building_3', battery_capacity: 6.4, pv_power: 4.0 },
  { id: 'Building_4', battery_capacity: 6.4, pv_power: 8.0 },
  { id: 'Building_5', battery_capacity: 6.4, pv_power: 10.0 },
  { id: 'Building_6', battery_capacity: 6.4, pv_power: 4.0 },
  { id: 'Building_7', battery_capacity: 6.4, pv_power: 9.0 },
  { id: 'Building_8', battery_capacity: 6.4, pv_power: 4.0 },
  { id: 'Building_9', battery_capacity: 6.4, pv_power: 4.0 },
  { id: 'Building_10', battery_capacity: 6.4, pv_power: 6.0 },
  { id: 'Building_11', battery_capacity: 6.4, pv_power: 5.0 },
  { id: 'Building_12', battery_capacity: 6.4, pv_power: 8.0 },
  { id: 'Building_13', battery_capacity: 6.4, pv_power: 5.0 },
  { id: 'Building_14', battery_capacity: 6.4, pv_power: 4.0 },
  { id: 'Building_15', battery_capacity: 6.4, pv_power: 7.0 },
  { id: 'Building_16', battery_capacity: 6.4, pv_power: 4.0 },
  { id: 'Building_17', battery_capacity: 6.4, pv_power: 4.0 },
];

function getCityLearnAgentBuildingMapping(metadata: Record<string, unknown> | undefined): CityLearnAgentBuildingMapping | null {
  const rawMapping = metadata?.agent_building_mapping;
  if (!rawMapping || typeof rawMapping !== 'object' || Array.isArray(rawMapping)) return null;

  const mapping = rawMapping as Record<string, unknown>;
  const rawBuildings = Array.isArray(mapping.buildings) ? mapping.buildings : [];
  const rawCentralControllerAgents = Array.isArray(mapping.central_controller_agents)
    ? mapping.central_controller_agents
    : [];

  const buildings = rawBuildings.flatMap((rawBuilding): CityLearnBuildingAssignment[] => {
    if (!rawBuilding || typeof rawBuilding !== 'object' || Array.isArray(rawBuilding)) return [];
    const building = rawBuilding as Record<string, unknown>;
    if (typeof building.building_id !== 'string') return [];
    return [{
      building_id: building.building_id,
      assigned_agent_id: typeof building.assigned_agent_id === 'string' ? building.assigned_agent_id : null,
      assigned_agent_name: typeof building.assigned_agent_name === 'string' ? building.assigned_agent_name : null,
      metadata: building.metadata && typeof building.metadata === 'object' && !Array.isArray(building.metadata)
        ? building.metadata as Record<string, unknown>
        : undefined,
    }];
  });

  const centralControllerAgents = rawCentralControllerAgents.flatMap((rawAgent): CityLearnCentralControllerAgent[] => {
    if (!rawAgent || typeof rawAgent !== 'object' || Array.isArray(rawAgent)) return [];
    const agent = rawAgent as Record<string, unknown>;
    if (typeof agent.agent_id !== 'string') return [];
    return [{
      agent_id: agent.agent_id,
      agent_name: typeof agent.agent_name === 'string' ? agent.agent_name : agent.agent_id,
    }];
  });

  return { buildings, central_controller_agents: centralControllerAgents };
}

function cityLearnBuildingLabel(buildingId: string): string {
  return buildingId.replace('_', ' ');
}

function workspaceTemplateId(metadata: Record<string, unknown> | undefined): string | null {
  if (typeof metadata?.template_id === 'string') return metadata.template_id;
  const environmentTemplate = metadata?.environment_template;
  if (
    environmentTemplate &&
    typeof environmentTemplate === 'object' &&
    !Array.isArray(environmentTemplate) &&
    typeof (environmentTemplate as Record<string, unknown>).id === 'string'
  ) {
    return (environmentTemplate as Record<string, unknown>).id as string;
  }
  return null;
}

function isCityLearnWorkspace(metadata: Record<string, unknown> | undefined): boolean {
  return workspaceTemplateId(metadata) === 'citylearn-2022';
}

function isMeshChescaWorkspace(metadata: Record<string, unknown> | undefined): boolean {
  return workspaceTemplateId(metadata) === MESH_CHESCA_TEMPLATE_ID;
}

// 두 템플릿 모두 도시관리 board UI를 사용한다.
function isCityManagementWorkspace(metadata: Record<string, unknown> | undefined): boolean {
  return isCityLearnWorkspace(metadata) || isMeshChescaWorkspace(metadata);
}

function cityLearnBaseLoad(timeStep: number): number {
  const hour = timeStep % 24;
  const day = Math.floor(timeStep / 24);
  const daytimeSolarRelief = hour >= 10 && hour <= 15 ? -5.5 : 0;
  const eveningPeak = hour >= 17 && hour <= 21 ? 13.5 : 0;
  const morningRamp = hour >= 7 && hour <= 10 ? 6.5 : 0;
  const nightReduction = hour <= 5 ? -7.5 : 0;
  const weeklyVariation = Math.sin((day % 7) / 7 * Math.PI * 2) * 2.4;
  const deterministicNoise = Math.sin(timeStep * 1.73) * 1.6 + Math.cos(timeStep * 0.37) * 0.9;
  return Math.max(
    18,
    38 + daytimeSolarRelief + eveningPeak + morningRamp + nightReduction + weeklyVariation + deterministicNoise
  );
}

function cityLearnPowerPoint(
  timeStep: number,
  baselineModel: CityLearnBaselineModel = 'basic_rbc',
  agentMeshMode: CityLearnAgentMeshMode = 'not_configured'
): CityLearnPowerPoint {
  const hour = timeStep % 24;
  const baselineConfig = CITYLEARN_BASELINE_MODELS.find((model) => model.id === baselineModel) || CITYLEARN_BASELINE_MODELS[0];
  const meshConfig = CITYLEARN_AGENT_MESH_MODES.find((mode) => mode.id === agentMeshMode) || CITYLEARN_AGENT_MESH_MODES[0];
  const baseLoad = cityLearnBaseLoad(timeStep);
  const baselinePeakWindow = hour >= 16 && hour <= 22 ? baselineConfig.peakMitigation : baselineConfig.peakMitigation * 0.5;
  const baseline = Math.max(14, baseLoad * (1 - baselinePeakWindow) - Math.cos(timeStep * 0.51) * baselineConfig.peakMitigation * 2);
  const meshPeakWindow = hour >= 16 && hour <= 22 ? meshConfig.peakMitigation : hour >= 11 && hour <= 15 ? meshConfig.peakMitigation * 0.45 : meshConfig.peakMitigation * 0.55;
  const agentMesh = Math.max(13, baseLoad * (1 - meshPeakWindow) - Math.cos(timeStep * 0.91) * 0.8);
  const baselineReward = -Math.pow(Math.max(baseline, 0), 1.05);
  const agentMeshReward = -Math.pow(Math.max(agentMesh, 0), 1.05);

  return {
    time_step: timeStep,
    time_label: `T+${timeStep}`,
    baseline: Number(baseline.toFixed(2)),
    agent_mesh: Number(agentMesh.toFixed(2)),
    baseline_reward: Number(baselineReward.toFixed(2)),
    agent_mesh_reward: Number(agentMeshReward.toFixed(2)),
  };
}

function buildCityLearnPowerWindow(
  currentStep: number,
  baselineModel: CityLearnBaselineModel,
  agentMeshMode: CityLearnAgentMeshMode
): CityLearnPowerPoint[] {
  const start = Math.max(0, currentStep - 71);
  return Array.from({ length: currentStep - start + 1 }, (_, index) =>
    cityLearnPowerPoint(start + index, baselineModel, agentMeshMode)
  );
}

function sumSeries(data: CityLearnPowerPoint[], key: 'baseline' | 'agent_mesh' | 'baseline_reward' | 'agent_mesh_reward'): number {
  return data.reduce((total, point) => total + point[key], 0);
}

function improvementPercent(baseline: number, agentMesh: number): number {
  if (baseline <= 0) return 0;
  return ((baseline - agentMesh) / baseline) * 100;
}

function cityLearnMetrics(data: CityLearnPowerPoint[]): CityLearnMetric[] {
  const totalBaseline = sumSeries(data, 'baseline');
  const totalAgentMesh = sumSeries(data, 'agent_mesh');
  const costRate = 0.18;
  const carbonRate = 0.42;
  const baselinePeak = Math.max(...data.map((point) => point.baseline));
  const meshPeak = Math.max(...data.map((point) => point.agent_mesh));
  const totalBaselineReward = sumSeries(data, 'baseline_reward');
  const totalAgentMeshReward = sumSeries(data, 'agent_mesh_reward');
  const rewardImprovement = ((totalAgentMeshReward - totalBaselineReward) / Math.max(Math.abs(totalBaselineReward), 1)) * 100;

  return [
    {
      id: 'total_consumption',
      label: '총 전력 소비량',
      unit: 'kWh',
      baseline: totalBaseline,
      agentMesh: totalAgentMesh,
      improvement: improvementPercent(totalBaseline, totalAgentMesh),
      improvementLabel: '% 절감',
      tone: 'blue',
    },
    {
      id: 'total_cost',
      label: '전력 비용',
      unit: '$',
      baseline: totalBaseline * costRate,
      agentMesh: totalAgentMesh * costRate,
      improvement: improvementPercent(totalBaseline, totalAgentMesh),
      improvementLabel: '% 절감',
      tone: 'green',
    },
    {
      id: 'carbon_emission',
      label: '탄소 배출량',
      unit: 'kgCO2',
      baseline: totalBaseline * carbonRate,
      agentMesh: totalAgentMesh * carbonRate,
      improvement: improvementPercent(totalBaseline, totalAgentMesh),
      improvementLabel: '% 감소',
      tone: 'yellow',
    },
    {
      id: 'peak_reduction',
      label: '피크 부하 감소',
      unit: 'kW',
      baseline: baselinePeak,
      agentMesh: meshPeak,
      improvement: improvementPercent(baselinePeak, meshPeak),
      improvementLabel: '% 감소',
      tone: 'red',
    },
    {
      id: 'reward',
      label: '누적 Reward',
      unit: 'pts',
      baseline: totalBaselineReward,
      agentMesh: totalAgentMeshReward,
      improvement: rewardImprovement,
      improvementLabel: '% 개선',
      tone: 'green',
    },
  ];
}

function cityLearnBuildingStatus(
  building: CityLearnBuildingNode,
  index: number,
  timeStep: number,
  baselineModel: CityLearnBaselineModel,
  agentMeshMode: CityLearnAgentMeshMode,
  assignment?: CityLearnBuildingAssignment
): CityLearnBuildingStatus {
  const hour = timeStep % 24;
  const baselineConfig = CITYLEARN_BASELINE_MODELS.find((model) => model.id === baselineModel) || CITYLEARN_BASELINE_MODELS[0];
  const meshConfig = CITYLEARN_AGENT_MESH_MODES.find((mode) => mode.id === agentMeshMode) || CITYLEARN_AGENT_MESH_MODES[0];
  const baseLoad = 2.8 + ((index * 13) % 22) / 5;
  const morningRamp = hour >= 7 && hour <= 10 ? 1.1 : 0;
  const eveningPeak = hour >= 17 && hour <= 21 ? 2.2 : 0;
  const deterministicNoise = Math.sin((timeStep + index) * 0.83) * 0.45;
  const currentConsumption = Math.max(0.8, baseLoad + morningRamp + eveningPeak + deterministicNoise);
  const pvShape = hour >= 7 && hour <= 18 ? Math.sin(((hour - 7) / 11) * Math.PI) : 0;
  const pvGeneration = Math.max(0, building.pv_power * pvShape * (0.42 + ((index % 4) * 0.05)));
  const isChargingWindow = hour >= 10 && hour <= 15 && pvGeneration > currentConsumption * 0.45;
  const isDischargingWindow = hour >= 17 && hour <= 21;
  const batteryAction: CityLearnBatteryAction = isDischargingWindow ? 'discharging' : isChargingWindow ? 'charging' : 'idle';
  const socWave = Math.sin((timeStep / 24 + index * 0.31) * Math.PI * 2) * 0.14;
  const actionBias = batteryAction === 'charging' ? 0.14 : batteryAction === 'discharging' ? -0.1 : 0;
  const batterySoc = Math.min(0.94, Math.max(0.14, 0.54 + socWave + actionBias + ((index % 5) * 0.025)));
  const batteryEffect = batteryAction === 'charging' ? 0.75 : batteryAction === 'discharging' ? -1.25 : 0;
  const rawNetLoad = Math.max(0, currentConsumption - pvGeneration);
  const baselineReduction = (hour >= 16 && hour <= 22 ? baselineConfig.peakMitigation : baselineConfig.peakMitigation * 0.45);
  const meshReduction = (hour >= 16 && hour <= 22 ? meshConfig.peakMitigation : hour >= 10 && hour <= 15 ? meshConfig.peakMitigation * 0.35 : meshConfig.peakMitigation * 0.5);
  const baselineNetLoad = Math.max(0, rawNetLoad * (1 - baselineReduction));
  const meshNetLoad = Math.max(0, rawNetLoad * (1 - meshReduction) + batteryEffect);
  const netLoad = meshNetLoad;
  const agentIntervention = Boolean(assignment?.assigned_agent_id && (batteryAction !== 'idle' || netLoad >= 4.5));
  const history = Array.from({ length: 24 }, (_, historyIndex) => {
    const historyStep = Math.max(0, timeStep - (23 - historyIndex));
    const historyHour = historyStep % 24;
    const historyPvShape = historyHour >= 7 && historyHour <= 18 ? Math.sin(((historyHour - 7) / 11) * Math.PI) : 0;
    const historyPv = Math.max(0, building.pv_power * historyPvShape * (0.38 + ((index % 4) * 0.05)));
    const historyPeak = historyHour >= 17 && historyHour <= 21 ? 1.8 : historyHour >= 7 && historyHour <= 10 ? 0.9 : 0;
    const historyLoad = Math.max(0.8, baseLoad + historyPeak + Math.sin((historyStep + index) * 0.83) * 0.4);
    const historySoc = Math.min(0.94, Math.max(0.14, 0.54 + Math.sin((historyStep / 24 + index * 0.31) * Math.PI * 2) * 0.14));
    const historyRawNet = Math.max(0, historyLoad - historyPv);
    const historyBaseline = Math.max(0, historyRawNet * (1 - (historyHour >= 16 && historyHour <= 22 ? baselineConfig.peakMitigation : baselineConfig.peakMitigation * 0.45)));
    const historyMesh = Math.max(0, historyRawNet * (1 - (historyHour >= 16 && historyHour <= 22 ? meshConfig.peakMitigation : meshConfig.peakMitigation * 0.5)));

    return {
      time_step: historyStep,
      net_load_kwh: Number(historyMesh.toFixed(2)),
      baseline_net_load_kwh: Number(historyBaseline.toFixed(2)),
      agent_mesh_net_load_kwh: Number(historyMesh.toFixed(2)),
      pv_generation_kwh: Number(historyPv.toFixed(2)),
      battery_soc: Number(historySoc.toFixed(2)),
    };
  });

  return {
    building_id: building.id,
    baseline_net_load_kwh: Number(baselineNetLoad.toFixed(2)),
    agent_mesh_net_load_kwh: Number(meshNetLoad.toFixed(2)),
    current_consumption_kwh: Number(currentConsumption.toFixed(2)),
    battery_soc: Number(batterySoc.toFixed(2)),
    battery_action: batteryAction,
    pv_generation_kwh: Number(pvGeneration.toFixed(2)),
    agent_intervention: agentIntervention,
    agent_action_description: agentIntervention
      ? batteryAction === 'charging'
        ? 'PV surplus window: battery charge command active'
        : batteryAction === 'discharging'
          ? 'Peak window: battery discharge command active'
          : 'High local net load: monitoring threshold exceeded'
      : null,
    net_load_kwh: Number(netLoad.toFixed(2)),
    history,
  };
}

function cityLearnHeatmapColor(netLoadKwh: number): string {
  if (netLoadKwh < 2.2) return 'rgba(52, 199, 89, 0.18)';
  if (netLoadKwh < 4.8) return 'rgba(255, 214, 10, 0.24)';
  return 'rgba(255, 69, 58, 0.2)';
}

function cityLearnHeatmapValue(status: CityLearnBuildingStatus, mode: CityLearnHeatmapCompareMode): number {
  if (mode === 'baseline') return status.baseline_net_load_kwh;
  if (mode === 'agent_mesh') return status.agent_mesh_net_load_kwh;
  return status.baseline_net_load_kwh - status.agent_mesh_net_load_kwh;
}

function cityLearnHeatmapLabel(mode: CityLearnHeatmapCompareMode): string {
  if (mode === 'baseline') return 'Baseline';
  if (mode === 'agent_mesh') return 'Agent-Mesh';
  return 'Delta saved';
}

function cityLearnSimulationDateLabel(step: number): string {
  const current = new Date(CITYLEARN_START_DATE.getTime() + (step * 60 * 60 * 1000));
  const year = current.getFullYear();
  const month = String(current.getMonth() + 1).padStart(2, '0');
  const day = String(current.getDate()).padStart(2, '0');
  const hour = String(current.getHours()).padStart(2, '0');
  return `${year}-${month}-${day} ${hour}:00`;
}

function cityLearnProgressPercent(step: number): number {
  return Math.min(100, Math.max(0, (step / (CITYLEARN_TOTAL_STEPS - 1)) * 100));
}

type CityLearnMeshMessageItem = {
  id: string;
  sender: string;
  summary: string;
  meta: string;
  tone: 'blue' | 'green' | 'yellow';
};

type CityLearnBaselineWeightSignal = {
  id: string;
  label: string;
  values: number[];
};

function cityLearnMeshMessageItems(
  detail: WorkspaceDetail,
  mapping: CityLearnAgentBuildingMapping | null,
  step: number,
  latestPoint: CityLearnPowerPoint,
  meshLabel: string
): CityLearnMeshMessageItem[] {
  // 실제 메시지 페이지와 동일하게 전체 메시지를 시간순(오래된→최신)으로 표시한다.
  const realMessages = [...detail.messages]
    .sort((a, b) => new Date(a.sent_at).getTime() - new Date(b.sent_at).getTime())
    .map((message): CityLearnMeshMessageItem => ({
      id: message.message_id,
      sender: message.sender_name || message.sender_id,
      summary: bodyPreview(message.body_ref),
      meta: `${new Date(message.sent_at).toLocaleTimeString()} · ${message.priority}`,
      tone: message.queued ? 'yellow' : message.sender_type === 'agent' ? 'green' : 'blue',
    }));

  if (realMessages.length > 0) return realMessages;

  const assigned = mapping?.buildings.filter((building) => building.assigned_agent_id).slice(0, 3) || [];
  const fallback = assigned.map((building, index): CityLearnMeshMessageItem => ({
    id: `${building.building_id}-${step}`,
    sender: building.assigned_agent_name || `${cityLearnBuildingLabel(building.building_id)} Agent`,
    summary: `tick ${step}: ${meshLabel} target ${latestPoint.agent_mesh.toFixed(1)} kWh`,
    meta: `${building.building_id} · policy sync`,
    tone: index === 0 ? 'green' : 'blue',
  }));

  if (fallback.length > 0) return fallback;

  return [
    {
      id: `coordinator-${step}`,
      sender: 'City Grid Coordinator',
      summary: `tick ${step}: waiting for Agent-Mesh action API`,
      meta: `preview · target ${latestPoint.agent_mesh.toFixed(1)} kWh`,
      tone: 'yellow',
    },
    {
      id: `guard-${step}`,
      sender: 'Grid Guard',
      summary: 'checks peak, reward, and battery-only phase_all constraints',
      meta: 'monitor · no action API',
      tone: 'blue',
    },
  ];
}

function cityLearnBaselineWeightSignals(
  building: CityLearnBuildingStatus | undefined,
  latestPoint: CityLearnPowerPoint,
  step: number,
  runnerConnected: boolean
): CityLearnBaselineWeightSignal[] {
  const action = building?.baseline_action_value ?? (building?.battery_action === 'charging' ? 0.36 : building?.battery_action === 'discharging' ? -0.42 : 0);
  const soc = building?.battery_soc ?? 0;
  const pv = building?.pv_generation_kwh ?? 0;
  const load = building?.current_consumption_kwh ?? latestPoint.baseline;
  const seed = action * 3.7 + soc * 2.1 + pv * 0.013 + load * 0.17 + (runnerConnected ? 0.41 : 0.09);
  const vector = (offset: number, length = 16) => Array.from({ length }, (_, index) => {
    const wave = Math.sin(step * (0.17 + offset * 0.013) + index * 0.73 + seed + offset);
    const cross = Math.cos(step * 0.071 + index * 0.31 + action * 4.2 - offset);
    return Math.max(-1, Math.min(1, (wave * 0.72) + (cross * 0.28)));
  });

  return [
    {
      id: 'actor-l1',
      label: 'actor.layer1.weight[0:16]',
      values: vector(0.3),
    },
    {
      id: 'actor-l2',
      label: 'actor.layer2.weight[0:16]',
      values: vector(1.7),
    },
    {
      id: 'mean-head',
      label: 'mean_head.vector[0:16]',
      values: vector(3.1),
    },
    {
      id: 'log-std',
      label: 'log_std.vector[0:16]',
      values: vector(4.8),
    },
    {
      id: 'critic-q',
      label: 'critic.q_projection[0:16]',
      values: vector(6.2),
    },
  ];
}

function csvToList(text: string): string[] {
  return text.split(',').map((item) => item.trim()).filter(Boolean);
}

function bodyPreview(bodyRef: string): string {
  if (!bodyRef.startsWith('inline:json:')) return bodyRef;
  try {
    const parsed = JSON.parse(bodyRef.replace('inline:json:', ''));
    return parsed.message || parsed.question || JSON.stringify(parsed);
  } catch {
    return bodyRef;
  }
}

function mentionRangeAt(text: string, caret: number): { start: number; end: number; query: string } | null {
  const beforeCaret = text.slice(0, caret);
  const start = beforeCaret.lastIndexOf('@');
  if (start < 0) return null;
  const previous = start > 0 ? text[start - 1] : '';
  if (previous && !/\s/.test(previous)) return null;
  const query = beforeCaret.slice(start + 1);
  if (/[\s@]/.test(query)) return null;
  return { start, end: caret, query };
}

function mentionToken(displayName: string): string {
  return `@${displayName.trim().replace(/\s+/g, '_')}`;
}

function mentionKey(displayName: string): string {
  return displayName.trim().replace(/\s+/g, '_').toLowerCase();
}

function agentStatus(index: number): 'active' | 'processing' | 'idle' {
  if (index === 0) return 'active';
  if (index === 1) return 'processing';
  return 'idle';
}

function statusTone(status: 'active' | 'processing' | 'idle' | 'error'): string {
  if (status === 'active') return 'bg-[#34c759]';
  if (status === 'processing') return 'bg-[#ffd60a]';
  if (status === 'error') return 'bg-[#ff453a]';
  return 'bg-white/30';
}

function statusLabel(status: 'active' | 'processing' | 'idle' | 'error'): string {
  if (status === 'active') return 'active';
  if (status === 'processing') return 'processing';
  if (status === 'error') return 'error';
  return 'idle';
}

function topologyStatusTone(status: 'active' | 'processing' | 'idle' | 'error'): string {
  if (status === 'active') return '#34c759';
  if (status === 'processing') return '#ffd60a';
  if (status === 'error') return '#ff453a';
  return '#8e8e93';
}

function agentType(agentName: string): string {
  const normalized = agentName.toLowerCase();
  if (normalized.includes('inspect') || normalized.includes('검수')) return 'inspector';
  if (normalized.includes('plan') || normalized.includes('planner')) return 'planner';
  if (normalized.includes('coord') || normalized.includes('orchestrator')) return 'coordinator';
  if (normalized.includes('monitor') || normalized.includes('감시')) return 'monitor';
  if (normalized.includes('exec') || normalized.includes('실행')) return 'executor';
  return 'custom';
}

export default function WorkspacePage() {
  const { user } = useAuthStore();
  const navigate = useNavigate();
  const [view, setView] = useState<'list' | 'create' | 'detail'>('list');
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [detail, setDetail] = useState<WorkspaceDetail | null>(null);
  const [joinableWorkspaces, setJoinableWorkspaces] = useState<WorkspaceJoinable[]>([]);
  const [accessRequests, setAccessRequests] = useState<WorkspaceAccessRequest[]>([]);
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [toolCatalog, setToolCatalog] = useState<ToolDescriptor[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [joiningId, setJoiningId] = useState<string | null>(null);
  const [joinLoading, setJoinLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joinOpen, setJoinOpen] = useState(false);
  const [joinCode, setJoinCode] = useState('1234');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('All');
  const [wizardStep, setWizardStep] = useState(1);
  const [workspaceName, setWorkspaceName] = useState('');
  const [workspaceDescription, setWorkspaceDescription] = useState('');
  const [workspaceTags, setWorkspaceTags] = useState('');
  const [selectedEnvironmentTemplateId, setSelectedEnvironmentTemplateId] = useState<string | null>(null);
  const [buildingAgentAssignments, setBuildingAgentAssignments] = useState<Record<string, string>>({});
  const [centralControllerAgentIds, setCentralControllerAgentIds] = useState<string[]>([]);
  const [basket, setBasket] = useState<Record<string, { agent: AgentCard; quantity: number }>>({});
  const [subscriptionTargets, setSubscriptionTargets] = useState<Record<string, string[]>>({});
  const [subscriptionFilter, setSubscriptionFilter] = useState<'all' | 'user' | 'agent'>('all');
  const [selectedCreateEdgeId, setSelectedCreateEdgeId] = useState<string | null>(null);
  const [createNodePositions, setCreateNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const [createMapNodes, setCreateMapNodes, applyCreateMapNodeChanges] = useNodesState<Node>([]);
  const [createMapEdges, setCreateMapEdges, onCreateMapEdgesChange] = useEdgesState<Edge>([]);
  const [draftAgentName, setDraftAgentName] = useState('');
  const [draftAgentPurpose, setDraftAgentPurpose] = useState('');
  const [messageText, setMessageText] = useState('');
  const [mentionRange, setMentionRange] = useState<{ start: number; end: number; query: string } | null>(null);
  const [activeMentionIndex, setActiveMentionIndex] = useState(0);
  const [optimisticMessages, setOptimisticMessages] = useState<WorkspaceMessage[]>([]);
  // 메시지 페이지 "clean" 버튼: 현재까지의 메시지 message_id를 기록해 view에서 숨긴다(데모용,
  // 모드별 메시지가 섞여 보기 어려울 때 사용). 백엔드 삭제가 아니라 클라이언트 필터이며,
  // 이후 새로 생성되는 메시지(새 id)는 그대로 표시된다.
  const [clearedMessageIds, setClearedMessageIds] = useState<Set<string>>(new Set());
  const [typingAgentIds, setTypingAgentIds] = useState<string[]>([]);
  const [publishResult, setPublishResult] = useState<PublishMessageResult | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [expandedMessageId, setExpandedMessageId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorMode, setInspectorMode] = useState<'agent' | 'message' | 'logs'>('agent');
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('messaging');
  const [workspaceSidebarCollapsed, setWorkspaceSidebarCollapsed] = useState(false);
  const [selectedGoalId, setSelectedGoalId] = useState<string | null>(null);
  const [showGoalForm, setShowGoalForm] = useState(false);
  const [goalName, setGoalName] = useState('');
  const [goalDescription, setGoalDescription] = useState('');
  const [goalPriority, setGoalPriority] = useState<Goal['priority']>('medium');
  const [goalSuccessCriteria, setGoalSuccessCriteria] = useState('');
  const [goalParentId, setGoalParentId] = useState<string | null>(null);
  const [goalAssignedAgents, setGoalAssignedAgents] = useState<string[]>([]);
  const [mapFilter, setMapFilter] = useState<'all' | 'active' | 'processing' | 'idle' | 'error'>('all');
  const [selectedMapNodeId, setSelectedMapNodeId] = useState<string | null>(null);
  const [selectedMapEdgeId, setSelectedMapEdgeId] = useState<string | null>(null);
  const [mapNodes, setMapNodes, applyMapNodeChanges] = useNodesState<Node>([]);
  const [mapEdges, setMapEdges, onMapEdgesChange] = useEdgesState<Edge>([]);
  const [mapNodePositions, setMapNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const [topologySaving, setTopologySaving] = useState(false);
  const [pendingTopologyEdges, setPendingTopologyEdges] = useState<Array<{ edge_id: string; source_node_id: string; target_node_id: string; edge_type: 'subscription'; status: 'active'; created_at: string; updated_at: string }>>([]);
  const [removedTopologyEdgeIds, setRemovedTopologyEdgeIds] = useState<string[]>([]);
  const [agentToolDrafts, setAgentToolDrafts] = useState<Record<string, string[]>>({});
  const [toolSavingAgentId, setToolSavingAgentId] = useState<string | null>(null);
  const [cityLearnSimulation, setCityLearnSimulation] = useState<CityLearnSimulationState>({
    step: 0,
    status: 'idle',
    tickRate: CITYLEARN_DEFAULT_TICK_RATE,
    lastGridAgentRun: null,
    pendingGridAgentStep: null,
    gridAgentError: null,
    forbiddenActionKeys: [],
    lastMacroMeshRun: null,
    pendingMacroMeshStep: null,
    macroMeshError: null,
  });
  const [cityLearnBaselineModel, setCityLearnBaselineModel] = useState<CityLearnBaselineModel>('sacrbc');
  const [cityLearnAgentMeshMode, setCityLearnAgentMeshMode] = useState<CityLearnAgentMeshMode>('not_configured');
  // macro_mesh mode에서 building proposer를 LLM으로 돌릴지(use_llm_proposers) 토글. 기본 ON.
  // (grid 계열은 deterministic/llm_planner mode 자체로 LLM 사용 여부가 결정되므로 이 값을 쓰지 않는다.)
  const [cityLearnUseLLMPlanner, setCityLearnUseLLMPlanner] = useState(true);
  // mesh_chesca 템플릿 전용: 어떤 CHESCA 협상 시나리오로 board 런타임을 구동할지.
  const [meshChescaScenario, setMeshChescaScenario] = useState<string>('chesca_mesh');
  const messageFeedEndRef = useRef<HTMLDivElement | null>(null);
  const messageInputRef = useRef<HTMLTextAreaElement | null>(null);
  // grid_agent / macro_mesh async loop의 중복 dispatch 방지용. effect 의존성에 pending step을
  // 넣으면 setState가 effect를 재실행시켜 cleanup이 in-flight 요청을 cancel해버리므로(=self-cancel),
  // pending step은 deps에서 빼고 ref로 in-flight 여부를 추적한다.
  const gridLoopInFlight = useRef(false);
  const macroLoopInFlight = useRef(false);

  const roles = new Set(user?.roles || []);
  const canCreateWorkspace =
    roles.has('agent_owner') ||
    roles.has('agent_engineer') ||
    roles.has('trust_ops') ||
    roles.has('release_manager');
  const canGrantAccess =
    roles.has('trust_ops') || roles.has('release_manager') || roles.has('evaluator');
  const activeCityLearnWorkspace = Boolean(detail && isCityLearnWorkspace(detail.metadata_));
  const activeMeshChescaWorkspace = Boolean(detail && isMeshChescaWorkspace(detail.metadata_));
  const activeCityManagementWorkspace = activeCityLearnWorkspace || activeMeshChescaWorkspace;

  const basketItems = useMemo(() => Object.values(basket), [basket]);
  const selectedEnvironmentTemplate = useMemo(
    () => ENVIRONMENT_TEMPLATES.find((template) => template.id === selectedEnvironmentTemplateId) || null,
    [selectedEnvironmentTemplateId]
  );
  const basketAgentMap = useMemo(
    () => new Map(basketItems.map((item) => [item.agent.agent_id, item.agent])),
    [basketItems]
  );
  const mappedCityLearnBuildingCount = useMemo(
    () => CITYLEARN_BUILDING_NODES.filter((building) => basketAgentMap.has(buildingAgentAssignments[building.id])).length,
    [basketAgentMap, buildingAgentAssignments]
  );
  const unmappedCityLearnBuildingIds = useMemo(
    () => CITYLEARN_BUILDING_NODES
      .filter((building) => !basketAgentMap.has(buildingAgentAssignments[building.id]))
      .map((building) => building.id),
    [basketAgentMap, buildingAgentAssignments]
  );
  const selectedGoal = detail?.goals.find((goal) => goal.goal_id === selectedGoalId) || null;
  const topLevelGoals = detail?.goals.filter((goal) => !goal.parent_goal_id) || [];
  const workspaceMembers = detail?.nodes.filter((node) => node.node_type === 'user') || [];
  const activeMessages = useMemo(
    () => {
      const messages = [...(detail?.messages || []), ...optimisticMessages];
      return selectedGoal?.conversation_id
        ? messages.filter((message) => message.conversation_id === selectedGoal.conversation_id)
        : messages;
    },
    [detail?.messages, optimisticMessages, selectedGoal?.conversation_id]
  );
  // 메시지 페이지 렌더 전용: clean으로 숨긴 메시지를 제외. 맵/토폴로지(activeMessages)에는 영향 없음.
  const visibleMessages = useMemo(
    () => (clearedMessageIds.size === 0
      ? activeMessages
      : activeMessages.filter((message) => !clearedMessageIds.has(message.message_id))),
    [activeMessages, clearedMessageIds]
  );
  const cleanMessages = () => {
    setClearedMessageIds((prev) => {
      const next = new Set(prev);
      activeMessages.forEach((message) => next.add(message.message_id));
      return next;
    });
    setOptimisticMessages([]);
  };
  const selectedMapNode = mapNodes.find((node) => node.id === selectedMapNodeId);
  const selectedMapEdge = mapEdges.find((edge) => edge.id === selectedMapEdgeId);
  const topologyEdges = useMemo(
    () => [
      ...(detail?.edges || []).filter((edge) => !removedTopologyEdgeIds.includes(edge.edge_id)),
      ...pendingTopologyEdges,
    ],
    [detail?.edges, pendingTopologyEdges, removedTopologyEdgeIds]
  );
  const selectedSubscribableNodes = useMemo(
    () =>
      selectedMapNodeId
        ? detail?.nodes.filter((node) => node.node_id !== selectedMapNodeId) || []
        : [],
    [detail?.nodes, selectedMapNodeId]
  );
  const mentionCandidates = useMemo(() => {
    if (!detail || !mentionRange) return [];
    const query = mentionRange.query.toLowerCase();
    return detail.nodes
      .filter((node) => {
        if (node.node_type === 'user' && node.ref_id === user?.user_id) return false;
        const name = node.display_name.toLowerCase();
        return !query || name.includes(query) || node.node_type.includes(query);
      })
      .sort((a, b) => {
        if (a.node_type !== b.node_type) return a.node_type === 'user' ? -1 : 1;
        return a.display_name.localeCompare(b.display_name);
      })
      .slice(0, 8);
  }, [detail, mentionRange, user?.user_id]);
  const typingAgents = useMemo(
    () =>
      detail?.placements
        .filter((placement) => typingAgentIds.includes(placement.agent.agent_id))
        .map((placement) => placement.agent) || [],
    [detail?.placements, typingAgentIds]
  );

  const onMapNodesChange = (changes: NodeChange<Node>[]) => {
    applyMapNodeChanges(changes);
    setMapNodePositions((positions) => {
      let changed = false;
      const nextPositions = { ...positions };
      changes.forEach((change) => {
        if (change.type === 'position' && change.position) {
          nextPositions[change.id] = change.position;
          changed = true;
        }
      });
      return changed ? nextPositions : positions;
    });
  };

  const onCreateMapNodesChange = (changes: NodeChange<Node>[]) => {
    applyCreateMapNodeChanges(changes);
    setCreateNodePositions((positions) => {
      let changed = false;
      const nextPositions = { ...positions };
      changes.forEach((change) => {
        if (change.type === 'position' && change.position) {
          nextPositions[change.id] = change.position;
          changed = true;
        }
      });
      return changed ? nextPositions : positions;
    });
  };

  const loadList = async () => {
    setLoading(true);
    setError(null);
    try {
      const requestPromise = canGrantAccess
        ? workspacesApi.listAccessRequests()
        : Promise.resolve([]);
      const [workspaceList, requestList] = await Promise.all([
        workspacesApi.list(),
        requestPromise,
      ]);
      setWorkspaces(workspaceList);
      setAccessRequests(requestList);
    } catch (err) {
      console.error(err);
      setError('워크스페이스 목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const loadAgents = async () => {
    const marketplaceAgents = await getAgents(searchQuery, activeCategory);
    setAgents(marketplaceAgents);
  };

  const loadToolCatalog = async () => {
    try {
      setToolCatalog(await agentsApi.listTools());
    } catch (err) {
      console.error(err);
      setToolCatalog([]);
    }
  };

  const refreshWorkspaceDetail = useCallback(async () => {
    const workspaceId = detail?.workspace_id;
    if (!workspaceId) return;
    try {
      const fresh = await workspacesApi.get(workspaceId);
      setDetail(fresh);
    } catch (err) {
      console.warn('detail refresh failed after mesh publish', err);
    }
  }, [detail?.workspace_id]);

  const openJoinWorkspace = async () => {
    setJoinOpen(true);
    setJoinLoading(true);
    setJoinError(null);
    try {
      const data = await workspacesApi.listJoinable();
      setJoinableWorkspaces(data);
    } catch (err) {
      console.error(err);
      setJoinError('참여 가능한 워크스페이스 목록을 불러오지 못했습니다.');
    } finally {
      setJoinLoading(false);
    }
  };

  useEffect(() => {
    void loadList();
    void loadToolCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canGrantAccess]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadAgents();
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, activeCategory]);

  // 메시지 피드 자동 스크롤: 가장 최근 메시지가 항상 viewport에 보이도록.
  // - workspaceMode가 messaging으로 진입할 때
  // - 메시지/typing 변화 시
  // - useLayoutEffect 대신 useEffect 안에서 즉시 + 다음 frame까지 두 번 호출 (smooth scroll 보장 + 큰 리스트도 안정)
  useEffect(() => {
    if (view !== 'detail' || workspaceMode !== 'messaging') return;
    const scrollNow = () => {
      const el = messageFeedEndRef.current;
      if (!el) return;
      el.scrollIntoView({ block: 'end', behavior: 'auto' });
    };
    scrollNow();
    const raf = window.requestAnimationFrame(scrollNow);
    return () => window.cancelAnimationFrame(raf);
  }, [
    view,
    workspaceMode,
    detail?.messages.length,
    optimisticMessages.length,
    typingAgentIds.length,
  ]);

  useEffect(() => {
    if (view !== 'detail' || !activeCityManagementWorkspace || cityLearnSimulation.status !== 'running') return;
    // deterministic / llm_planner / macro_mesh mode는 별도 async loop(아래 useEffect)에서 step을 진행한다.
    if (
      cityLearnAgentMeshMode === 'deterministic'
      || cityLearnAgentMeshMode === 'llm_planner'
      || cityLearnAgentMeshMode === 'macro_mesh'
      || cityLearnAgentMeshMode === 'macro_mesh_v2'
    ) return;

    const timer = window.setInterval(() => {
      setCityLearnSimulation((current) => {
        if (current.status !== 'running') return current;
        if (current.step >= CITYLEARN_TOTAL_STEPS - 1) {
          return { ...current, status: 'completed' };
        }

        const nextStep = current.step + 1;
        return {
          ...current,
          step: nextStep,
          status: nextStep >= CITYLEARN_TOTAL_STEPS - 1 ? 'completed' : 'running',
        };
      });
    }, cityLearnSimulation.tickRate.realSecondsPerStep * 1000);

    return () => window.clearInterval(timer);
  }, [
    activeCityManagementWorkspace,
    cityLearnAgentMeshMode,
    cityLearnSimulation.status,
    cityLearnSimulation.tickRate.realSecondsPerStep,
    view,
  ]);

  // deterministic / llm_planner mode 전용 async loop.
  // - status='running' + mode가 위 둘 중 하나인 동안 매 step마다 POST /citylearn/grid-agent/plan 호출
  // - 응답 도착 후에만 setStep(+1)으로 직렬 진행 (setInterval 미사용)
  // - 타임아웃 또는 API 실패 시 simulation을 paused로 전환하고 에러 메시지 표시
  // - In-flight 동안 Coordinator/Guard agent를 typingAgentIds에 표시 → 메시지 view에 "응답 중" 애니메이션
  // - 응답 완료 후 workspace detail refresh → publish된 plan_result 메시지를 자동 표시
  // - 중복 dispatch는 gridLoopInFlight ref로 막는다. pending step을 deps에 넣으면 self-cancel 되므로 제외.
  useEffect(() => {
    if (view !== 'detail' || !activeCityLearnWorkspace || !detail) return;
    if (cityLearnAgentMeshMode !== 'deterministic' && cityLearnAgentMeshMode !== 'llm_planner') return;
    if (cityLearnSimulation.status !== 'running') return;
    if (gridLoopInFlight.current) return;

    const useLLM = cityLearnAgentMeshMode === 'llm_planner';
    gridLoopInFlight.current = true;
    let cancelled = false;
    // abort 시 실제 HTTP 요청도 끊어 백엔드가 in-flight LLM 호출을 더 진행하지 않도록 한다.
    const abortController = new AbortController();
    const requestStep = cityLearnSimulation.step;
    const workspaceId = detail.workspace_id;
    // Coordinator + Guard agent_id를 placements에서 찾아 typing indicator로 사용.
    const gridAgentAgentIds = detail.placements
      .filter((p) => p.agent.name === 'City Grid Coordinator' || p.agent.name === 'CityLearn Constraint Guard')
      .map((p) => p.agent.agent_id);

    setCityLearnSimulation((current) => ({
      ...current,
      pendingGridAgentStep: requestStep,
      gridAgentError: null,
    }));
    if (gridAgentAgentIds.length > 0) {
      setTypingAgentIds((prev) => Array.from(new Set([...prev, ...gridAgentAgentIds])));
    }

    const clearTyping = () => {
      if (gridAgentAgentIds.length > 0) {
        setTypingAgentIds((prev) => prev.filter((id) => !gridAgentAgentIds.includes(id)));
      }
    };

    const timeoutId = window.setTimeout(() => {
      if (cancelled) return;
      cancelled = true;
      abortController.abort();
      clearTyping();
      setCityLearnSimulation((current) => ({
        ...current,
        status: 'paused',
        pendingGridAgentStep: null,
        gridAgentError: `Grid-Agent plan API timeout (${Math.round(GRID_AGENT_STEP_TIMEOUT_MS / 1000)}s).`,
      }));
    }, GRID_AGENT_STEP_TIMEOUT_MS);

    citylearnApi.runGridAgentPlan({
      workspace_id: workspaceId,
      step: requestStep,
      baseline_model: cityLearnBaselineModel,
      agent_mesh_mode: 'grid_agent',
      window: 24,
      max_iterations: useLLM ? 3 : 1,
      use_llm_planner: useLLM,
      forbidden_action_keys: cityLearnSimulation.forbiddenActionKeys,
    }, { signal: abortController.signal })
      .then(async (response) => {
        window.clearTimeout(timeoutId);
        if (cancelled) return;
        // 새로 publish된 plan_result 메시지를 가져오기 위해 detail refresh.
        try {
          const fresh = await workspacesApi.get(workspaceId);
          if (!cancelled) setDetail(fresh);
        } catch (err) {
          console.warn('detail refresh failed after grid-agent plan', err);
        }
        if (cancelled) return;
        clearTyping();
        setCityLearnSimulation((current) => {
          if (current.status !== 'running') return current;
          const nextStep = current.step + 1;
          const reachedEnd = nextStep >= CITYLEARN_TOTAL_STEPS;
          return {
            ...current,
            step: reachedEnd ? current.step : nextStep,
            status: reachedEnd ? 'completed' : 'running',
            lastGridAgentRun: response,
            pendingGridAgentStep: null,
            gridAgentError: null,
            forbiddenActionKeys: response.forbidden_action_keys ?? current.forbiddenActionKeys,
          };
        });
      })
      .catch((error) => {
        window.clearTimeout(timeoutId);
        if (cancelled) return;
        console.error('grid-agent plan failed', error);
        clearTyping();
        const message = (error as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail?.message
          ?? (error as Error)?.message
          ?? 'Grid-Agent plan API 호출 실패';
        setCityLearnSimulation((current) => ({
          ...current,
          status: 'paused',
          pendingGridAgentStep: null,
          gridAgentError: String(message),
        }));
      });

    return () => {
      cancelled = true;
      gridLoopInFlight.current = false;
      abortController.abort();
      window.clearTimeout(timeoutId);
      clearTyping();
    };
  }, [
    activeCityLearnWorkspace,
    cityLearnAgentMeshMode,
    cityLearnBaselineModel,
    cityLearnSimulation.status,
    cityLearnSimulation.step,
    cityLearnSimulation.forbiddenActionKeys,
    detail,
    view,
  ]);

  // macro_mesh mode 전용 async loop (AM-macro-ui-001).
  // deterministic/llm_planner loop와 동일 패턴이지만 negotiate endpoint 호출 + Building Battery Agent 17명 + Coordinator를 typing.
  // 중복 dispatch는 macroLoopInFlight ref로 막는다(pending step을 deps에 넣으면 self-cancel 됨).
  useEffect(() => {
    if (view !== 'detail' || !activeCityLearnWorkspace || !detail) return;
    if (cityLearnAgentMeshMode !== 'macro_mesh' && cityLearnAgentMeshMode !== 'macro_mesh_v2') return;
    if (cityLearnSimulation.status !== 'running') return;
    if (macroLoopInFlight.current) return;

    macroLoopInFlight.current = true;
    let cancelled = false;
    const abortController = new AbortController();
    const requestStep = cityLearnSimulation.step;
    const workspaceId = detail.workspace_id;
    // Coordinator만 일반 typing 버블로 표시. 17 Building Battery Agent의 병렬 작동은
    // 메시지 피드의 전용 grid(아래 pendingMacroMeshStep 블록)에서 17개로 시각화한다.
    const macroAgentIds = detail.placements
      .filter((p) => p.agent.name === 'City Grid Coordinator')
      .map((p) => p.agent.agent_id);

    setCityLearnSimulation((current) => ({
      ...current,
      pendingMacroMeshStep: requestStep,
      macroMeshError: null,
    }));
    if (macroAgentIds.length > 0) {
      setTypingAgentIds((prev) => Array.from(new Set([...prev, ...macroAgentIds])));
    }
    const clearTyping = () => {
      if (macroAgentIds.length > 0) {
        setTypingAgentIds((prev) => prev.filter((id) => !macroAgentIds.includes(id)));
      }
    };

    const timeoutId = window.setTimeout(() => {
      if (cancelled) return;
      cancelled = true;
      abortController.abort();
      clearTyping();
      setCityLearnSimulation((current) => ({
        ...current,
        status: 'paused',
        pendingMacroMeshStep: null,
        macroMeshError: `MACRO-Mesh negotiate API timeout (${Math.round(GRID_AGENT_STEP_TIMEOUT_MS / 1000)}s).`,
      }));
    }, GRID_AGENT_STEP_TIMEOUT_MS);

    citylearnApi.runMacroMeshNegotiate({
      workspace_id: workspaceId,
      step: requestStep,
      baseline_model: cityLearnBaselineModel,
      agent_mesh_mode: cityLearnAgentMeshMode,
      window: 24,
      max_rounds: 2,
      use_llm_proposers: cityLearnUseLLMPlanner,
    }, { signal: abortController.signal })
      .then(async (response) => {
        window.clearTimeout(timeoutId);
        if (cancelled) return;
        try {
          const fresh = await workspacesApi.get(workspaceId);
          if (!cancelled) setDetail(fresh);
        } catch (err) {
          console.warn('detail refresh failed after macro-mesh negotiate', err);
        }
        if (cancelled) return;
        clearTyping();
        setCityLearnSimulation((current) => {
          if (current.status !== 'running') return current;
          const nextStep = current.step + 1;
          const reachedEnd = nextStep >= CITYLEARN_TOTAL_STEPS;
          return {
            ...current,
            step: reachedEnd ? current.step : nextStep,
            status: reachedEnd ? 'completed' : 'running',
            lastMacroMeshRun: response,
            pendingMacroMeshStep: null,
            macroMeshError: null,
          };
        });
      })
      .catch((error) => {
        window.clearTimeout(timeoutId);
        if (cancelled) return;
        console.error('macro-mesh negotiate failed', error);
        clearTyping();
        const message = (error as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail?.message
          ?? (error as Error)?.message
          ?? 'MACRO-Mesh negotiate API 호출 실패';
        setCityLearnSimulation((current) => ({
          ...current,
          status: 'paused',
          pendingMacroMeshStep: null,
          macroMeshError: String(message),
        }));
      });

    return () => {
      cancelled = true;
      macroLoopInFlight.current = false;
      abortController.abort();
      window.clearTimeout(timeoutId);
      clearTyping();
    };
  }, [
    activeCityLearnWorkspace,
    cityLearnAgentMeshMode,
    cityLearnBaselineModel,
    cityLearnUseLLMPlanner,
    cityLearnSimulation.status,
    cityLearnSimulation.step,
    detail,
    view,
  ]);

  useEffect(() => {
    setActiveMentionIndex((index) => Math.min(index, Math.max(mentionCandidates.length - 1, 0)));
  }, [mentionCandidates.length]);

  useEffect(() => {
    if (view !== 'create') return;
    const userNode = user?.user_id
      ? [{
          id: `user:${user.user_id}`,
          nodeType: 'user' as const,
          refId: user.user_id,
          name: user.name || '나',
          status: 'active' as const,
        }]
      : [];
    const agentNodes = basketItems.map((item) => ({
      id: `agent:${item.agent.agent_id}`,
      nodeType: 'agent' as const,
      refId: item.agent.agent_id,
      name: item.agent.name,
      status: 'idle' as const,
      version: item.agent.version,
      quantity: item.quantity,
    }));
    const graphItems = [...userNode, ...agentNodes];
    const columns = Math.max(3, Math.ceil(Math.sqrt(Math.max(graphItems.length, 1))));
    const nodes: Node[] = graphItems.map((item, index) => {
      const defaultPosition = {
        x: (index % columns) * 260,
        y: Math.floor(index / columns) * 165,
      };
      return {
        id: item.id,
        position: createNodePositions[item.id] || defaultPosition,
        sourcePosition: Position.Top,
        targetPosition: Position.Top,
        connectable: item.nodeType === 'agent',
        data: {
          nodeType: item.nodeType,
          refId: item.refId,
          displayName: item.name,
          status: item.status,
          label: (
            <div className={`min-w-[220px] rounded-[14px] border bg-white px-4 py-3 shadow-sm ${item.nodeType === 'user' ? 'border-[#0071e3]/25' : 'border-black/10'}`}>
              <div className="mb-2 flex items-center gap-2">
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${item.nodeType === 'user' ? 'bg-[#0071e3] text-white' : 'bg-black/[0.06] text-black/60'}`}>
                  {item.nodeType === 'user' ? 'U' : 'A'}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-[#1d1d1f]">{item.name}</span>
                  <span className="block text-[11px] uppercase tracking-[0.08em] text-black/38">{item.nodeType}</span>
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px] text-black/55">
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">
                  {item.nodeType === 'agent' ? `x${item.quantity}` : 'owner'}
                </span>
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">
                  {item.nodeType === 'agent' ? `v${item.version}` : item.status}
                </span>
              </div>
            </div>
          ),
        },
        style: {
          border: 'none',
          background: 'transparent',
          padding: 0,
          width: 220,
        },
      };
    });
    const nodeIds = new Set(nodes.map((node) => node.id));
    const edges: Edge[] = Object.entries(subscriptionTargets).flatMap(([sourceAgentId, targets]) =>
      targets.flatMap((targetKey) => {
        const source = `agent:${sourceAgentId}`;
        const target = targetKey;
        if (!nodeIds.has(source) || !nodeIds.has(target)) return [];
        return [{
          id: `create-edge:${sourceAgentId}:${targetKey}`,
          source,
          target,
          animated: true,
          label: 'subscription',
          markerEnd: { type: MarkerType.ArrowClosed, color: '#34c759' },
          data: { relation_type: 'subscription' },
          style: { stroke: '#34c759', strokeWidth: 2.2 },
          labelStyle: { fill: '#3a3a3c', fontSize: 11, fontWeight: 600 },
        } satisfies Edge];
      })
    );
    setCreateMapNodes(nodes);
    setCreateMapEdges(edges);
  }, [basketItems, createNodePositions, setCreateMapEdges, setCreateMapNodes, subscriptionTargets, user?.name, user?.user_id, view]);

  const openDetail = async (workspaceId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await workspacesApi.get(workspaceId);
      setDetail(data);
      setOptimisticMessages([]);
      setClearedMessageIds(new Set());
      setTypingAgentIds([]);
      setMapNodePositions({});
      setPendingTopologyEdges([]);
      setRemovedTopologyEdgeIds([]);
      setSelectedMapEdgeId(null);
      setSelectedMapNodeId(null);
      setWorkspaceMode('messaging');
      setView('detail');
    } catch (err) {
      console.error(err);
      setError('워크스페이스 상세를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const addAgent = (agent: AgentCard) => {
    setBasket((prev) => ({
      ...prev,
      [agent.agent_id]: {
        agent,
        quantity: (prev[agent.agent_id]?.quantity || 0) + 1,
      },
    }));
  };

  const setQuantity = (agentId: string, quantity: number) => {
    setBasket((prev) => {
      const current = prev[agentId];
      if (!current) return prev;
      if (quantity <= 0) {
        const next = { ...prev };
        delete next[agentId];
        setBuildingAgentAssignments((assignments) => {
          const cleaned = { ...assignments };
          Object.keys(cleaned).forEach((buildingId) => {
            if (cleaned[buildingId] === agentId) delete cleaned[buildingId];
          });
          return cleaned;
        });
        setCentralControllerAgentIds((agentIds) => agentIds.filter((currentAgentId) => currentAgentId !== agentId));
        setSubscriptionTargets((targets) => {
          const cleaned = { ...targets };
          delete cleaned[agentId];
          Object.keys(cleaned).forEach((sourceAgentId) => {
            cleaned[sourceAgentId] = cleaned[sourceAgentId].filter((targetKey) => targetKey !== `agent:${agentId}`);
          });
          return cleaned;
        });
        return next;
      }
      return { ...prev, [agentId]: { ...current, quantity } };
    });
  };

  const toggleSubscriptionTarget = (sourceAgentId: string, targetKey: string) => {
    setSubscriptionTargets((prev) => {
      const current = prev[sourceAgentId] || [];
      const nextTargets = current.includes(targetKey)
        ? current.filter((item) => item !== targetKey)
        : [...current, targetKey];
      return { ...prev, [sourceAgentId]: nextTargets };
    });
  };

  const createTopologyEdge = (sourceNodeId: string, targetNodeId: string) => {
    if (!sourceNodeId.startsWith('agent:') || sourceNodeId === targetNodeId) {
      setError('구독 관계는 agent 노드에서 다른 노드로만 만들 수 있습니다.');
      return;
    }
    const sourceAgentId = sourceNodeId.replace('agent:', '');
    setSubscriptionTargets((prev) => {
      const current = prev[sourceAgentId] || [];
      if (current.includes(targetNodeId)) return prev;
      return { ...prev, [sourceAgentId]: [...current, targetNodeId] };
    });
    setError(null);
  };

  const onCreateTopologyConnect = (connection: Connection) => {
    if (!connection.source || !connection.target) return;
    createTopologyEdge(connection.source, connection.target);
  };

  const onCreateTopologyEdgeClick: EdgeMouseHandler = (_, edge) => {
    setSelectedCreateEdgeId(edge.id);
  };

  const deleteSelectedCreateEdge = () => {
    if (!selectedCreateEdgeId) return;
    const edge = createMapEdges.find((item) => item.id === selectedCreateEdgeId);
    if (!edge || !edge.source.startsWith('agent:')) return;
    const sourceAgentId = edge.source.replace('agent:', '');
    setSubscriptionTargets((prev) => ({
      ...prev,
      [sourceAgentId]: (prev[sourceAgentId] || []).filter((targetKey) => targetKey !== edge.target),
    }));
    setSelectedCreateEdgeId(null);
  };

  const ensureAgentBasketForTopology = () => {
    if (basketItems.length > 0) return true;
    setError('토폴로지 구성을 위해 에이전트를 하나 이상 배치하세요.');
    setWizardStep(2);
    return false;
  };

  const createDraftAgent = async () => {
    if (!draftAgentName.trim()) return;
    const payload: AgentCreatePayload = {
      name: draftAgentName.trim(),
      version: '0.1.0',
      purpose: draftAgentPurpose.trim() || '워크스페이스 생성 흐름에서 작성된 초안 에이전트',
      status: 'DRAFT',
      visibility: 'PRIVATE',
      tools: [],
      metadata: { category: 'Draft' },
    };
    const created = await agentsApi.createAgent(payload);
    const card: AgentCard = {
      agent_id: created.agent_id,
      name: created.name,
      version: created.version,
      purpose: created.purpose || undefined,
      description: created.description || undefined,
      status: created.status,
      visibility: created.visibility,
      metadata_: created.metadata_,
      roles: created.roles,
      tools: created.tools,
      created_at: created.created_at,
    };
    addAgent(card);
    setDraftAgentName('');
    setDraftAgentPurpose('');
  };

  const validateAgentSubscriptions = () => {
    const agentsMissingSubscriptions = basketItems.filter(
      (item) => (subscriptionTargets[item.agent.agent_id] || []).length === 0
    );
    if (agentsMissingSubscriptions.length === 0) return true;
    setError(`구독 대상을 선택하지 않은 에이전트가 있습니다: ${agentsMissingSubscriptions.map((item) => item.agent.name).join(', ')}`);
    setWizardStep(3);
    return false;
  };

  const assignAgentToBuilding = (buildingId: string, agentId: string | null) => {
    setBuildingAgentAssignments((prev) => {
      const next = { ...prev };
      if (!agentId) {
        delete next[buildingId];
      } else if (basketAgentMap.has(agentId)) {
        next[buildingId] = agentId;
      }
      return next;
    });
    setError(null);
  };

  const toggleCentralControllerAgent = (agentId: string) => {
    if (!basketAgentMap.has(agentId)) return;
    setCentralControllerAgentIds((prev) =>
      prev.includes(agentId)
        ? prev.filter((currentAgentId) => currentAgentId !== agentId)
        : [...prev, agentId]
    );
    setError(null);
  };

  const onMappingAgentDragStart = (event: DragEvent<HTMLElement>, agentId: string) => {
    event.dataTransfer.setData('application/x-agent-id', agentId);
    event.dataTransfer.setData('text/plain', agentId);
    event.dataTransfer.effectAllowed = 'copy';
  };

  const agentIdFromDrop = (event: DragEvent<HTMLElement>) =>
    event.dataTransfer.getData('application/x-agent-id') || event.dataTransfer.getData('text/plain');

  const onBuildingMappingDrop = (event: DragEvent<HTMLDivElement>, buildingId: string) => {
    event.preventDefault();
    const agentId = agentIdFromDrop(event);
    if (agentId) assignAgentToBuilding(buildingId, agentId);
  };

  const onCentralControllerDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const agentId = agentIdFromDrop(event);
    if (agentId && basketAgentMap.has(agentId) && !centralControllerAgentIds.includes(agentId)) {
      setCentralControllerAgentIds((prev) => [...prev, agentId]);
      setError(null);
    }
  };

  const buildAgentBuildingMapping = () => {
    const assignedBuildings = CITYLEARN_BUILDING_NODES.map((building) => {
      const agentId = buildingAgentAssignments[building.id];
      const agent = agentId ? basketAgentMap.get(agentId) : undefined;
      return {
        building_id: building.id,
        assigned_agent_id: agent?.agent_id || null,
        assigned_agent_name: agent?.name || null,
        metadata: {
          battery_capacity: building.battery_capacity,
          pv_power: building.pv_power,
          pv_nominal_power: building.pv_power,
        },
      };
    });
    const centralControllerAgents = centralControllerAgentIds
      .map((agentId) => basketAgentMap.get(agentId))
      .filter((agent): agent is AgentCard => Boolean(agent))
      .map((agent) => ({
        agent_id: agent.agent_id,
        agent_name: agent.name,
      }));

    return {
      environment_template_id: 'citylearn-2022',
      assignment_mode: 'building_or_central',
      mapped_building_count: assignedBuildings.filter((building) => building.assigned_agent_id).length,
      unmapped_building_ids: assignedBuildings
        .filter((building) => !building.assigned_agent_id)
        .map((building) => building.building_id),
      central_controller_agents: centralControllerAgents,
      buildings: assignedBuildings,
    };
  };

  const buildAgentPlacements = () => {
    if (selectedEnvironmentTemplate?.id !== 'citylearn-2022') {
      return basketItems.map((item) => ({
        agent_id: item.agent.agent_id,
        quantity: item.quantity,
      }));
    }

    const mappedInstanceCounts = new Map<string, number>();
    CITYLEARN_BUILDING_NODES.forEach((building) => {
      const agentId = buildingAgentAssignments[building.id];
      if (agentId && basketAgentMap.has(agentId)) {
        mappedInstanceCounts.set(agentId, (mappedInstanceCounts.get(agentId) || 0) + 1);
      }
    });
    centralControllerAgentIds.forEach((agentId) => {
      if (basketAgentMap.has(agentId)) {
        mappedInstanceCounts.set(agentId, (mappedInstanceCounts.get(agentId) || 0) + 1);
      }
    });

    return basketItems.map((item) => ({
      agent_id: item.agent.agent_id,
      quantity: mappedInstanceCounts.get(item.agent.agent_id) || item.quantity,
    }));
  };

  const createWorkspace = async () => {
    if (!workspaceName.trim()) {
      setError('워크스페이스 이름을 입력하세요.');
      return;
    }
    if (!validateAgentSubscriptions()) return;
    if (!selectedEnvironmentTemplate || selectedEnvironmentTemplate.status !== 'available') {
      setError('환경 템플릿을 선택하세요.');
      setWizardStep(4);
      return;
    }
    setSaving(true);
    setError(null);
    const templateMetadata = selectedEnvironmentTemplate.metadata;
    try {
      const workspace = await workspacesApi.create({
        name: workspaceName.trim(),
        description: workspaceDescription.trim() || undefined,
        tags: csvToList(workspaceTags),
        metadata: {
          template_id: selectedEnvironmentTemplate.id,
	          dataset_year: templateMetadata?.dataset_year,
	          dataset_id: templateMetadata?.dataset_id,
	          dataset_path: templateMetadata?.dataset_path,
	          building_count: templateMetadata?.buildings,
	          environment_template: {
	            id: selectedEnvironmentTemplate.id,
	            name: selectedEnvironmentTemplate.name,
	            dataset_year: templateMetadata?.dataset_year,
	            dataset_id: templateMetadata?.dataset_id,
	            dataset_path: templateMetadata?.dataset_path,
	            building_count: templateMetadata?.buildings,
            time_steps: templateMetadata?.time_steps,
            interval: templateMetadata?.interval,
            features: templateMetadata?.features || [],
          },
          agent_building_mapping: selectedEnvironmentTemplate.id === 'citylearn-2022'
            ? buildAgentBuildingMapping()
            : undefined,
        },
        agent_placements: buildAgentPlacements(),
        agent_subscriptions: basketItems.flatMap((item) =>
          (subscriptionTargets[item.agent.agent_id] || []).map((targetKey) => {
            const [targetType, targetRefId] = targetKey.split(':');
            return {
              source_agent_id: item.agent.agent_id,
              target_node_type: targetType as 'user' | 'agent',
              target_ref_id: targetRefId,
            };
          })
        ),
      });
      await loadList();
      await openDetail(workspace.workspace_id);
    } catch (err) {
      console.error(err);
      setError('워크스페이스 생성 중 오류가 발생했습니다.');
    } finally {
      setSaving(false);
    }
  };

  const decideRequest = async (requestId: string, decision: 'approve' | 'reject') => {
    if (decision === 'approve') {
      await workspacesApi.approveAccessRequest(requestId);
    } else {
      await workspacesApi.rejectAccessRequest(requestId);
    }
    await loadList();
  };

  const joinWorkspace = async (workspace: WorkspaceJoinable) => {
    setJoiningId(workspace.workspace_id);
    setJoinError(null);
    try {
      const joined = await workspacesApi.join(workspace.workspace_id, joinCode);
      await loadList();
      setJoinOpen(false);
      setJoinableWorkspaces([]);
      await openDetail(joined.workspace_id);
    } catch (err) {
      console.error(err);
      setJoinError('참여 코드가 올바르지 않거나 참여할 수 없는 워크스페이스입니다.');
    } finally {
      setJoiningId(null);
    }
  };

  const routedAgentIdsForMessage = (text: string) => {
    if (!detail || !user?.user_id) return [];

    const mentionedTokens = Array.from(text.matchAll(/(?<!\S)@([^\s@]+)/g)).map((match) => match[1].toLowerCase());
    if (mentionedTokens.length > 0) {
      const agentIdByToken = new Map(
        detail.nodes
          .filter((node) => node.node_type === 'agent' && node.status !== 'error')
          .map((node) => [mentionKey(node.display_name), node.ref_id])
      );
      return mentionedTokens
        .map((token) => agentIdByToken.get(token))
        .filter((agentId): agentId is string => Boolean(agentId))
        .filter((agentId, index, agentIds) => agentIds.indexOf(agentId) === index);
    }

    const senderNode = detail.nodes.find(
      (node) => node.node_type === 'user' && node.ref_id === user.user_id
    );
    if (!senderNode) return [];
    const agentRefIdByNodeId = new Map(
      detail.nodes
        .filter((node) => node.node_type === 'agent')
        .map((node) => [node.node_id, node.ref_id])
    );
    return detail.edges
      .filter((edge) => edge.edge_type === 'subscription' && edge.status === 'active' && edge.target_node_id === senderNode.node_id)
      .map((edge) => agentRefIdByNodeId.get(edge.source_node_id))
      .filter((agentId): agentId is string => Boolean(agentId))
      .filter((agentId, index, agentIds) => agentIds.indexOf(agentId) === index);
  };

  const markRoutedAgentsProcessing = (text: string) => {
    if (!detail) return [];
    const routedAgentIds = routedAgentIdsForMessage(text);
    if (routedAgentIds.length === 0) return [];
    const routedAgentIdSet = new Set(routedAgentIds);
    setTypingAgentIds(routedAgentIds);
    setDetail({
      ...detail,
      nodes: detail.nodes.map((node) =>
        node.node_type === 'agent' && routedAgentIdSet.has(node.ref_id)
          ? { ...node, status: 'processing' }
          : node
      ),
    });
    return routedAgentIds;
  };

  const addOptimisticUserMessage = (text: string) => {
    if (!detail || !user?.user_id) return null;
    const messageId =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? `local-${crypto.randomUUID()}`
        : `local-${Date.now()}`;
    const optimisticMessage: WorkspaceMessage = {
      message_id: messageId,
      sender_id: user.user_id,
      sender_type: 'user',
      sender_name: user.name,
      domain: 'workspace',
      intent: selectedGoal ? 'goal_message' : 'operator_message',
      conversation_id: selectedGoal?.conversation_id || null,
      priority: 'medium',
      tags: selectedGoal ? ['workspace', 'goal'] : ['workspace'],
      body_ref: `inline:json:${JSON.stringify({ message: text })}`,
      sent_at: new Date().toISOString(),
      processed_count: 0,
      queued: true,
      receipt_count: 0,
    };
    setOptimisticMessages((messages) => [...messages, optimisticMessage]);
    return messageId;
  };

  const updateMentionRange = (text: string, caret: number) => {
    setMentionRange(mentionRangeAt(text, caret));
    setActiveMentionIndex(0);
  };

  const insertMention = (candidate: (typeof mentionCandidates)[number]) => {
    if (!mentionRange) return;
    const token = mentionToken(candidate.display_name);
    const prefix = messageText.slice(0, mentionRange.start);
    const suffix = messageText.slice(mentionRange.end);
    const nextText = `${prefix}${token} ${suffix}`;
    const nextCaret = prefix.length + token.length + 1;
    setMessageText(nextText);
    setMentionRange(null);
    window.requestAnimationFrame(() => {
      messageInputRef.current?.focus();
      messageInputRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const publishMessage = async (overrideText?: string) => {
    if (!detail) return;
    const nextMessage = (overrideText ?? messageText).trim();
    if (!nextMessage) return;
    setError(null);
    const optimisticMessageId = addOptimisticUserMessage(nextMessage);
    markRoutedAgentsProcessing(nextMessage);
    if (overrideText === undefined) setMessageText('');
    setMentionRange(null);
    try {
      const result = await workspacesApi.publish(detail.workspace_id, {
        domain: 'workspace',
        intent: selectedGoal ? 'goal_message' : 'operator_message',
        payload: { message: nextMessage },
        tags: selectedGoal ? ['workspace', 'goal'] : ['workspace'],
        priority: 'medium',
        conversation_id: selectedGoal?.conversation_id,
      });
      setPublishResult(result);
      const nextDetail = await workspacesApi.get(detail.workspace_id);
      if (selectedGoal?.conversation_id) {
        nextDetail.messages = await workspacesApi.listMessages(detail.workspace_id, selectedGoal.conversation_id);
      }
      setOptimisticMessages((messages) => messages.filter((message) => message.message_id !== optimisticMessageId));
      setTypingAgentIds([]);
      setDetail(nextDetail);
    } catch (err) {
      console.error(err);
      setOptimisticMessages((messages) => messages.filter((message) => message.message_id !== optimisticMessageId));
      setTypingAgentIds([]);
      setError('메시지 전송 중 오류가 발생했습니다.');
    }
  };

  const selectGoal = async (goal: Goal | null) => {
    if (!detail) return;
    setSelectedGoalId(goal?.goal_id || null);
    if (!goal?.conversation_id) {
      const nextDetail = await workspacesApi.get(detail.workspace_id);
      setDetail(nextDetail);
      return;
    }
    const messages = await workspacesApi.listMessages(detail.workspace_id, goal.conversation_id);
    setDetail({ ...detail, messages });
    setWorkspaceMode('messaging');
    setInspectorMode('logs');
    setInspectorOpen(true);
  };

  const resetGoalForm = () => {
    setGoalName('');
    setGoalDescription('');
    setGoalPriority('medium');
    setGoalSuccessCriteria('');
    setGoalParentId(null);
    setGoalAssignedAgents([]);
  };

  const createGoal = async () => {
    if (!detail || !goalName.trim()) return;
    await workspacesApi.createGoal(detail.workspace_id, {
      name: goalName.trim(),
      description: goalDescription.trim() || undefined,
      priority: goalPriority,
      state: 'pending',
      parent_goal_id: goalParentId,
      assigned_agent_ids: goalAssignedAgents,
      success_criteria: goalSuccessCriteria.trim() || undefined,
    });
    const nextDetail = await workspacesApi.get(detail.workspace_id);
    setDetail(nextDetail);
    resetGoalForm();
    setShowGoalForm(false);
  };

  const startSubGoalForm = (parentGoal: Goal) => {
    setGoalParentId(parentGoal.goal_id);
    setGoalName('');
    setGoalDescription('');
    setGoalPriority(parentGoal.priority);
    setGoalSuccessCriteria('');
    setGoalAssignedAgents(parentGoal.assigned_agent_ids);
    setShowGoalForm(true);
  };

  const playCityLearnSimulation = () => {
    setCityLearnSimulation((current) => ({
      ...current,
      step: current.status === 'completed' ? 0 : current.step,
      status: 'running',
      gridAgentError: null,
    }));
  };

  const pauseCityLearnSimulation = () => {
    setCityLearnSimulation((current) => ({
      ...current,
      status: current.status === 'running' ? 'paused' : current.status,
    }));
  };

  const resetCityLearnSimulation = () => {
    setCityLearnSimulation((current) => ({
      ...current,
      step: 0,
      status: 'idle',
      lastGridAgentRun: null,
      pendingGridAgentStep: null,
      gridAgentError: null,
      forbiddenActionKeys: [],
      lastMacroMeshRun: null,
      pendingMacroMeshStep: null,
      macroMeshError: null,
    }));
  };

  const setCityLearnTickRate = (tickRateLabel: string) => {
    const nextTickRate = CITYLEARN_TICK_RATES.find((rate) => rate.label === tickRateLabel) || CITYLEARN_DEFAULT_TICK_RATE;
    setCityLearnSimulation((current) => ({ ...current, tickRate: nextTickRate }));
  };

  const deleteGoal = async (goal: Goal) => {
    if (!detail) return;
    const childGoalIds = new Set<string>();
    const collectChildren = (parentGoalId: string) => {
      detail.goals
        .filter((item) => item.parent_goal_id === parentGoalId)
        .forEach((child) => {
          childGoalIds.add(child.goal_id);
          collectChildren(child.goal_id);
        });
    };
    collectChildren(goal.goal_id);
    const deleteLabel = goal.parent_goal_id ? 'Sub Goal' : 'Goal';
    if (!window.confirm(`${deleteLabel} "${goal.name}"을 삭제하시겠습니까? 하위 Goal도 함께 삭제됩니다.`)) return;
    await workspacesApi.deleteGoal(detail.workspace_id, goal.goal_id);
    const nextDetail = await workspacesApi.get(detail.workspace_id);
    setDetail(nextDetail);
    if (selectedGoalId === goal.goal_id || childGoalIds.has(selectedGoalId || '')) {
      setSelectedGoalId(null);
    }
  };

  const updateGoalState = async (goal: Goal, nextState: Goal['state']) => {
    if (!detail) return;
    const updated = await workspacesApi.updateGoal(detail.workspace_id, goal.goal_id, { state: nextState });
    setDetail({
      ...detail,
      goals: detail.goals.map((item) => (item.goal_id === updated.goal_id ? updated : item)),
    });
  };

  const deleteWorkspace = async () => {
    if (!detail || !window.confirm('이 워크스페이스를 삭제하시겠습니까?')) return;
    await workspacesApi.delete(detail.workspace_id);
    await loadList();
    setDetail(null);
    setView('list');
  };

  useEffect(() => {
    if (!detail) return;

    const agentById = new Map(detail.placements.map((placement) => [placement.agent.agent_id, placement]));
    const cityLearnMapping = getCityLearnAgentBuildingMapping(detail.metadata_);
    const buildingAssignmentsByAgentId = new Map<string, CityLearnBuildingAssignment[]>();
    cityLearnMapping?.buildings.forEach((building) => {
      if (!building.assigned_agent_id) return;
      const assignments = buildingAssignmentsByAgentId.get(building.assigned_agent_id) || [];
      assignments.push(building);
      buildingAssignmentsByAgentId.set(building.assigned_agent_id, assignments);
    });
    const centralControllerAgentIds = new Set(cityLearnMapping?.central_controller_agents.map((agent) => agent.agent_id) || []);
    const edgeDegreeByNodeId = new Map<string, { incoming: number; outgoing: number }>();
    topologyEdges.forEach((edge) => {
      const sourceDegree = edgeDegreeByNodeId.get(edge.source_node_id) || { incoming: 0, outgoing: 0 };
      sourceDegree.outgoing += 1;
      edgeDegreeByNodeId.set(edge.source_node_id, sourceDegree);
      const targetDegree = edgeDegreeByNodeId.get(edge.target_node_id) || { incoming: 0, outgoing: 0 };
      targetDegree.incoming += 1;
      edgeDegreeByNodeId.set(edge.target_node_id, targetDegree);
    });
    const graphItems = detail.nodes.flatMap((node): TopologyGraphItem[] => {
      const placement = node.node_type === 'agent' ? agentById.get(node.ref_id) : undefined;
      const messageCount = activeMessages.filter((message) => message.sender_id === node.ref_id).length;
      const degree = edgeDegreeByNodeId.get(node.node_id) || { incoming: 0, outgoing: 0 };
      const baseItem: TopologyGraphItem = {
        id: node.node_id,
        dbNodeId: node.node_id,
        refId: node.ref_id,
        name: node.display_name,
        role: node.node_type === 'agent'
          ? placement?.agent.roles[0] || agentType(node.display_name)
          : 'workspace member',
        type: node.node_type === 'agent' ? agentType(node.display_name) : 'user',
        status: node.status,
        messageCount,
        eventCount: messageCount + degree.incoming + degree.outgoing,
        version: placement?.agent.version || '',
        tools: placement?.agent.tools || [],
        visibility: placement?.agent.visibility || '',
        nodeType: node.node_type,
        incoming: degree.incoming,
        outgoing: degree.outgoing,
        canEditTopology: true,
      };
      if (node.node_type !== 'agent') return [baseItem];

      const buildingAssignments = buildingAssignmentsByAgentId.get(node.ref_id) || [];
      if (buildingAssignments.length === 0) return [baseItem];

      const items: TopologyGraphItem[] = centralControllerAgentIds.has(node.ref_id)
        ? [{ ...baseItem, role: 'central controller', type: 'central agent' }]
        : [];

      buildingAssignments.forEach((building) => {
        const buildingLabel = cityLearnBuildingLabel(building.building_id);
        items.push({
          ...baseItem,
          id: `building-agent:${building.building_id}:${node.ref_id}`,
          name: `${node.display_name} · ${buildingLabel}`,
          role: buildingLabel,
          type: 'building agent',
          canEditTopology: false,
          buildingId: building.building_id,
        });
      });

      return items;
    });
    const filteredGraphItems = graphItems.filter((item) =>
      mapFilter === 'all' ? true : item.status === mapFilter
    );
    // 직사각형 둘레(perimeter) 배치: user/central controller는 중앙 허브에 세로 정렬,
    // 나머지(빌딩 에이전트 등)는 사각형 테두리를 따라 균등 배치 → 중앙으로 모이는 subscription 선이 명확.
    // 중앙 허브 = 사용자 + 모든 조정(central controller) 에이전트(Coordinator/Guard).
    // 외곽(테두리) = 빌딩 에이전트(및 그 외).
    // 주의: 'central agent' type은 building이 할당된 controller에만 붙으므로(Coordinator/Guard는 building 없음)
    //       type 대신 centralControllerAgentIds(=mapping의 central_controller_agents)로 직접 판정한다.
    const isCenterHub = (it: TopologyGraphItem) =>
      it.nodeType === 'user' ||
      (it.nodeType === 'agent' && !it.buildingId && centralControllerAgentIds.has(it.refId));
    const centerItems = filteredGraphItems.filter(isCenterHub);
    const ringItems = filteredGraphItems.filter((it) => !isCenterHub(it));
    const ringCount = Math.max(ringItems.length, 1);
    const NODE_W = 220;
    // 테두리를 따라 카드가 겹치지 않도록 둘레 길이를 노드 수에 비례시킨다.
    const frameWidth = Math.max(960, Math.round(ringCount * 82));
    const frameHeight = Math.max(640, Math.round(ringCount * 60));
    const perimeter = 2 * (frameWidth + frameHeight);
    const frameCenterX = frameWidth / 2;
    const frameCenterY = frameHeight / 2;
    const toTopLeft = (cx: number, cy: number) => ({ x: cx - NODE_W / 2, y: cy - 36 });
    const perimeterPositionFor = (item: TopologyGraphItem): { x: number; y: number } => {
      const centerIdx = centerItems.indexOf(item);
      if (centerIdx !== -1) {
        // 중앙 허브: 세로로 쌓는다.
        const offset = (centerIdx - (centerItems.length - 1) / 2) * 150;
        return toTopLeft(frameCenterX, frameCenterY + offset);
      }
      const ringIdx = ringItems.indexOf(item);
      const t = (perimeter * ringIdx) / ringCount; // 0..perimeter, 좌상단에서 시계방향
      let px: number;
      let py: number;
      if (t < frameWidth) {
        px = t;
        py = 0;
      } else if (t < frameWidth + frameHeight) {
        px = frameWidth;
        py = t - frameWidth;
      } else if (t < 2 * frameWidth + frameHeight) {
        px = frameWidth - (t - frameWidth - frameHeight);
        py = frameHeight;
      } else {
        px = 0;
        py = frameHeight - (t - 2 * frameWidth - frameHeight);
      }
      return toTopLeft(px, py);
    };
    const nodes: Node[] = filteredGraphItems.map((item) => {
      const defaultPosition = perimeterPositionFor(item);
      const statusColor = topologyStatusTone(item.status);
      const highlighted =
        (item.nodeType === 'agent' && selectedAgentId === item.refId) ||
        selectedMapNodeId === item.id;

      return {
        id: item.id,
        position: mapNodePositions[item.id] || defaultPosition,
        sourcePosition: Position.Top,
        targetPosition: Position.Top,
        connectable: Boolean(detail.user_can_manage && item.canEditTopology),
        data: {
          agentId: item.nodeType === 'agent' ? item.refId : undefined,
          dbNodeId: item.dbNodeId,
          refId: item.refId,
          nodeType: item.nodeType,
          displayName: item.name,
          status: item.status,
          role: item.role,
          messageCount: item.messageCount,
          eventCount: item.eventCount,
          tools: item.tools,
          version: item.version,
          visibility: item.visibility,
          incoming: item.incoming,
          outgoing: item.outgoing,
          canEditTopology: item.canEditTopology,
          buildingId: item.buildingId,
          label: (
            <div className={`relative min-w-[220px] rounded-[14px] border bg-white px-4 py-3 shadow-sm ${highlighted ? 'border-apple-blue shadow-[0_0_0_4px_rgba(0,113,227,0.14)]' : item.nodeType === 'user' ? 'border-[#0071e3]/20' : 'border-black/10'}`}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${item.nodeType === 'user' ? 'bg-[#0071e3] text-white' : 'bg-black/[0.06] text-black/60'}`}>
                    {item.nodeType === 'user' ? item.name.charAt(0) : 'A'}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-[#1d1d1f]">{item.name}</p>
                    <p className="text-[11px] uppercase tracking-[0.08em] text-black/38">{item.type}</p>
                  </div>
                </div>
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: statusColor }} />
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px] text-black/55">
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">msg {item.messageCount}</span>
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">edge {item.incoming + item.outgoing}</span>
              </div>
              <p className="mt-2 text-[11px] text-black/40">
                {item.status}{item.nodeType === 'agent' ? ` · ${item.buildingId ? cityLearnBuildingLabel(item.buildingId) : `v${item.version}`}` : ' · member'}
              </p>
            </div>
          ),
        },
        style: {
          border: 'none',
          background: 'transparent',
          padding: 0,
          width: 220,
        },
      };
    });

    const nodeIds = new Set(nodes.map((node) => node.id));
    const graphItemsById = new Map(graphItems.map((item) => [item.id, item]));
    // 현재 동작(메시지 생성/응답 대기) 중인 agent 집합 → 연결된 edge를 파랑↔빨강 점멸 처리.
    const typingSet = new Set(typingAgentIds);
    const graphItemIdsByDbNodeId = graphItems.reduce<Map<string, string[]>>((itemsByDbNodeId, item) => {
      const itemIds = itemsByDbNodeId.get(item.dbNodeId) || [];
      itemIds.push(item.id);
      itemsByDbNodeId.set(item.dbNodeId, itemIds);
      return itemsByDbNodeId;
    }, new Map());
    const subscriptionEdges: Edge[] = topologyEdges
      .flatMap((edge) => {
        const active = edge.status === 'active';
        const pending = edge.edge_id.startsWith('local-edge-');
        const sourceIds = (graphItemIdsByDbNodeId.get(edge.source_node_id) || []).filter((id) => nodeIds.has(id));
        const targetIds = (graphItemIdsByDbNodeId.get(edge.target_node_id) || []).filter((id) => nodeIds.has(id));
        return sourceIds.flatMap((sourceId) =>
          targetIds.map((targetId) => {
            const expanded = sourceId !== edge.source_node_id || targetId !== edge.target_node_id;
            const sourceNode = graphItemsById.get(sourceId);
            const targetNode = graphItemsById.get(targetId);
            const live = active && (
              (sourceNode?.nodeType === 'agent' && typingSet.has(sourceNode.refId)) ||
              (targetNode?.nodeType === 'agent' && typingSet.has(targetNode.refId))
            );
            return {
              id: expanded ? `${edge.edge_id}:${sourceId}:${targetId}` : edge.edge_id,
              source: sourceId,
              target: targetId,
              animated: active,
              className: live ? 'edge-live' : undefined,
              label: live ? 'active' : 'subscription',
              markerEnd: { type: MarkerType.ArrowClosed, color: live ? '#ff3b30' : active ? '#0071e3' : '#8e8e93' },
              data: {
                relation_type: edge.edge_type,
                status: edge.status,
                pending,
                sourceEdgeId: edge.edge_id,
                sourceName: sourceNode?.name || edge.source_node_id,
                targetName: targetNode?.name || edge.target_node_id,
                created_at: edge.created_at,
                updated_at: edge.updated_at,
              },
              style: {
                stroke: pending ? '#34c759' : active ? '#0071e3' : '#8e8e93',
                strokeWidth: active ? 2.2 : 1.6,
                strokeDasharray: pending || !active ? '5 5' : undefined,
              },
              labelStyle: { fill: '#3a3a3c', fontSize: 11, fontWeight: 600 },
            } satisfies Edge;
          })
        );
      });

    setMapNodes(nodes);
    setMapEdges(subscriptionEdges);
  }, [activeMessages, detail, mapFilter, mapNodePositions, selectedAgentId, selectedMapNodeId, setMapEdges, setMapNodes, topologyEdges, typingAgentIds]);

  const onTopologyNodeClick: NodeMouseHandler = (_, node) => {
    setSelectedMapNodeId(node.id);
    setSelectedMapEdgeId(null);
    setSelectedAgentId(node.data.nodeType === 'agent' ? String(node.data.agentId || '') : null);
    setInspectorMode('agent');
    setInspectorOpen(true);
  };

  const onTopologyEdgeClick: EdgeMouseHandler = (_, edge) => {
    setSelectedMapEdgeId(edge.id);
    setSelectedMapNodeId(null);
    setInspectorMode('logs');
    setInspectorOpen(true);
  };

  const setTopologySubscriptionDraft = (sourceNodeId: string, targetNodeId: string, enabled: boolean) => {
    if (!detail || !detail.user_can_manage) return;
    if (sourceNodeId === targetNodeId) {
      setError('같은 노드끼리는 구독 관계를 만들 수 없습니다.');
      return;
    }
    const sourceNode = detail.nodes.find((node) => node.node_id === sourceNodeId);
    const targetNode = detail.nodes.find((node) => node.node_id === targetNodeId);
    if (!sourceNode || !targetNode) return;
    if (sourceNode.node_type !== 'agent') {
      setError('구독 관계의 source node 는 agent 여야 합니다.');
      return;
    }
    const existing = topologyEdges.find(
      (edge) => edge.source_node_id === sourceNodeId && edge.target_node_id === targetNodeId
    );

    if (enabled) {
      if (existing) {
        setRemovedTopologyEdgeIds((ids) => ids.filter((edgeId) => edgeId !== existing.edge_id));
        return;
      }
      const now = new Date().toISOString();
      setPendingTopologyEdges((edges) => [
        ...edges,
        {
          edge_id: `local-edge-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          source_node_id: sourceNodeId,
          target_node_id: targetNodeId,
          edge_type: 'subscription',
          status: 'active',
          created_at: now,
          updated_at: now,
        },
      ]);
      setError(null);
      return;
    }

    if (!existing) return;
    if (existing.edge_id.startsWith('local-edge-')) {
      setPendingTopologyEdges((edges) => edges.filter((edge) => edge.edge_id !== existing.edge_id));
    } else {
      setRemovedTopologyEdgeIds((ids) => (
        ids.includes(existing.edge_id) ? ids : [...ids, existing.edge_id]
      ));
    }
    setError(null);
  };

  const onTopologyConnect = (connection: Connection) => {
    if (!connection.source || !connection.target) return;
    setTopologySubscriptionDraft(connection.source, connection.target, true);
  };

  const deleteSelectedTopologyEdge = () => {
    if (!selectedMapEdgeId) return;
    const selectedEdge = mapEdges.find((edge) => edge.id === selectedMapEdgeId);
    const sourceEdgeId = String(selectedEdge?.data?.sourceEdgeId || selectedMapEdgeId);
    if (sourceEdgeId.startsWith('local-edge-')) {
      setPendingTopologyEdges((edges) => edges.filter((edge) => edge.edge_id !== sourceEdgeId));
    } else {
      setRemovedTopologyEdgeIds((ids) => (
        ids.includes(sourceEdgeId) ? ids : [...ids, sourceEdgeId]
      ));
    }
    setSelectedMapEdgeId(null);
  };

  const saveTopologyChanges = async () => {
    if (!detail || (!pendingTopologyEdges.length && !removedTopologyEdgeIds.length)) return;
    setTopologySaving(true);
    setError(null);
    try {
      await Promise.all(removedTopologyEdgeIds.map((edgeId) => workspacesApi.deleteEdge(detail.workspace_id, edgeId)));
      for (const edge of pendingTopologyEdges) {
        await workspacesApi.createEdge(detail.workspace_id, {
          source_node_id: edge.source_node_id,
          target_node_id: edge.target_node_id,
          edge_type: 'subscription',
        });
      }
      const nextDetail = await workspacesApi.get(detail.workspace_id);
      setDetail(nextDetail);
      setPendingTopologyEdges([]);
      setRemovedTopologyEdgeIds([]);
      setSelectedMapEdgeId(null);
    } catch (err) {
      console.error(err);
      setError('토폴로지 변경사항 저장 중 오류가 발생했습니다.');
    } finally {
      setTopologySaving(false);
    }
  };

  const cancelTopologyChanges = () => {
    setPendingTopologyEdges([]);
    setRemovedTopologyEdgeIds([]);
    setSelectedMapEdgeId(null);
  };

  const toggleAgentToolDraft = (agentId: string, toolId: string) => {
    const currentTools =
      agentToolDrafts[agentId] ||
      detail?.placements.find((placement) => placement.agent.agent_id === agentId)?.agent.tools ||
      [];
    const nextTools = currentTools.includes(toolId)
      ? currentTools.filter((id) => id !== toolId)
      : [...currentTools, toolId];
    setAgentToolDrafts((drafts) => ({ ...drafts, [agentId]: nextTools }));
  };

  const saveAgentTools = async (agentId: string) => {
    if (!detail) return;
    const tools =
      agentToolDrafts[agentId] ||
      detail.placements.find((placement) => placement.agent.agent_id === agentId)?.agent.tools ||
      [];
    setToolSavingAgentId(agentId);
    setError(null);
    try {
      const updatedAgent = await workspacesApi.updateAgentTools(detail.workspace_id, agentId, tools);
      setDetail({
        ...detail,
        placements: detail.placements.map((placement) =>
          placement.agent.agent_id === agentId
            ? { ...placement, agent: { ...placement.agent, tools: updatedAgent.tools } }
            : placement
        ),
      });
      setAgentToolDrafts((drafts) => {
        const nextDrafts = { ...drafts };
        delete nextDrafts[agentId];
        return nextDrafts;
      });
    } catch (err) {
      console.error(err);
      setError('에이전트 도구 저장 중 오류가 발생했습니다.');
    } finally {
      setToolSavingAgentId(null);
    }
  };

  if (view === 'create') {
    return (
      <div className="animate-fade-in font-apple">
        <Header
          title="새 워크스페이스 생성"
          subtitle="환경 정보, 에이전트 배치, 추후 환경 구성 슬롯을 순서대로 설정합니다."
          actionLabel="목록으로"
          onAction={() => setView('list')}
        />
        {error && <Alert message={error} />}
        <div className="bg-apple-surface1 rounded-[18px] border border-white/5 p-6">
          <div className="flex gap-2 mb-6">
            {[1, 2, 3, 4].map((step) => (
              <div
                key={step}
                className={`flex-1 h-2 rounded-full ${wizardStep >= step ? 'bg-apple-blue' : 'bg-white/10'}`}
              />
            ))}
          </div>
          {wizardStep === 1 && (
            <section className="space-y-4">
              <Field label="워크스페이스 이름">
                <input className="input-field" value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} placeholder="예: 자동차 공장 전체" />
              </Field>
              <Field label="설명">
                <textarea className="input-field min-h-[110px]" value={workspaceDescription} onChange={(e) => setWorkspaceDescription(e.target.value)} placeholder="환경 범위, 데이터 소스, 에이전트가 감시할 상황을 설명하세요." />
              </Field>
              <Field label="태그 (쉼표 구분)">
                <input className="input-field" value={workspaceTags} onChange={(e) => setWorkspaceTags(e.target.value)} placeholder="factory, quality, logistics" />
              </Field>
              <button className="btn-primary" onClick={() => setWizardStep(2)}>다음: 에이전트 배치</button>
            </section>
          )}
          {wizardStep === 2 && (
            <section>
              <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-6">
                <div>
                  <div className="flex gap-2 mb-4">
                    <input className="input-field" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="마켓플레이스 에이전트 검색" />
                    <button className="btn-secondary" onClick={() => navigate('/dashboard/creator')}>새 에이전트 즉시 생성</button>
                  </div>
                  <div className="flex gap-2 mb-4 overflow-x-auto">
                    {CATEGORIES.map((category) => (
                      <button key={category} onClick={() => setActiveCategory(category)} className={`px-3 py-1.5 rounded-full text-[13px] ${activeCategory === category ? 'bg-apple-blue text-white' : 'bg-white/10 text-white/60'}`}>
                        {category}
                      </button>
                    ))}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {agents.map((agent) => (
                      <button key={agent.agent_id} onClick={() => addAgent(agent)} className="text-left bg-apple-surface2 rounded-[14px] p-4 border border-white/10 hover:border-apple-blue/60">
                        <p className="text-[15px] font-semibold text-white">{agent.name}</p>
                        <p className="text-[12px] text-white/50">v{agent.version} · {agent.metadata_?.category || 'General'}</p>
                        <p className="text-[13px] text-white/60 line-clamp-2 mt-2">{agent.description || agent.purpose || '설명이 없습니다.'}</p>
                      </button>
                    ))}
                  </div>
                </div>
                <aside className="bg-apple-surface2 rounded-[14px] p-4 border border-white/10 h-fit">
                  <h3 className="text-[17px] font-semibold text-white mb-3">배치 바구니</h3>
                  <div className="space-y-3">
                    {basketItems.length === 0 ? (
                      <p className="text-[13px] text-white/50">동일 에이전트를 여러 번 추가할 수 있습니다.</p>
                    ) : (
                      basketItems.map((item) => (
                        <div key={item.agent.agent_id} className="flex items-center justify-between gap-2">
                          <span className="text-[13px] text-white">{item.agent.name}</span>
                          <div className="flex items-center gap-2">
                            <button className="btn-secondary !px-2 !py-1" onClick={() => setQuantity(item.agent.agent_id, item.quantity - 1)}>-</button>
                            <span className="text-white/70 text-[13px] w-8 text-center">x{item.quantity}</span>
                            <button className="btn-secondary !px-2 !py-1" onClick={() => setQuantity(item.agent.agent_id, item.quantity + 1)}>+</button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                  {basketItems.length > 0 && (
                    <div className="border-t border-white/10 mt-4 pt-4">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <p className="text-[12px] text-white/50">구독 대상</p>
                        <div className="flex rounded-[10px] bg-white/10 p-1">
                          {(['all', 'user', 'agent'] as const).map((filter) => (
                            <button
                              key={filter}
                              className={`rounded-[8px] px-2 py-1 text-[11px] font-medium ${subscriptionFilter === filter ? 'bg-apple-blue text-white' : 'text-white/50'}`}
                              onClick={() => setSubscriptionFilter(filter)}
                            >
                              {filter}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="space-y-4">
                        {basketItems.map((item) => {
                          const selectedTargets = subscriptionTargets[item.agent.agent_id] || [];
                          const targetOptions = [
                            ...(user?.user_id
                              ? [{ key: `user:${user.user_id}`, label: user.name || '나', type: 'user' as const }]
                              : []),
                            ...basketItems
                              .filter((target) => target.agent.agent_id !== item.agent.agent_id)
                              .map((target) => ({
                                key: `agent:${target.agent.agent_id}`,
                                label: target.agent.name,
                                type: 'agent' as const,
                              })),
                          ].filter((target) => subscriptionFilter === 'all' || target.type === subscriptionFilter);
                          return (
                            <div key={`subscriptions-${item.agent.agent_id}`} className="rounded-[12px] bg-black/18 p-3">
                              <div className="mb-2 flex items-center justify-between gap-2">
                                <p className="truncate text-[12px] font-semibold text-white">{item.agent.name}</p>
                                <span className={`text-[11px] ${selectedTargets.length > 0 ? 'text-[#34c759]' : 'text-[#ff9f0a]'}`}>
                                  {selectedTargets.length} selected
                                </span>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                {targetOptions.length === 0 ? (
                                  <span className="text-[11px] text-white/35">선택 가능한 대상이 없습니다.</span>
                                ) : (
                                  targetOptions.map((target) => {
                                    const selected = selectedTargets.includes(target.key);
                                    return (
                                      <button
                                        key={target.key}
                                        className={`rounded-[9px] border px-2.5 py-1.5 text-[11px] transition ${selected ? 'border-apple-blue bg-apple-blue/20 text-white' : 'border-white/10 bg-white/[0.04] text-white/55 hover:border-apple-blue/50 hover:text-white'}`}
                                        onClick={() => toggleSubscriptionTarget(item.agent.agent_id, target.key)}
                                      >
                                        {target.type === 'user' ? '사용자' : '에이전트'} · {target.label}
                                      </button>
                                    );
                                  })
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <div className="border-t border-white/10 mt-4 pt-4">
                    <p className="text-[12px] text-white/50 mb-2">인라인 에이전트 초안</p>
                    <input className="input-field mb-2" value={draftAgentName} onChange={(e) => setDraftAgentName(e.target.value)} placeholder="초안 에이전트 이름" />
                    <textarea className="input-field min-h-[70px] mb-2" value={draftAgentPurpose} onChange={(e) => setDraftAgentPurpose(e.target.value)} placeholder="목적" />
                    <button className="btn-secondary w-full" onClick={createDraftAgent}>초안 생성 후 추가</button>
                  </div>
                </aside>
              </div>
              <div className="flex justify-between mt-6">
                <button className="btn-secondary" onClick={() => setWizardStep(1)}>이전</button>
                <button className="btn-primary" onClick={() => {
                  setError(null);
                  if (ensureAgentBasketForTopology()) setWizardStep(3);
                }}>다음: 토폴로지 구성</button>
              </div>
            </section>
          )}
          {wizardStep === 3 && (
            <section className="space-y-4">
              <div className="rounded-[14px] border border-white/10 bg-apple-surface2 p-4">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-[17px] font-semibold text-white">Topology 구성</h3>
                    <p className="mt-1 text-[13px] text-white/45">Agent 상단 포인트에서 사용자 또는 다른 agent로 드래그해 subscription edge를 만듭니다.</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      className="rounded-[10px] bg-white/10 px-3 py-2 text-[12px] font-semibold text-[#ff9f0a] disabled:opacity-40"
                      disabled={!selectedCreateEdgeId}
                      onClick={deleteSelectedCreateEdge}
                    >
                      Delete edge
                    </button>
                    <p className="text-[12px] text-white/42">{createMapNodes.length} nodes · {createMapEdges.length} edges</p>
                  </div>
                </div>
                <div className="h-[460px] overflow-hidden rounded-[18px] border border-white/10 bg-white">
                  <ReactFlow
                    nodes={createMapNodes}
                    edges={createMapEdges}
                    onNodesChange={onCreateMapNodesChange}
                    onEdgesChange={onCreateMapEdgesChange}
                    onConnect={onCreateTopologyConnect}
                    onEdgeClick={onCreateTopologyEdgeClick}
                    fitView
                    minZoom={0.25}
                    maxZoom={1.8}
                    nodesDraggable
                    nodesConnectable
                    edgesFocusable
                  >
                    <Background color="#d1d1d6" gap={18} />
                    <Controls />
                    <MiniMap
                      nodeColor={(node) => node.data.nodeType === 'user' ? '#0071e3' : '#8e8e93'}
                      pannable
                      zoomable
                    />
                  </ReactFlow>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {basketItems.map((item) => {
                  const selectedTargets = subscriptionTargets[item.agent.agent_id] || [];
                  return (
                    <div key={`topology-summary-${item.agent.agent_id}`} className="rounded-[12px] bg-white/[0.04] p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="truncate text-[13px] font-semibold text-white">{item.agent.name}</p>
                        <span className={`text-[11px] ${selectedTargets.length > 0 ? 'text-[#34c759]' : 'text-[#ff9f0a]'}`}>{selectedTargets.length} subscriptions</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {selectedTargets.length === 0 ? (
                          <span className="text-[11px] text-white/35">구독 대상 없음</span>
                        ) : (
                          selectedTargets.map((targetKey) => {
                            const [targetType, targetRefId] = targetKey.split(':');
                            const label = targetType === 'user'
                              ? user?.name || '나'
                              : basketItems.find((target) => target.agent.agent_id === targetRefId)?.agent.name || targetRefId;
                            return (
                              <span key={targetKey} className="rounded-[8px] bg-apple-blue/15 px-2 py-1 text-[11px] text-white/72">
                                {targetType} · {label}
                              </span>
                            );
                          })
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-between">
                <button className="btn-secondary" onClick={() => setWizardStep(2)}>이전</button>
                <button className="btn-primary" onClick={() => {
                  setError(null);
                  if (validateAgentSubscriptions()) setWizardStep(4);
                }}>다음: 환경 구성</button>
              </div>
            </section>
          )}
          {wizardStep === 4 && (
            <section className="space-y-4">
              <div>
                <div className="mb-4">
                  <h3 className="text-[19px] font-semibold text-white">Environment Setup</h3>
                  <p className="mt-1 text-[13px] text-white/45">에이전트가 동작할 시뮬레이션 환경 템플릿을 선택하세요.</p>
                </div>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {ENVIRONMENT_TEMPLATES.map((template) => {
                    const selected = selectedEnvironmentTemplateId === template.id;
                    const available = template.status === 'available';
                    const metadata = template.metadata;
                    return (
                      <button
                        key={template.id}
                        type="button"
                        disabled={!available}
                        onClick={() => {
                          if (!available) return;
                          setSelectedEnvironmentTemplateId(template.id);
                          setError(null);
                        }}
                        className={`min-h-[220px] rounded-[16px] border p-5 text-left transition ${
                          selected
                            ? 'border-apple-blue bg-apple-blue/16 shadow-[0_16px_48px_rgba(0,113,227,0.2)]'
                            : available
                              ? 'border-white/10 bg-apple-surface2 hover:border-apple-blue/50 hover:bg-white/[0.06]'
                              : 'cursor-not-allowed border-white/8 bg-white/[0.03] opacity-55'
                        }`}
                      >
                        <div className="mb-4 flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              {template.highlighted && (
                                <span className="rounded-full bg-[#34c759]/16 px-2 py-1 text-[11px] font-semibold text-[#34c759]">Recommended</span>
                              )}
                              <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${available ? 'bg-apple-blue/18 text-apple-blue' : 'bg-white/10 text-white/42'}`}>
                                {available ? 'Available' : 'Coming Soon'}
                              </span>
                            </div>
                            <p className="truncate text-[16px] font-semibold text-white">{template.name}</p>
                          </div>
                          <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
                            selected ? 'border-apple-blue bg-apple-blue text-white' : 'border-white/18 text-white/35'
                          }`}>
                            {selected ? '✓' : ''}
                          </span>
                        </div>
                        {template.description ? (
                          <p className="mb-4 line-clamp-3 text-[13px] leading-5 text-white/58">{template.description}</p>
                        ) : (
                          <p className="mb-4 text-[13px] leading-5 text-white/38">이 환경 템플릿은 후속 단계에서 제공됩니다.</p>
                        )}
                        {metadata ? (
                          <>
                            <div className="mb-4 grid grid-cols-2 gap-2">
                              <TemplateMetric label="Buildings" value={`${metadata.buildings}`} />
	                              <TemplateMetric label="Dataset" value={metadata.dataset_id || `${metadata.dataset_year}`} />
                              <TemplateMetric label="Time steps" value={`${metadata.time_steps}`} />
                              <TemplateMetric label="Interval" value={metadata.interval} />
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {metadata.features.map((feature) => (
                                <span key={feature} className="rounded-[8px] bg-black/20 px-2 py-1 text-[11px] text-white/54">
                                  {feature}
                                </span>
                              ))}
                            </div>
                          </>
                        ) : (
                          <div className="rounded-[12px] border border-dashed border-white/12 px-3 py-3 text-[12px] text-white/35">
                            세부 데이터셋 정보 준비 중
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
              {selectedEnvironmentTemplate?.metadata && (
                <div className="rounded-[14px] border border-apple-blue/25 bg-apple-blue/10 p-4">
                  <p className="text-[14px] font-semibold text-white">선택된 환경: {selectedEnvironmentTemplate.name}</p>
                  <p className="mt-1 text-[13px] leading-5 text-white/60">
                    CityLearn 2022 phase_all 데이터셋 기반 17개 빌딩 도시 환경입니다. 전력 소비, PV, 배터리 충방전 정보를 사용하는 전력 관리 시뮬레이션으로 구성됩니다.
                  </p>
                </div>
              )}
              {selectedEnvironmentTemplateId === 'citylearn-2022' && (
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
                  <aside className="rounded-[14px] border border-white/10 bg-apple-surface2 p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <h3 className="text-[16px] font-semibold text-white">Mapping Agents</h3>
                        <p className="mt-1 text-[12px] text-white/42">드래그하거나 드롭다운으로 빌딩에 할당합니다.</p>
                      </div>
                      <span className="rounded-full bg-white/10 px-2 py-1 text-[11px] text-white/55">{basketItems.length} types</span>
                    </div>
                    <div className="space-y-2">
                      {basketItems.map((item) => (
                        <button
                          key={`mapping-agent-${item.agent.agent_id}`}
                          type="button"
                          draggable
                          onDragStart={(event) => onMappingAgentDragStart(event, item.agent.agent_id)}
                          className="w-full cursor-grab rounded-[12px] border border-white/10 bg-black/18 px-3 py-3 text-left transition hover:border-apple-blue/50 active:cursor-grabbing"
                        >
                          <span className="block truncate text-[13px] font-semibold text-white">{item.agent.name}</span>
                          <span className="mt-1 block text-[11px] text-white/42">x{item.quantity} · {item.agent.metadata_?.category || 'General'}</span>
                        </button>
                      ))}
                    </div>
                    <div
                      className="mt-4 rounded-[14px] border border-dashed border-apple-blue/35 bg-apple-blue/10 p-3"
                      onDragOver={(event) => {
                        event.preventDefault();
                        event.dataTransfer.dropEffect = 'copy';
                      }}
                      onDrop={onCentralControllerDrop}
                    >
                      <div className="mb-3 flex items-center justify-between gap-2">
                        <p className="text-[13px] font-semibold text-white">Central Controller Zone</p>
                        <span className="text-[11px] text-white/45">{centralControllerAgentIds.length} agents</span>
                      </div>
                      <div className="space-y-2">
                        {basketItems.map((item) => {
                          const selected = centralControllerAgentIds.includes(item.agent.agent_id);
                          return (
                            <label key={`central-${item.agent.agent_id}`} className={`flex cursor-pointer items-center gap-2 rounded-[10px] px-2.5 py-2 ${selected ? 'bg-apple-blue/20 text-white' : 'bg-white/[0.04] text-white/55'}`}>
                              <input
                                type="checkbox"
                                checked={selected}
                                onChange={() => toggleCentralControllerAgent(item.agent.agent_id)}
                              />
                              <span className="min-w-0 flex-1 truncate text-[12px]">{item.agent.name}</span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  </aside>

                  <div className="rounded-[14px] border border-white/10 bg-apple-surface2 p-4">
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h3 className="text-[16px] font-semibold text-white">CityLearn Building Map</h3>
                        <p className="mt-1 text-[12px] text-white/42">17개 빌딩의 배터리, PV 설비와 할당 에이전트입니다.</p>
                      </div>
                      <div className="flex flex-wrap gap-2 text-[11px]">
                        <span className="rounded-full bg-[#34c759]/16 px-2 py-1 text-[#34c759]">{mappedCityLearnBuildingCount}/17 mapped</span>
                        {unmappedCityLearnBuildingIds.length > 0 && (
                          <span className="rounded-full bg-[#ff9f0a]/16 px-2 py-1 text-[#ff9f0a]">{unmappedCityLearnBuildingIds.length} unmapped allowed</span>
                        )}
                      </div>
                    </div>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                      {CITYLEARN_BUILDING_NODES.map((building) => {
                        const assignedAgentId = buildingAgentAssignments[building.id];
                        const assignedAgent = assignedAgentId ? basketAgentMap.get(assignedAgentId) : undefined;
                        return (
                          <div
                            key={building.id}
                            className={`min-h-[176px] rounded-[14px] border p-3 transition ${
                              assignedAgent
                                ? 'border-apple-blue/55 bg-apple-blue/12'
                                : 'border-white/10 bg-white/[0.035] hover:border-white/22'
                            }`}
                            onDragOver={(event) => {
                              event.preventDefault();
                              event.dataTransfer.dropEffect = 'copy';
                            }}
                            onDrop={(event) => onBuildingMappingDrop(event, building.id)}
                          >
                            <div className="mb-2 flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <p className="truncate text-[13px] font-semibold text-white">{building.id.replace('_', ' ')}</p>
                                <p className="mt-0.5 text-[11px] text-white/38">Battery {building.battery_capacity}kWh</p>
                              </div>
                              <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${assignedAgent ? 'bg-apple-blue text-white' : 'bg-white/10 text-white/42'}`}>
                                {assignedAgent ? 'Mapped' : 'Open'}
                              </span>
                            </div>
                            <div className="mb-3 grid grid-cols-2 gap-1.5">
                              <span className="rounded-[8px] bg-black/18 px-2 py-1.5 text-[11px] text-white/58">PV {building.pv_power.toFixed(1)}kW</span>
                              <span className="rounded-[8px] bg-black/18 px-2 py-1.5 text-[11px] text-white/58">Battery {building.battery_capacity.toFixed(1)}kWh</span>
                            </div>
                            <select
                              className="w-full rounded-[10px] border border-white/10 bg-[#202126] px-2.5 py-2 text-[12px] text-white outline-none"
                              value={assignedAgent?.agent_id || ''}
                              onChange={(event) => assignAgentToBuilding(building.id, event.target.value || null)}
                            >
                              <option value="">미할당</option>
                              {basketItems.map((item) => (
                                <option key={`${building.id}-${item.agent.agent_id}`} value={item.agent.agent_id}>
                                  {item.agent.name}
                                </option>
                              ))}
                            </select>
                          </div>
                        );
                      })}
                    </div>
                    {unmappedCityLearnBuildingIds.length > 0 && (
                      <p className="mt-3 text-[12px] leading-5 text-[#ff9f0a]">
                        미매핑 빌딩: {unmappedCityLearnBuildingIds.slice(0, 6).map((id) => id.replace('_', ' ')).join(', ')}
                        {unmappedCityLearnBuildingIds.length > 6 ? ` 외 ${unmappedCityLearnBuildingIds.length - 6}개` : ''}. 생성은 허용됩니다.
                      </p>
                    )}
                  </div>
                </div>
              )}
              <div className="flex justify-between">
                <button className="btn-secondary" onClick={() => setWizardStep(3)}>이전</button>
                <button className="btn-primary" onClick={createWorkspace} disabled={saving}>
                  {saving ? '생성 중...' : '워크스페이스 생성'}
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    );
  }

  if (view === 'detail' && detail) {
    const selectedAgent =
      detail.placements.find((placement) => placement.agent.agent_id === selectedAgentId) ||
      detail.placements[0] ||
      null;
    const cityLearnWorkspace = isCityManagementWorkspace(detail.metadata_);
    const meshChescaWorkspace = isMeshChescaWorkspace(detail.metadata_);
    const expandedMessage = detail.messages.find((message) => message.message_id === expandedMessageId);
    const agentLabel = selectedAgent ? selectedAgent.agent.name : 'environment-messages';
    const selectedSubscribedNodes = selectedMapNodeId
      ? mapEdges
          .filter((edge) => edge.source === selectedMapNodeId)
          .map((edge) => ({
            edge,
            node: mapNodes.find((node) => node.id === edge.target),
          }))
          .filter((item) => Boolean(item.node))
      : [];
    const detailAgentStatusById = new Map(
      detail.nodes
        .filter((node) => node.node_type === 'agent')
        .map((node) => [node.ref_id, node.status])
    );

    const detailGridColumns = workspaceSidebarCollapsed
      ? inspectorOpen
        ? 'xl:grid-cols-[76px_minmax(0,1fr)_340px]'
        : 'xl:grid-cols-[76px_minmax(0,1fr)]'
      : inspectorOpen
        ? 'xl:grid-cols-[280px_minmax(0,1fr)_340px]'
        : 'xl:grid-cols-[280px_minmax(0,1fr)]';

    return (
      <div className="-mt-5 animate-fade-in font-apple">
        <div className="mb-2 flex items-center justify-between">
          <button className="btn-secondary !py-2" onClick={() => setView('list')}>← 워크스페이스 목록</button>
          <div className="hidden md:flex items-center gap-2 text-[12px] text-white/45">
            <span>{detail.tags.join(' · ') || 'untagged environment'}</span>
            <span>·</span>
            <span>{detail.active_agent_count} agent instances</span>
          </div>
        </div>

        <div className={`grid h-[calc(100vh-158px)] min-h-0 grid-cols-1 ${detailGridColumns} gap-0 overflow-hidden rounded-[22px] border border-white/10 bg-[#101114] shadow-[0_18px_70px_rgba(0,0,0,0.35)] transition-[grid-template-columns] duration-300 ease-out`}>
          <aside className="flex min-h-0 flex-col border-b border-white/10 bg-[#17181c] transition-[width] duration-300 xl:border-b-0 xl:border-r">
            <div className={`${workspaceSidebarCollapsed ? 'p-3' : 'p-5'} border-b border-white/10 transition-all duration-300`}>
              <div className={`flex items-start ${workspaceSidebarCollapsed ? 'justify-center' : 'gap-3'}`}>
                {!workspaceSidebarCollapsed && (
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-white/35">Workspace</p>
                    <h1 className="mt-1 truncate text-[19px] font-semibold text-white">{detail.name || '워크스페이스'}</h1>
                    <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-white/45">{detail.description || '다중 에이전트 그래프 환경'}</p>
                  </div>
                )}
                <button
                  type="button"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] text-white/50 transition hover:bg-white/10 hover:text-white"
                  onClick={() => setWorkspaceSidebarCollapsed((collapsed) => !collapsed)}
                  aria-label={workspaceSidebarCollapsed ? '워크스페이스 정보 사이드바 펼치기' : '워크스페이스 정보 사이드바 접기'}
                  aria-expanded={!workspaceSidebarCollapsed}
                  title={workspaceSidebarCollapsed ? '워크스페이스 정보 펼치기' : '워크스페이스 정보 접기'}
                >
                  <svg
                    className={`h-5 w-5 transition-transform duration-300 ${workspaceSidebarCollapsed ? 'rotate-180' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
              </div>
            </div>

            {workspaceSidebarCollapsed ? (
              <div className="flex-1 overflow-y-auto px-3 py-4">
                <div className="space-y-2">
                  <button
                    type="button"
                    className="flex h-12 w-full items-center justify-center rounded-[12px] bg-white/[0.04] text-[12px] font-semibold text-white/68 hover:bg-white/[0.08] hover:text-white"
                    onClick={() => setWorkspaceSidebarCollapsed(false)}
                    title={detail.name || '워크스페이스'}
                  >
                    W
                  </button>
                  <button
                    type="button"
                    className="flex h-12 w-full items-center justify-center rounded-[12px] text-[12px] font-semibold text-white/55 hover:bg-white/[0.08] hover:text-white"
                    onClick={() => {
                      setWorkspaceSidebarCollapsed(false);
                      setInspectorMode('agent');
                      setInspectorOpen(true);
                    }}
                    title={`Active Agents ${detail.placements.length}`}
                  >
                    A
                  </button>
                  <button
                    type="button"
                    className="flex h-12 w-full items-center justify-center rounded-[12px] text-[12px] font-semibold text-white/55 hover:bg-white/[0.08] hover:text-white"
                    onClick={() => setWorkspaceSidebarCollapsed(false)}
                    title={`Workspace Members ${workspaceMembers.length}`}
                  >
                    U
                  </button>
                  <button
                    type="button"
                    className="flex h-12 w-full items-center justify-center rounded-[12px] text-[12px] font-semibold text-white/55 hover:bg-white/[0.08] hover:text-white"
                    onClick={() => setWorkspaceSidebarCollapsed(false)}
                    title={`Goals ${detail.goals.length}`}
                  >
                    G
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto p-3">
                <SidebarGroup title="Active Agents">
                {detail.placements.map((placement, index) => {
                  const status = detailAgentStatusById.get(placement.agent.agent_id) || agentStatus(index);
                  const unreadCount = detail.messages.filter(
                    (message) => message.sender_id === placement.agent.agent_id
                  ).length;
                  const selected = selectedAgent?.agent.agent_id === placement.agent.agent_id;
                  return (
                    <button
                      key={placement.agent.agent_id}
                      className={`mb-1 flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left transition ${selected ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07] hover:text-white'}`}
                      onClick={() => {
                        setSelectedAgentId(placement.agent.agent_id);
                        setInspectorMode('agent');
                        setInspectorOpen(true);
                      }}
                    >
                      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusTone(status)}`} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">{placement.agent.name}</span>
                        <span className="block text-[11px] text-white/38">instance x{placement.quantity} · {statusLabel(status)}</span>
                      </span>
                      {unreadCount > 0 && (
                        <span className="rounded-full bg-apple-blue px-2 py-0.5 text-[11px] font-semibold text-white">{unreadCount}</span>
                      )}
                    </button>
                  );
                })}
                </SidebarGroup>

                <SidebarGroup title="Workspace Members">
                {workspaceMembers.length === 0 ? (
                  <div className="rounded-[12px] px-3 py-2 text-[12px] text-white/38">참여한 사용자가 없습니다.</div>
                ) : (
                  workspaceMembers.map((member) => {
                    const memberNodeId = `user-${member.node_id}`;
                    const selected = selectedMapNodeId === memberNodeId;
                    const messageCount = detail.messages.filter((message) => message.sender_id === member.ref_id).length;
                    return (
                      <button
                        key={member.node_id}
                        className={`mb-1 flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left transition ${selected ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07] hover:text-white'}`}
                        onClick={() => {
                          setSelectedAgentId(null);
                          setSelectedMapNodeId(memberNodeId);
                          setSelectedMapEdgeId(null);
                          setInspectorMode('agent');
                          setInspectorOpen(true);
                        }}
                      >
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-apple-blue text-[11px] font-semibold text-white">
                          {member.display_name.charAt(0)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium">{member.display_name}</span>
                          <span className="block text-[11px] text-white/38">{member.status} · messages {messageCount}</span>
                        </span>
                      </button>
                    );
                  })
                )}
                </SidebarGroup>

                <SidebarGroup title="Goals">
                <button
                  className={`mb-1 flex w-full items-center justify-between rounded-[12px] px-3 py-2.5 text-left transition ${!selectedGoal ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07]'}`}
                  onClick={() => void selectGoal(null)}
                >
                  <span className="truncate text-[13px] font-medium"># workspace-wide</span>
                  <span className="text-[11px] text-white/38">{detail.recent_message_count}</span>
                </button>
                {topLevelGoals.map((goal) => (
                  <GoalTreeItem
                    key={goal.goal_id}
                    goal={goal}
                    goals={detail.goals}
                    selectedGoalId={selectedGoalId}
                    onSelect={selectGoal}
                    canManage={detail.user_can_manage}
                    onCreateChild={startSubGoalForm}
                    onDelete={deleteGoal}
                  />
                ))}
                {detail.user_can_manage && (
                  <button
                    className="mt-2 w-full rounded-[12px] border border-dashed border-white/18 px-3 py-2 text-left text-[12px] font-medium text-white/55 hover:border-apple-blue/60 hover:text-white"
                    onClick={() => {
                      setGoalParentId(null);
                      setShowGoalForm((value) => !value);
                    }}
                  >
                    + Goal 생성
                  </button>
                )}
                {showGoalForm && (
                  <div className="mt-3 rounded-[14px] bg-black/20 p-3">
                    <input className="mb-2 w-full rounded-[10px] border border-white/10 bg-white/[0.06] px-3 py-2 text-[12px] text-white outline-none" value={goalName} onChange={(e) => setGoalName(e.target.value)} placeholder="Goal 이름" />
                    <textarea className="mb-2 min-h-[64px] w-full rounded-[10px] border border-white/10 bg-white/[0.06] px-3 py-2 text-[12px] text-white outline-none" value={goalDescription} onChange={(e) => setGoalDescription(e.target.value)} placeholder="설명" />
                    <select className="mb-2 w-full rounded-[10px] border border-white/10 bg-[#202126] px-3 py-2 text-[12px] text-white outline-none" value={goalParentId || ''} onChange={(e) => setGoalParentId(e.target.value || null)}>
                      <option value="">상위 Goal 없음</option>
                      {detail.goals.map((goal) => <option key={goal.goal_id} value={goal.goal_id}>{goal.name}</option>)}
                    </select>
                    <select className="mb-2 w-full rounded-[10px] border border-white/10 bg-[#202126] px-3 py-2 text-[12px] text-white outline-none" value={goalPriority} onChange={(e) => setGoalPriority(e.target.value as Goal['priority'])}>
                      {(['low', 'medium', 'high', 'critical'] as const).map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                    </select>
                    <div className="mb-2 max-h-[92px] overflow-y-auto rounded-[10px] border border-white/10 p-2">
                      {detail.placements.map((placement) => (
                        <label key={placement.agent.agent_id} className="mb-1 flex items-center gap-2 text-[11px] text-white/60">
                          <input
                            type="checkbox"
                            checked={goalAssignedAgents.includes(placement.agent.agent_id)}
                            onChange={(event) => {
                              setGoalAssignedAgents((prev) =>
                                event.target.checked
                                  ? [...prev, placement.agent.agent_id]
                                  : prev.filter((agentId) => agentId !== placement.agent.agent_id)
                              );
                            }}
                          />
                          {placement.agent.name}
                        </label>
                      ))}
                    </div>
                    <textarea className="mb-2 min-h-[54px] w-full rounded-[10px] border border-white/10 bg-white/[0.06] px-3 py-2 text-[12px] text-white outline-none" value={goalSuccessCriteria} onChange={(e) => setGoalSuccessCriteria(e.target.value)} placeholder="종료 조건" />
                    <div className="flex gap-2">
                      <button className="flex-1 rounded-[10px] bg-apple-blue px-3 py-2 text-[12px] font-semibold text-white" onClick={createGoal}>생성</button>
                      <button className="rounded-[10px] bg-white/10 px-3 py-2 text-[12px] text-white/70" onClick={() => { resetGoalForm(); setShowGoalForm(false); }}>취소</button>
                    </div>
                  </div>
                )}
                </SidebarGroup>

                <SidebarGroup title="System Agents">
                <button className="flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left text-white/55 hover:bg-white/[0.07]">
                  <span className="h-2.5 w-2.5 rounded-full bg-white/30" />
                  <span className="text-[13px]">Graph Orchestrator</span>
                </button>
                <button className="flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left text-white/55 hover:bg-white/[0.07]">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#ffd60a]" />
                  <span className="text-[13px]">Memory Indexer</span>
                </button>
                </SidebarGroup>
              </div>
            )}

            <div className={`${workspaceSidebarCollapsed ? 'p-3' : 'p-4'} border-t border-white/10`}>
              <div className="flex items-center gap-3 rounded-[14px] bg-white/[0.04] p-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-apple-blue text-[13px] font-semibold text-white">
                  {(user?.name || 'U').charAt(0)}
                </div>
                {!workspaceSidebarCollapsed && <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-white">{user?.name || '사용자'}</p>
                  <p className="text-[11px] text-white/38">Settings · Profile</p>
                </div>}
              </div>
            </div>
          </aside>

          <main className="flex min-h-0 min-w-0 flex-col bg-[#f4f5f7] text-[#1d1d1f]">
            <div className="flex items-center justify-between border-b border-black/10 bg-white/86 px-5 py-4 backdrop-blur-xl">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-[18px] font-semibold text-[#1d1d1f]"># {selectedGoal ? selectedGoal.name : agentLabel}</h2>
                  <span className={`h-2.5 w-2.5 rounded-full ${selectedGoal?.state === 'blocked' || selectedGoal?.state === 'failed' ? 'bg-[#ff453a]' : selectedAgent ? statusTone(agentStatus(detail.placements.indexOf(selectedAgent))) : 'bg-[#34c759]'}`} />
                </div>
                <p className="text-[12px] text-black/45">
                  {selectedGoal
                    ? `${selectedGoal.state} · ${selectedGoal.progress}% · ${selectedGoal.assigned_agent_ids.length} assigned agents`
                    : selectedAgent ? `${statusLabel(agentStatus(detail.placements.indexOf(selectedAgent)))} · ${selectedAgent.quantity} instance(s)` : 'workspace-wide agent collaboration'}
                </p>
              </div>
              <div className="flex gap-2">
                {detail.user_can_manage && selectedGoal && (
                  <select
                    className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-medium text-black/70 shadow-sm outline-none"
                    value={selectedGoal.state}
                    onChange={(e) => void updateGoalState(selectedGoal, e.target.value as Goal['state'])}
                  >
                    {(['pending', 'running', 'blocked', 'completed', 'failed'] as const).map((state) => (
                      <option key={state} value={state}>{state}</option>
                    ))}
                  </select>
                )}
                <div className="mr-2 flex rounded-[12px] border border-black/10 bg-black/[0.04] p-1">
                  <button
                    className={`rounded-[9px] px-3 py-1.5 text-[12px] font-medium ${workspaceMode === 'messaging' ? 'bg-white text-black/80 shadow-sm' : 'text-black/45'}`}
                    onClick={() => setWorkspaceMode('messaging')}
                  >
                    Messaging
                  </button>
                  <button
                    className={`rounded-[9px] px-3 py-1.5 text-[12px] font-medium ${workspaceMode === 'map' ? 'bg-white text-black/80 shadow-sm' : 'text-black/45'}`}
                    onClick={() => setWorkspaceMode('map')}
                  >
                    Map
                  </button>
                  <button
                    className={`rounded-[9px] px-3 py-1.5 text-[12px] font-medium ${workspaceMode === 'board' ? 'bg-white text-black/80 shadow-sm' : cityLearnWorkspace ? 'text-black/45' : 'cursor-not-allowed text-black/28'}`}
                    onClick={() => {
                      if (cityLearnWorkspace) setWorkspaceMode('board');
                    }}
                    disabled={!cityLearnWorkspace}
                    title={cityLearnWorkspace ? 'Board' : 'Board Coming Soon'}
                  >
                    Board{cityLearnWorkspace ? '' : ' · Coming Soon'}
                  </button>
                </div>
                <button
                  className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-medium text-black/70 shadow-sm hover:bg-black/[0.03]"
                  onClick={() => {
                    setInspectorMode('agent');
                    setInspectorOpen(true);
                  }}
                >
                  View Agent Info
                </button>
                <button
                  className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-medium text-black/70 shadow-sm hover:bg-black/[0.03]"
                  onClick={() => {
                    setInspectorMode('logs');
                    setInspectorOpen(true);
                  }}
                >
                  Expand Logs
                </button>
                {detail.user_can_delete && (
                  <button
                    className="rounded-[10px] border border-[#ff453a]/20 bg-[#ff453a]/10 px-3 py-2 text-[12px] font-medium text-[#d70015] shadow-sm hover:bg-[#ff453a]/15"
                    onClick={deleteWorkspace}
                  >
                    Delete Workspace
                  </button>
                )}
	              </div>
	            </div>

	            {cityLearnWorkspace && workspaceMode === 'board' && (
	              <CityLearnSimulationControlBar
	                simulation={cityLearnSimulation}
	                onPlay={playCityLearnSimulation}
	                onPause={pauseCityLearnSimulation}
	                onReset={resetCityLearnSimulation}
	                onTickRateChange={setCityLearnTickRate}
	                agentMeshMode={cityLearnAgentMeshMode}
	              />
	            )}
	
	            {workspaceMode === 'messaging' ? (
	              <>
                <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-6 md:px-7">
                  {visibleMessages.length > 0 && (
                    <div className="pointer-events-none sticky top-0 z-20 -mt-2 -mb-4 flex justify-end">
                      <button
                        type="button"
                        onClick={cleanMessages}
                        title="메시지 기록 비우기 (데모용)"
                        aria-label="메시지 기록 비우기"
                        className="pointer-events-auto inline-flex h-9 w-9 items-center justify-center rounded-full border border-black/10 bg-white/90 text-black/55 shadow-sm backdrop-blur transition hover:bg-black/[0.04] hover:text-black/80"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M3 6h18" />
                          <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
                          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                          <path d="M10 11v6M14 11v6" />
                        </svg>
                      </button>
                    </div>
                  )}
                  {visibleMessages.length === 0 ? (
                    <div className="mx-auto mt-20 max-w-[420px] rounded-[18px] border border-black/8 bg-white p-6 text-center shadow-sm">
                      <p className="text-[17px] font-semibold text-[#1d1d1f]">아직 메시지가 없습니다</p>
                      <p className="mt-2 text-[13px] leading-5 text-black/50">워크스페이스에 첫 메시지를 보내면 에이전트 협업 타임라인이 이곳에 표시됩니다.</p>
                    </div>
                  ) : (
                    visibleMessages.map((message) => {
                      const isSystem = message.sender_type === 'system';
                      const isMine = message.sender_type === 'user' && message.sender_id === user?.user_id;
                      const isExpanded = expandedMessageId === message.message_id;
                      return (
                        <div key={message.message_id} className={`flex ${isMine ? 'justify-end' : 'justify-start'}`}>
                          <div className={`flex max-w-[780px] gap-3 ${isMine ? 'flex-row-reverse' : ''}`}>
                            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold ${isMine ? 'bg-apple-blue text-white' : isSystem ? 'bg-[#ff3b30] text-white' : 'bg-white text-black/70 shadow-sm'}`}>
                              {(isMine ? user?.name : message.sender_name || message.sender_type || 'A')?.charAt(0)}
                            </div>
                            <div className={`min-w-0 ${isMine ? 'items-end text-right' : 'items-start text-left'}`}>
                              <div className={`mb-1 flex items-center gap-2 ${isMine ? 'justify-end' : 'justify-start'}`}>
                                <span className={`text-[13px] font-semibold ${isSystem ? 'text-[#d70015]' : 'text-black/75'}`}>{isMine ? 'You' : message.sender_name || message.sender_type}</span>
                                <span className="text-[11px] text-black/35">{new Date(message.sent_at).toLocaleString()}</span>
                              </div>
                              <div className={`rounded-[18px] px-4 py-3 text-[14px] leading-6 shadow-sm ${isMine ? 'rounded-br-[6px] bg-apple-blue text-white' : isSystem ? 'rounded-bl-[6px] border border-[#ff3b30]/25 bg-[#fff2f2] text-[#d70015]' : 'rounded-bl-[6px] border border-black/6 bg-white text-black/78'}`}>
                                {bodyPreview(message.body_ref)}
                              </div>
                              <button
                                className={`mt-1.5 text-[11px] font-medium ${isMine ? 'text-apple-blue' : isSystem ? 'text-[#d70015]/70 hover:text-[#d70015]' : 'text-black/42 hover:text-apple-blue'}`}
                                onClick={() => {
                                  setExpandedMessageId(isExpanded ? null : message.message_id);
                                  setInspectorMode('message');
                                  setInspectorOpen(true);
                                }}
                              >
                                {isExpanded ? 'Hide details' : 'Inspect details'}
                              </button>
                              {isExpanded && (
                                <div className={`mt-2 rounded-[12px] border border-black/8 bg-white/70 px-3 py-2 text-[11px] text-black/45 ${isMine ? 'text-right' : 'text-left'}`}>
                                  Inspector opened · {message.receipt_count} receipts · {message.priority} priority
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                  {typingAgents.map((agent) => (
                    <div key={`typing-${agent.agent_id}`} className="flex justify-start">
                      <div className="flex max-w-[780px] gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-[13px] font-semibold text-black/70 shadow-sm">
                          {agent.name.charAt(0)}
                        </div>
                        <div className="min-w-0 text-left">
                          <div className="mb-1 flex items-center gap-2">
                            <span className="text-[13px] font-semibold text-black/75">{agent.name}</span>
                            <span className="text-[11px] text-black/35">typing</span>
                          </div>
                          <div className="inline-flex items-center gap-2 rounded-[18px] rounded-bl-[6px] border border-black/6 bg-white px-4 py-3 shadow-sm">
                            <span className="text-[13px] font-medium text-black/58">생각중</span>
                            <span className="flex h-4 items-end gap-1">
                              {[0, 1, 2].map((dot) => (
                                <span
                                  key={dot}
                                  className="block h-2 w-2 animate-bounce rounded-full bg-apple-blue"
                                  style={{ animationDelay: `${dot * 140}ms`, animationDuration: '860ms' }}
                                />
                              ))}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                  {/* deterministic/llm_planner in-flight 중 매칭 배치 agent가 없을 때 generic typing. */}
                  {typingAgents.length === 0 && cityLearnSimulation.pendingGridAgentStep !== null && (
                    <div className="flex justify-start">
                      <div className="flex max-w-[780px] gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-[13px] font-semibold text-black/70 shadow-sm">
                          G
                        </div>
                        <div className="min-w-0 text-left">
                          <div className="mb-1 flex items-center gap-2">
                            <span className="text-[13px] font-semibold text-black/75">
                              {cityLearnAgentMeshMode === 'llm_planner' ? 'City Grid Coordinator' : 'Grid-Agent'}
                            </span>
                            <span className="text-[11px] text-black/35">running</span>
                          </div>
                          <div className="inline-flex items-center gap-2 rounded-[18px] rounded-bl-[6px] border border-black/6 bg-white px-4 py-3 shadow-sm">
                            <span className="text-[13px] font-medium text-black/58">응답 대기중</span>
                            <span className="flex h-4 items-end gap-1">
                              {[0, 1, 2].map((dot) => (
                                <span
                                  key={dot}
                                  className="block h-2 w-2 animate-bounce rounded-full bg-apple-blue"
                                  style={{ animationDelay: `${dot * 140}ms`, animationDuration: '860ms' }}
                                />
                              ))}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                  {/* macro_mesh in-flight: 17 Building Battery Agent를 각각 독립된 에이전트 버블로 표시. */}
                  {cityLearnSimulation.pendingMacroMeshStep !== null && (
                    <>
                      <div className="px-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-black/35">
                        Round 1/2 · 17 Building Battery Agents 병렬 협상중
                      </div>
                      {CITYLEARN_BUILDING_NODES.map((building, idx) => (
                        <div key={`mc-peer-${building.id}`} className="flex justify-start">
                          <div className="flex max-w-[780px] gap-3">
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-apple-blue/10 text-[12px] font-semibold text-[#005bb5] shadow-sm">
                              {idx + 1}
                            </div>
                            <div className="min-w-0 text-left">
                              <div className="mb-1 flex items-center gap-2">
                                <span className="text-[13px] font-semibold text-black/75">
                                  Building Battery Agent · {cityLearnBuildingLabel(building.id)}
                                </span>
                                <span className="text-[11px] text-black/35">협상중</span>
                              </div>
                              <div className="inline-flex items-center gap-2 rounded-[18px] rounded-bl-[6px] border border-black/6 bg-white px-4 py-3 shadow-sm">
                                <span className="text-[13px] font-medium text-black/58">flex offer 발의중</span>
                                <span className="flex h-4 items-end gap-1">
                                  {[0, 1, 2].map((dot) => (
                                    <span
                                      key={dot}
                                      className="block h-2 w-2 animate-bounce rounded-full bg-apple-blue"
                                      style={{ animationDelay: `${(idx * 60 + dot * 140) % 900}ms`, animationDuration: '860ms' }}
                                    />
                                  ))}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                  <div ref={messageFeedEndRef} />
                </div>
                <div className="border-t border-black/10 bg-white/90 p-3">
                  <div className="relative flex items-center gap-2 rounded-[14px] border border-black/10 bg-[#f7f8fa] p-1.5 shadow-inner">
                    {mentionRange && mentionCandidates.length > 0 && (
                      <div className="absolute bottom-[calc(100%+8px)] left-2 z-20 w-[min(360px,calc(100%-16px))] overflow-hidden rounded-[12px] border border-black/10 bg-white shadow-[0_14px_42px_rgba(0,0,0,0.16)]">
                        {mentionCandidates.map((candidate, index) => {
                          const active = index === activeMentionIndex;
                          return (
                            <button
                              key={candidate.node_id}
                              className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition ${active ? 'bg-apple-blue/10' : 'hover:bg-black/[0.04]'}`}
                              onMouseDown={(e) => {
                                e.preventDefault();
                                insertMention(candidate);
                              }}
                            >
                              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${candidate.node_type === 'user' ? 'bg-apple-blue text-white' : 'bg-black/[0.07] text-black/65'}`}>
                                {candidate.node_type === 'user' ? 'U' : 'A'}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-[13px] font-semibold text-[#1d1d1f]">{candidate.display_name}</span>
                                <span className="block text-[11px] text-black/38">{candidate.node_type} · {candidate.status}</span>
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                    <textarea
                      ref={messageInputRef}
                      className="min-h-[36px] flex-1 resize-none bg-transparent px-3 py-1.5 text-[14px] leading-5 text-black/80 outline-none placeholder:text-black/35"
                      value={messageText}
                      onChange={(e) => {
                        setMessageText(e.target.value);
                        updateMentionRange(e.target.value, e.target.selectionStart);
                      }}
                      onSelect={(e) => updateMentionRange(e.currentTarget.value, e.currentTarget.selectionStart)}
                      onKeyDown={(e) => {
                        if (mentionRange && mentionCandidates.length > 0) {
                          if (e.key === 'ArrowDown') {
                            e.preventDefault();
                            setActiveMentionIndex((index) => (index + 1) % mentionCandidates.length);
                            return;
                          }
                          if (e.key === 'ArrowUp') {
                            e.preventDefault();
                            setActiveMentionIndex((index) => (index - 1 + mentionCandidates.length) % mentionCandidates.length);
                            return;
                          }
                          if ((e.key === 'Enter' || e.key === 'Tab') && !e.nativeEvent.isComposing) {
                            e.preventDefault();
                            insertMention(mentionCandidates[activeMentionIndex]);
                            return;
                          }
                          if (e.key === 'Escape') {
                            e.preventDefault();
                            setMentionRange(null);
                            return;
                          }
                        }
                        if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return;
                        e.preventDefault();
                        void publishMessage();
                      }}
                      placeholder="@agent_name 에게 메시지 보내기"
                    />
                    <button className="btn-primary !h-9 !rounded-[10px] !px-4 !py-0" onClick={() => void publishMessage()}>Send</button>
                  </div>
                  {publishResult && (
                    <p className="mt-2 text-[11px] text-black/38">
                      Last routing: queued={String(publishResult.routing.queued)} · receipts={publishResult.routing.receipt_ids.length}
                    </p>
                  )}
                </div>
              </>
	            ) : workspaceMode === 'board' ? (
	              <CityLearnBoardView
	                detail={detail}
	                simulation={cityLearnSimulation}
	                onSendMessage={(text) => publishMessage(text)}
	                baselineModel={cityLearnBaselineModel}
	                onBaselineModelChange={setCityLearnBaselineModel}
	                agentMeshMode={cityLearnAgentMeshMode}
	                onAgentMeshModeChange={setCityLearnAgentMeshMode}
	                useLLMPlanner={cityLearnUseLLMPlanner}
	                onUseLLMPlannerChange={setCityLearnUseLLMPlanner}
	                isMeshChesca={meshChescaWorkspace}
	                meshChescaScenario={meshChescaScenario}
	                onMeshChescaScenarioChange={setMeshChescaScenario}
	                onDetailRefresh={refreshWorkspaceDetail}
	              />
            ) : (
              <div className="min-h-0 flex-1 bg-[#eef0f4] p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap gap-2">
                    {(['all', 'active', 'processing', 'idle', 'error'] as const).map((filter) => (
                      <button
                        key={filter}
                        className={`rounded-full px-3 py-1.5 text-[12px] font-medium ${mapFilter === filter ? 'bg-apple-blue text-white' : 'bg-white text-black/55 shadow-sm'}`}
                        onClick={() => setMapFilter(filter)}
                      >
                        {filter}
                      </button>
                    ))}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {detail.user_can_manage && (
                      <>
                        <button
                          className="rounded-[10px] bg-white px-3 py-1.5 text-[12px] font-semibold text-[#d70015] shadow-sm disabled:opacity-40"
                          disabled={!selectedMapEdgeId}
                          onClick={deleteSelectedTopologyEdge}
                        >
                          Delete edge
                        </button>
                        <button
                          className="rounded-[10px] bg-apple-blue px-3 py-1.5 text-[12px] font-semibold text-white shadow-sm disabled:opacity-40"
                          disabled={topologySaving || (!pendingTopologyEdges.length && !removedTopologyEdgeIds.length)}
                          onClick={() => void saveTopologyChanges()}
                        >
                          {topologySaving ? 'Saving...' : 'Save'}
                        </button>
                        {(pendingTopologyEdges.length > 0 || removedTopologyEdgeIds.length > 0) && (
                          <button
                            className="rounded-[10px] bg-white px-3 py-1.5 text-[12px] font-medium text-black/50 shadow-sm"
                            onClick={cancelTopologyChanges}
                          >
                            Cancel
                          </button>
                        )}
                      </>
                    )}
                    <p className="text-[12px] text-black/45">
                      {mapNodes.length} nodes · {mapEdges.length} edges
                      {pendingTopologyEdges.length > 0 || removedTopologyEdgeIds.length > 0
                        ? ` · +${pendingTopologyEdges.length} / -${removedTopologyEdgeIds.length}`
                        : ''}
                    </p>
                  </div>
                </div>
                <div className="h-[calc(100%-44px)] overflow-hidden rounded-[18px] border border-black/10 bg-white">
                  <style>{`
                    @keyframes meshEdgeBlink { 0%,100% { stroke: #0071e3; } 50% { stroke: #ff3b30; } }
                    .react-flow__edge.edge-live .react-flow__edge-path {
                      animation: meshEdgeBlink 1s ease-in-out infinite !important;
                      stroke-width: 3px !important;
                    }
                    .react-flow__edge.edge-live .react-flow__edge-text { fill: #ff3b30; font-weight: 700; }
                  `}</style>
                  <ReactFlow
                    nodes={mapNodes}
                    edges={mapEdges}
                    onNodesChange={onMapNodesChange}
                    onEdgesChange={onMapEdgesChange}
                    onConnect={onTopologyConnect}
                    onNodeClick={onTopologyNodeClick}
                    onEdgeClick={onTopologyEdgeClick}
                    fitView
                    minZoom={0.25}
                    maxZoom={1.8}
                    nodesDraggable
                    nodesConnectable={detail.user_can_manage}
                    edgesFocusable
                  >
                    <Background color="#d1d1d6" gap={18} />
                    <Controls />
                    <MiniMap
                      nodeColor={(node) => topologyStatusTone(String(node.data.status || 'idle') as 'active' | 'processing' | 'idle' | 'error')}
                      pannable
                      zoomable
                    />
                  </ReactFlow>
                </div>
              </div>
            )}
          </main>

          {inspectorOpen && (
            <aside className="min-h-0 overflow-y-auto border-t border-white/10 bg-[#17181c] p-5 xl:border-l xl:border-t-0">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.16em] text-white/35">Inspector</p>
                  <h2 className="mt-1 text-[17px] font-semibold text-white">
                    {inspectorMode === 'message'
                      ? 'Message Details'
                      : inspectorMode === 'logs'
                        ? 'Execution Logs'
                        : selectedMapNode?.data.nodeType === 'user'
                          ? 'User Node Info'
                          : 'Agent Info'}
                  </h2>
                </div>
                <button className="text-[20px] text-white/45 hover:text-white" onClick={() => setInspectorOpen(false)}>×</button>
              </div>

              {inspectorMode === 'message' && expandedMessage ? (
                <InspectorSection title="Structured Message">
                  <InspectorKV label="Natural output" value={bodyPreview(expandedMessage.body_ref)} />
                  <InspectorKV label="Domain / intent" value={`${expandedMessage.domain || '-'} / ${expandedMessage.intent || '-'}`} />
                  <InspectorKV label="Priority" value={expandedMessage.priority} />
                  <InspectorKV label="Receipts" value={`${expandedMessage.receipt_count}`} />
                  <InspectorKV label="Queued" value={String(expandedMessage.queued)} />
                  <pre className="mt-3 max-h-[260px] overflow-auto rounded-[12px] bg-black/28 p-3 text-[11px] leading-5 text-white/58">
                    {JSON.stringify(expandedMessage, null, 2)}
                  </pre>
                </InspectorSection>
              ) : inspectorMode === 'logs' ? (
                <>
                  {selectedGoal && (
                    <InspectorSection title="Goal Details">
                      <InspectorKV label="Goal" value={selectedGoal.name} />
                      <InspectorKV label="Status / progress" value={`${selectedGoal.state} / ${selectedGoal.progress}%`} />
                      <InspectorKV label="Priority" value={selectedGoal.priority} />
                      <InspectorKV label="Assigned agents" value={`${selectedGoal.assigned_agent_ids.length}`} />
                      <InspectorKV label="Success criteria" value={selectedGoal.success_criteria || '-'} />
                    </InspectorSection>
                  )}
                  <InspectorSection title="Execution Summary">
                    <InspectorKV label="Recent messages" value={`${activeMessages.length}`} />
                    <InspectorKV label="Active instances" value={`${detail.active_agent_count}`} />
                    <InspectorKV label="Last routing receipts" value={`${publishResult?.routing.receipt_ids.length || 0}`} />
                    {selectedMapEdge && (
                      <>
                        <InspectorKV label="Selected edge" value={selectedMapEdge.id} />
                        <InspectorKV label="Relation" value={String(selectedMapEdge.data?.relation_type || selectedMapEdge.label || '-')} />
                        <InspectorKV label="Status" value={`${String(selectedMapEdge.data?.status || '-')}${selectedMapEdge.data?.pending ? ' · pending' : ''}`} />
                        <InspectorKV label="Source → Target" value={`${String(selectedMapEdge.data?.sourceName || selectedMapEdge.source)} → ${String(selectedMapEdge.data?.targetName || selectedMapEdge.target)}`} />
                        {detail.user_can_manage && (
                          <button
                            className="mt-2 w-full rounded-[10px] bg-[#ff453a]/15 px-3 py-2 text-[12px] font-semibold text-[#ff9f0a] hover:bg-[#ff453a]/20"
                            onClick={deleteSelectedTopologyEdge}
                          >
                            Delete selected edge
                          </button>
                        )}
                      </>
                    )}
                  </InspectorSection>
                  <InspectorSection title="Graph Relationships">
                    <div className="space-y-2">
                      {mapEdges.length === 0 ? (
                        <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                          구독 관계가 없습니다.
                        </div>
                      ) : (
                        mapEdges.slice(0, 8).map((edge) => (
                          <div key={edge.id} className="rounded-[12px] bg-white/[0.04] px-3 py-2 text-[12px] leading-5 text-white/58">
                            <span className="font-medium text-white/76">{String(edge.data?.sourceName || edge.source)}</span>
                            <span className="text-white/32"> → </span>
                            <span className="font-medium text-white/76">{String(edge.data?.targetName || edge.target)}</span>
                            <span className="ml-2 text-white/35">{String(edge.data?.status || '-')}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </InspectorSection>
                </>
              ) : (
                <>
                  <InspectorSection title={selectedMapNode?.data.nodeType === 'user' ? 'User Node' : 'Agent Configuration'}>
                    {selectedMapNode?.data.nodeType === 'user' ? (
                      <>
                        <InspectorKV label="Name" value={String(selectedMapNode.data.displayName || 'User node')} />
                        <InspectorKV label="Node type" value="user" />
                        <InspectorKV label="User id" value={String(selectedMapNode.data.refId || '-')} />
                      </>
                    ) : (
                      <>
                        <InspectorKV label="Name" value={String(selectedMapNode?.data.displayName || selectedAgent?.agent.name || 'No agent selected')} />
                        <InspectorKV label="Instances" value={selectedMapNode?.data.buildingId ? '1' : `${selectedAgent?.quantity || 0}`} />
                        {selectedMapNode?.data.buildingId && (
                          <InspectorKV label="Building" value={cityLearnBuildingLabel(String(selectedMapNode.data.buildingId))} />
                        )}
                        <InspectorKV label="Version" value={selectedAgent?.agent.version || '-'} />
                        <InspectorKV label="Visibility" value={selectedAgent?.agent.visibility || '-'} />
                        <InspectorKV label="Tools" value={selectedAgent?.agent.tools.join(', ') || '-'} />
                        {detail.user_can_manage && selectedAgent && (
                          <div className="mt-3 rounded-[14px] bg-white/[0.04] p-3">
                            <div className="mb-2 flex items-center justify-between gap-2">
                              <span className="text-[12px] font-semibold text-white/70">MCP Tools</span>
                              <button
                                className="rounded-[9px] bg-apple-blue px-2.5 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
                                disabled={toolSavingAgentId === selectedAgent.agent.agent_id}
                                onClick={() => void saveAgentTools(selectedAgent.agent.agent_id)}
                              >
                                {toolSavingAgentId === selectedAgent.agent.agent_id ? 'Saving' : 'Save tools'}
                              </button>
                            </div>
                            <div className="max-h-[190px] space-y-1.5 overflow-y-auto">
                              {toolCatalog.length === 0 ? (
                                <div className="rounded-[10px] bg-black/20 px-3 py-2 text-[12px] text-white/42">사용 가능한 도구가 없습니다.</div>
                              ) : (
                                toolCatalog.map((tool) => {
                                  const agentId = selectedAgent.agent.agent_id;
                                  const draftTools = agentToolDrafts[agentId] || selectedAgent.agent.tools;
                                  const checked = draftTools.includes(tool.id);
                                  return (
                                    <label key={tool.id} className={`flex cursor-pointer items-start gap-2 rounded-[10px] px-2.5 py-2 ${checked ? 'bg-apple-blue/15' : 'bg-black/16 hover:bg-white/[0.06]'}`}>
                                      <input
                                        type="checkbox"
                                        className="mt-0.5"
                                        checked={checked}
                                        onChange={() => toggleAgentToolDraft(agentId, tool.id)}
                                      />
                                      <span className="min-w-0 flex-1">
                                        <span className="block truncate text-[12px] font-medium text-white/76">{tool.name}</span>
                                        <span className="block truncate text-[11px] text-white/36">{tool.id}</span>
                                      </span>
                                    </label>
                                  );
                                })
                              )}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                    {selectedMapNode && (
                      <>
                        <InspectorKV label="Map status" value={String(selectedMapNode.data.status || '-')} />
                        <InspectorKV label="Recent node messages" value={String(selectedMapNode.data.messageCount || 0)} />
                        <InspectorKV label="Incoming subscriptions" value={String(selectedMapNode.data.incoming || 0)} />
                        <InspectorKV label="Outgoing subscriptions" value={String(selectedMapNode.data.outgoing || 0)} />
                      </>
                    )}
                  </InspectorSection>
                  {selectedMapNode && (
                    <InspectorSection title="Subscribe Node">
                      {detail.user_can_manage && selectedMapNode.data.nodeType === 'agent' && selectedMapNode.data.canEditTopology !== false ? (
                        <div className="space-y-2">
                          {selectedSubscribableNodes.map((node) => {
                            const checked = topologyEdges.some(
                              (edge) => edge.source_node_id === selectedMapNode.id && edge.target_node_id === node.node_id
                            );
                            return (
                              <label key={node.node_id} className={`flex cursor-pointer items-center gap-3 rounded-[12px] px-3 py-2 ${checked ? 'bg-apple-blue/15' : 'bg-white/[0.04] hover:bg-white/[0.07]'}`}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(event) => setTopologySubscriptionDraft(selectedMapNode.id, node.node_id, event.target.checked)}
                                />
                                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${node.node_type === 'user' ? 'bg-apple-blue text-white' : 'bg-white/10 text-white/70'}`}>
                                  {node.node_type === 'user' ? 'U' : 'A'}
                                </span>
                                <span className="min-w-0 flex-1">
                                  <span className="block truncate text-[13px] font-medium text-white/76">{node.display_name}</span>
                                  <span className="block text-[11px] text-white/38">{node.node_type} · {node.status}</span>
                                </span>
                              </label>
                            );
                          })}
                        </div>
                      ) : selectedSubscribedNodes.length === 0 ? (
                        <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                          현재 이 노드가 구독 중인 노드가 없습니다.
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {selectedSubscribedNodes.map(({ edge, node }) => (
                            <div key={edge.id} className="flex items-center gap-3 rounded-[12px] bg-white/[0.04] px-3 py-2">
                              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${node?.data.nodeType === 'user' ? 'bg-apple-blue text-white' : 'bg-white/10 text-white/70'}`}>
                                {node?.data.nodeType === 'user' ? 'U' : 'A'}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-[13px] font-medium text-white/76">{String(node?.data.displayName || '-')}</span>
                                <span className="block text-[11px] text-white/38">{String(node?.data.nodeType || '-')} · {String(edge.data?.status || '-')}</span>
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </InspectorSection>
                  )}
                  <InspectorSection title="Workspace Members">
                    {workspaceMembers.length === 0 ? (
                      <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                        참여 중인 사용자가 없습니다.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {workspaceMembers.map((member) => (
                          <div key={member.node_id} className="flex items-center gap-3 rounded-[12px] bg-white/[0.04] px-3 py-2">
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-apple-blue text-[12px] font-semibold text-white">
                              {member.display_name.charAt(0)}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-[13px] font-medium text-white/76">{member.display_name}</span>
                              <span className="block text-[11px] text-white/38">{member.status} · {member.ref_id.slice(0, 8)}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </InspectorSection>
                  <InspectorSection title="Current State / Memory">
                    <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                      Memory snapshot and runtime state will appear here when persistent agent memory is connected.
                    </div>
                  </InspectorSection>
                </>
              )}
            </aside>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in font-apple">
      <Header
        title="워크스페이스"
        subtitle="공장, 도시 데이터, 운영 환경을 다중 에이전트 메시 구조로 관리합니다."
        actionLabel={canCreateWorkspace ? '새 워크스페이스 생성' : undefined}
        onAction={canCreateWorkspace ? () => setView('create') : undefined}
        secondaryActionLabel="워크스페이스 참여"
        onSecondaryAction={openJoinWorkspace}
      />
      {error && <Alert message={error} />}
      {joinOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4 backdrop-blur-sm">
          <div className="w-full max-w-4xl rounded-[18px] border border-white/10 bg-[#17181c] p-6 shadow-[0_24px_90px_rgba(0,0,0,0.48)]">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-[22px] font-semibold text-white">워크스페이스 참여</h2>
                <p className="mt-1 text-[13px] text-white/50">전체 워크스페이스 목록에서 참여할 환경을 선택하고 참여 코드를 입력하세요.</p>
              </div>
              <button className="text-[22px] text-white/45 hover:text-white" onClick={() => setJoinOpen(false)}>×</button>
            </div>
            <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-end">
              <Field label="참여 코드">
                <input className="input-field" value={joinCode} onChange={(e) => setJoinCode(e.target.value)} placeholder="1234" />
              </Field>
              <button className="btn-secondary md:mb-0.5" onClick={openJoinWorkspace} disabled={joinLoading}>
                {joinLoading ? '새로고침 중...' : '목록 새로고침'}
              </button>
            </div>
            {joinError && <Alert message={joinError} />}
            {joinLoading ? (
              <div className="py-12 text-center text-white/50">참여 가능한 워크스페이스를 불러오는 중...</div>
            ) : joinableWorkspaces.length === 0 ? (
              <div className="rounded-[14px] border border-white/10 bg-white/[0.04] p-6 text-[14px] text-white/55">참여 가능한 워크스페이스가 없습니다.</div>
            ) : (
              <div className="max-h-[56vh] overflow-y-auto">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {joinableWorkspaces.map((workspace) => (
                    <div key={workspace.workspace_id} className="rounded-[14px] border border-white/10 bg-apple-surface2 p-4">
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h3 className="truncate text-[16px] font-semibold text-white">{workspace.name || '워크스페이스'}</h3>
                          <p className="mt-1 line-clamp-2 text-[13px] text-white/55">{workspace.description || '환경 설명 없음'}</p>
                        </div>
                        <span className="shrink-0 rounded-full bg-white/10 px-2 py-1 text-[11px] text-white/55">{workspace.access_status}</span>
                      </div>
                      <div className="mb-4 grid grid-cols-3 gap-2 text-[11px] text-white/45">
                        <span className="rounded-[9px] bg-white/[0.04] px-2 py-1.5">에이전트 {workspace.agent_count}</span>
                        <span className="rounded-[9px] bg-white/[0.04] px-2 py-1.5">사용자 {workspace.user_count}</span>
                        <span className="rounded-[9px] bg-white/[0.04] px-2 py-1.5">활동 {workspace.recent_activity_count}</span>
                      </div>
                      <button
                        className="btn-primary w-full disabled:opacity-45"
                        disabled={workspace.user_can_access || joiningId === workspace.workspace_id}
                        onClick={() => void joinWorkspace(workspace)}
                      >
                        {workspace.user_can_access ? '이미 참여됨' : joiningId === workspace.workspace_id ? '참여 중...' : '참여'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {loading ? (
        <div className="py-20 text-center text-white/50">불러오는 중...</div>
      ) : workspaces.length === 0 ? (
        <div className="bg-apple-surface1 rounded-[18px] p-8 border border-white/5">
          <h2 className="text-[24px] font-semibold text-white mb-2">현재 할당된 환경이 없습니다</h2>
          <p className="text-[14px] text-white/50">워크스페이스 참여를 통해 접근 권한을 얻으면 목록에 표시됩니다.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 mb-8">
          {workspaces.map((workspace) => (
            <button key={workspace.workspace_id} onClick={() => openDetail(workspace.workspace_id)} className="text-left bg-apple-surface1 rounded-[18px] p-6 border border-white/5 hover:border-apple-blue/40 transition-all">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h2 className="text-[21px] font-semibold text-white">{workspace.name}</h2>
                  <p className="text-[13px] text-white/50 mt-1 line-clamp-2">{workspace.description || '환경 설명 없음'}</p>
                </div>
                <span className="text-[11px] text-apple-blue bg-apple-blue/10 px-2 py-1 rounded-full">{workspace.access_status}</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-[12px] text-white/55">
                <span className="rounded-[10px] bg-white/[0.04] px-3 py-2">에이전트 {workspace.agent_count}</span>
                <span className="rounded-[10px] bg-white/[0.04] px-3 py-2">사용자 {workspace.user_count}</span>
                <span className="rounded-[10px] bg-white/[0.04] px-3 py-2">최근 활동 {workspace.recent_activity_count}</span>
              </div>
            </button>
          ))}
        </div>
      )}
      {canGrantAccess && accessRequests.length > 0 && (
        <section className="mt-6 bg-apple-surface1 rounded-[18px] p-6 border border-white/5">
          <h2 className="text-[17px] font-semibold text-white mb-3">권한 승인 대기</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {accessRequests.map((request) => (
              <div key={request.request_id} className="bg-apple-surface2 rounded-[12px] p-4 border border-white/10">
                <p className="text-[12px] text-white/45 break-all">{request.workspace_id}</p>
                <p className="text-[13px] text-white/70 my-2">{request.reason || '사유 없음'}</p>
                <div className="flex gap-3">
                  <button className="text-[13px] text-[#34c759]" onClick={() => decideRequest(request.request_id, 'approve')}>승인</button>
                  <button className="text-[13px] text-[#ff3b30]" onClick={() => decideRequest(request.request_id, 'reject')}>반려</button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Header({
  title,
  subtitle,
  actionLabel,
  onAction,
  secondaryActionLabel,
  onSecondaryAction,
}: {
  title: string;
  subtitle: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
}) {
  return (
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8 pb-6 border-b border-white/10">
      <div>
        <h1 className="text-[40px] font-semibold text-white tracking-[-0.28px] leading-[1.07] mb-2">{title}</h1>
        <p className="text-[17px] text-white/60 tracking-[-0.374px] leading-[1.47]">{subtitle}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {secondaryActionLabel && onSecondaryAction && <button className="btn-secondary" onClick={onSecondaryAction}>{secondaryActionLabel}</button>}
        {actionLabel && onAction && <button className="btn-primary" onClick={onAction}>{actionLabel}</button>}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12px] text-white/60 uppercase mb-1.5">{label}</span>
      {children}
    </label>
  );
}

function TemplateMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[10px] bg-black/20 px-3 py-2">
      <span className="block text-[11px] text-white/38">{label}</span>
      <span className="block truncate text-[13px] font-semibold text-white/82">{value}</span>
    </div>
  );
}

function CityLearnSimulationControlBar({
  simulation,
  onPlay,
  onPause,
  onReset,
  onTickRateChange,
  agentMeshMode,
}: {
  simulation: CityLearnSimulationState;
  onPlay: () => void;
  onPause: () => void;
  onReset: () => void;
  onTickRateChange: (tickRateLabel: string) => void;
  agentMeshMode: CityLearnAgentMeshMode;
}) {
  const progress = cityLearnProgressPercent(simulation.step);
  const running = simulation.status === 'running';
  const isGridMode = agentMeshMode === 'deterministic' || agentMeshMode === 'llm_planner';
  const isMacroMode = agentMeshMode === 'macro_mesh' || agentMeshMode === 'macro_mesh_v2';
  const isAsyncMode = isGridMode || isMacroMode;
  const isWaitingForPlan =
    isAsyncMode
    && running
    && ((isGridMode && simulation.pendingGridAgentStep === simulation.step)
      || (isMacroMode && simulation.pendingMacroMeshStep === simulation.step));
  const waitingSubject = agentMeshMode === 'macro_mesh_v2'
    ? '17 building 협상 + rollout/introspect'
    : agentMeshMode === 'macro_mesh'
      ? '17 building 협상'
      : agentMeshMode === 'llm_planner'
        ? 'LLM'
        : '규칙 평가';
  const playLabel = isWaitingForPlan
    ? `Running step ${simulation.step + 1}/${CITYLEARN_TOTAL_STEPS} · ${waitingSubject} 응답 대기 중...`
    : 'Play';

  return (
    <section className="border-b border-black/10 bg-[#fbfbfd] px-5 py-3 shadow-sm">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${running ? 'bg-[#34c759]/14 text-[#248a3d]' : simulation.status === 'completed' ? 'bg-[#0071e3]/12 text-[#005bb5]' : 'bg-black/[0.06] text-black/48'}`}>
              {simulation.status}
            </span>
            <span className="text-[12px] font-semibold text-[#1d1d1f]">
              Step {simulation.step + 1}/{CITYLEARN_TOTAL_STEPS}
            </span>
            <span className="text-[12px] text-black/45">
              {cityLearnSimulationDateLabel(simulation.step)}
            </span>
            {isAsyncMode && (
              <span className="rounded-full bg-[#ff9500]/14 px-2 py-0.5 text-[10px] font-semibold text-[#a05a00]">
                {isMacroMode ? `${agentMeshMode} · 17 building 협상` : `${agentMeshMode} · 직렬 진행`}
              </span>
            )}
          </div>
          {(simulation.gridAgentError || simulation.macroMeshError) && (
            <p className="mt-1 text-[11px] font-medium text-[#d70015]">
              {simulation.gridAgentError || simulation.macroMeshError}
            </p>
          )}
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-black/[0.08]">
            <div className="h-full rounded-full bg-[#0071e3]" style={{ width: `${progress}%` }} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="rounded-[10px] bg-[#0071e3] px-3 py-2 text-[12px] font-semibold text-white shadow-sm disabled:opacity-50"
            onClick={onPlay}
            disabled={running}
            title={isAsyncMode ? '매 step마다 plan/negotiate API 호출 후 응답이 끝나면 직렬 진행' : undefined}
          >
            {playLabel}
          </button>
          <button
            type="button"
            className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-semibold text-black/68 shadow-sm disabled:opacity-45"
            onClick={onPause}
            disabled={!running}
          >
            Pause
          </button>
          <button
            type="button"
            className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-semibold text-black/50 shadow-sm"
            onClick={onReset}
          >
            Reset
          </button>
          <div
            className={`ml-0 flex rounded-[12px] border border-black/10 p-1 xl:ml-2 ${isAsyncMode ? 'bg-black/[0.06] opacity-50' : 'bg-black/[0.04]'}`}
            title={isAsyncMode ? '이 mode에서는 plan/negotiate 응답 시간이 step 간격을 결정하므로 속도 조절이 비활성화됩니다.' : undefined}
          >
            {CITYLEARN_TICK_RATES.map((rate) => (
              <button
                key={rate.label}
                type="button"
                disabled={isAsyncMode}
                className={`rounded-[9px] px-2.5 py-1.5 text-[11px] font-semibold ${simulation.tickRate.label === rate.label ? 'bg-white text-[#0071e3] shadow-sm' : 'text-black/42'} ${isAsyncMode ? 'cursor-not-allowed' : ''}`}
                onClick={() => onTickRateChange(rate.label)}
              >
                {rate.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function NegotiationTracePanel({
  run,
  pendingStep,
  error,
  currentStep,
  useLLMProposers,
  onToggleLLMProposers,
}: {
  run: CityLearnMacroMeshNegotiateResponse | null;
  pendingStep: number | null;
  error: string | null;
  currentStep: number;
  useLLMProposers: boolean;
  onToggleLLMProposers: (next: boolean) => void;
}) {
  const [openRounds, setOpenRounds] = useState<Record<number, boolean>>({});

  if (!run && !pendingStep && !error) {
    return (
      <section className="mb-4 rounded-[18px] border border-dashed border-black/15 bg-white/60 p-4 text-[12px] text-black/55">
        macro_mesh mode가 선택되었습니다. Play 버튼을 누르면 매 step마다 17 Building Battery Agent가 병렬로 proposal을 발의하고, Coordinator가 mean_field/conflict를 산출해 round 2 재제안을 유도합니다. 메시지 피드에 라운드별 trace가 누적됩니다.
      </section>
    );
  }

  const approved = run?.validation.approved ?? false;
  const badgeClass = approved
    ? 'bg-[#34c759]/14 text-[#248a3d]'
    : run ? 'bg-[#ff453a]/14 text-[#b42318]' : 'bg-[#ff9500]/14 text-[#a05a00]';

  return (
    <section className="mb-4 rounded-[18px] border border-black/10 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-black/38">MACRO-Mesh Negotiation</p>
          <h4 className="mt-1 text-[15px] font-semibold text-[#1d1d1f]">
            Step {(run?.topology.step ?? currentStep) + 1} · {run?.rounds.length ?? 0} rounds
          </h4>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 rounded-[10px] border border-black/10 bg-white px-2 py-1 text-[11px] font-medium text-black/60">
            <input type="checkbox" checked={useLLMProposers} onChange={(e) => onToggleLLMProposers(e.target.checked)} />
            LLM proposers
          </label>
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${badgeClass}`}>
            {run?.validation.status ?? (pendingStep != null ? 'pending' : 'idle')}
          </span>
        </div>
      </div>

      {error && (
        <p className="mt-2 rounded-[10px] bg-[#ff453a]/10 px-3 py-2 text-[11px] font-medium text-[#b42318]">
          {error}
        </p>
      )}

      {run && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <KV label="Score before" value={run.validation.score_before.toFixed(2)} />
            <KV label="Score after" value={run.validation.score_after.toFixed(2)} />
            <KV
              label="Δ"
              value={`${(run.validation.score_after - run.validation.score_before).toFixed(2)}`}
              tone={run.validation.score_after <= run.validation.score_before ? 'green' : 'red'}
            />
            <KV label="Merged actions" value={String(run.merged_plan.actions.length)} />
          </div>
          <p className="mt-3 rounded-[10px] bg-black/[0.04] px-3 py-2 text-[12px] leading-5 text-black/70">
            {run.operator_summary}
          </p>

          <div className="mt-3 space-y-2">
            {run.rounds.map((r, idx) => {
              const isOpen = openRounds[r.round_index] ?? (idx === run.rounds.length - 1);
              return (
                <div key={`round-${r.round_index}`} className="rounded-[12px] border border-black/[0.08] bg-[#f7f8fb]">
                  <button
                    type="button"
                    onClick={() => setOpenRounds((prev) => ({ ...prev, [r.round_index]: !isOpen }))}
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-[12px] font-semibold text-[#1d1d1f]"
                  >
                    <span>{isOpen ? '▾' : '▸'} Round {r.round_index + 1} · {r.proposals.length} proposals · {r.elapsed_seconds.toFixed(2)}s</span>
                    <span className="text-[11px] font-medium text-black/55">
                      discharge {r.mean_field.discharge_count} · charge {r.mean_field.charge_count} · hold {r.mean_field.hold_count}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-3">
                      <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-4 text-[11px]">
                        <KV label="mean action" value={r.mean_field.mean_action.toFixed(2)} />
                        <KV label="|action| std" value={r.mean_field.stddev_action.toFixed(2)} />
                        <KV label="critical SOC %" value={`${(r.mean_field.critical_soc_ratio * 100).toFixed(0)}%`} />
                        <KV label="Δ district kWh" value={r.mean_field.expected_district_load_delta_kwh.toFixed(2)} />
                      </div>
                      {r.conflicts.length > 0 && (
                        <div className="mb-2">
                          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-black/42">Conflicts ({r.conflicts.length})</p>
                          <ul className="mt-1 space-y-1">
                            {r.conflicts.map((c, i) => (
                              <li key={`c-${i}`} className="text-[11px] text-[#b35d00]">
                                <span className="font-semibold">{c.type}</span> (severity {c.severity.toFixed(2)}) — {c.description}
                                {c.building_ids.length > 0 && <span className="block text-black/45">└ {c.building_ids.join(', ')}</span>}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <details>
                        <summary className="cursor-pointer text-[11px] font-medium text-black/55">Proposals ({r.proposals.length})</summary>
                        <ul className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
                          {r.proposals.map((p) => (
                            <li key={`${r.round_index}-${p.building_id}`} className="rounded-[8px] bg-white px-2 py-1 text-[11px] text-black/68">
                              <span className="font-semibold text-[#1d1d1f]">{p.building_id}</span>:{' '}
                              <span className={`font-semibold ${p.proposed_action > 0.05 ? 'text-[#005bb5]' : p.proposed_action < -0.05 ? 'text-[#b35d00]' : 'text-black/45'}`}>
                                {p.proposed_action.toFixed(2)}
                              </span>{' '}
                              <span className="text-black/45">({p.kind}, conf {p.confidence.toFixed(2)})</span>
                              <span className="block text-[10px] text-black/45 truncate">{p.rationale}</span>
                            </li>
                          ))}
                        </ul>
                      </details>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}

function GridAgentValidationPanel({
  run,
  pendingStep,
  error,
  currentStep,
  modeLabel,
  showLLMToggle,
  useLLMPlanner,
  onToggleLLMPlanner,
}: {
  run: CityLearnGridAgentPlanResponse | null;
  pendingStep: number | null;
  error: string | null;
  currentStep: number;
  modeLabel?: string;
  showLLMToggle: boolean;
  useLLMPlanner: boolean;
  onToggleLLMPlanner: (next: boolean) => void;
}) {
  const [showIterationTrace, setShowIterationTrace] = useState(false);
  if (!run && !pendingStep && !error) {
    return (
      <section className="mb-4 rounded-[18px] border border-dashed border-black/15 bg-white/60 p-4 text-[12px] text-black/55">
        {modeLabel ?? 'Grid-Agent'} mode가 선택되었습니다. Play 버튼을 누르면 매 step마다 backend Grid-Agent plan API가 호출됩니다.
        한 step의 응답이 끝난 뒤 다음 step으로 자동 진행됩니다.
      </section>
    );
  }

  const approved = run?.validation.approved ?? false;
  const status = run?.validation.status ?? (pendingStep != null ? 'pending' : 'idle');
  const badgeClass = approved
    ? 'bg-[#34c759]/14 text-[#248a3d]'
    : status === 'rejected'
    ? 'bg-[#ff453a]/14 text-[#b42318]'
    : 'bg-[#ff9500]/14 text-[#a05a00]';

  return (
    <section className="mb-4 rounded-[18px] border border-black/10 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-black/38">Grid-Agent Plan{modeLabel ? ` · ${modeLabel}` : ''}</p>
          <h4 className="mt-1 text-[15px] font-semibold text-[#1d1d1f]">
            Step {(run?.topology.step ?? currentStep) + 1} 결과
          </h4>
        </div>
        <div className="flex items-center gap-2">
          {showLLMToggle && (
            <label className="flex items-center gap-1.5 rounded-[10px] border border-black/10 bg-white px-2 py-1 text-[11px] font-medium text-black/60">
              <input
                type="checkbox"
                checked={useLLMPlanner}
                onChange={(event) => onToggleLLMPlanner(event.target.checked)}
              />
              LLM Planner (Phase 2)
            </label>
          )}
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${badgeClass}`}>
            {status}
          </span>
        </div>
      </div>

      {error && (
        <p className="mt-2 rounded-[10px] bg-[#ff453a]/10 px-3 py-2 text-[11px] font-medium text-[#b42318]">
          {error}
        </p>
      )}

      {run && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <KV label="Score before" value={run.validation.score_before.toFixed(2)} />
            <KV label="Score after" value={run.validation.score_after.toFixed(2)} />
            <KV
              label="Δ"
              value={`${(run.validation.score_after - run.validation.score_before).toFixed(2)}`}
              tone={run.validation.score_after <= run.validation.score_before ? 'green' : 'red'}
            />
            <KV label="Actions" value={String(run.final_plan.actions.length)} />
          </div>

          <p className="mt-3 rounded-[10px] bg-black/[0.04] px-3 py-2 text-[12px] leading-5 text-black/70">
            {run.operator_summary}
          </p>

          {run.initial_violations.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-black/42">
                Initial violations ({run.initial_violations.length})
              </p>
              <ul className="mt-1 space-y-1">
                {run.initial_violations.slice(0, 6).map((v, idx) => (
                  <li key={`${v.type}-${v.building_id ?? 'district'}-${idx}`} className="text-[11px] text-black/65">
                    <span className="font-semibold text-[#b35d00]">[{v.type}]</span>{' '}
                    {v.building_id ? `${v.building_id} · ` : ''}{v.description}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {run.final_plan.actions.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-black/42">
                Proposed actions
              </p>
              <ul className="mt-1 space-y-1">
                {run.final_plan.actions.slice(0, 8).map((a) => {
                  const rejectedBuilding = run.validation.new_violations.some(
                    (v) => v.building_id === a.building_id && (v.type === 'soc' || v.type === 'invalid_action'),
                  );
                  return (
                    <li
                      key={`${a.building_id}:${a.action}`}
                      className={`flex items-center gap-2 rounded-[8px] px-2 py-1 text-[11px] ${rejectedBuilding ? 'bg-[#ff453a]/10 text-[#b42318]' : 'text-black/68'}`}
                      title={`expected: ${a.expected_effect}`}
                    >
                      <span className="font-semibold text-[#1d1d1f]">{a.building_id}</span>
                      <span className={`font-semibold ${a.mode === 'charge' ? 'text-[#005bb5]' : a.mode === 'discharge' ? 'text-[#b35d00]' : 'text-black/45'}`}>
                        {a.mode} {a.action.toFixed(2)}
                      </span>
                      <span className="flex-1 truncate text-black/55">{a.reason}</span>
                      <span
                        className="rounded-full bg-black/[0.06] px-1.5 text-[10px] font-semibold text-black/55"
                        title={`confidence ${a.confidence.toFixed(2)}`}
                      >
                        {Math.round(a.confidence * 100)}%
                      </span>
                      {rejectedBuilding && (
                        <span className="rounded-full bg-[#ff453a]/20 px-1.5 text-[10px] font-semibold text-[#b42318]">rejected</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {(run.validation.new_violations.length > 0 || run.validation.remaining_violations.length > 0) && (
            <p className="mt-3 text-[11px] text-black/55">
              feedback: {run.validation.feedback}
            </p>
          )}

          {run.iterations.length > 0 && (
            <div className="mt-3 border-t border-black/[0.06] pt-3">
              <button
                type="button"
                onClick={() => setShowIterationTrace((value) => !value)}
                className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-black/55 hover:text-[#0071e3]"
              >
                <span>{showIterationTrace ? '▾' : '▸'}</span>
                Iteration trace ({run.iterations.length})
              </button>
              {showIterationTrace && (
                <ol className="mt-2 space-y-2">
                  {run.iterations.map((iter, idx) => (
                    <li
                      key={`iter-${idx}`}
                      className={`rounded-[10px] border px-2.5 py-2 text-[11px] ${iter.validation.approved ? 'border-[#34c759]/35 bg-[#34c759]/5' : 'border-[#ff9500]/35 bg-[#ff9500]/5'}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-[#1d1d1f]">
                          #{iter.iteration} · {iter.planner_kind}
                        </span>
                        <span className="text-black/55">{iter.route_decision || '-'}</span>
                      </div>
                      <p className="mt-1 text-black/60">
                        score {iter.validation.score_before.toFixed(2)} → {iter.validation.score_after.toFixed(2)} ·
                        actions {iter.plan.actions.length} ·
                        feedback: {iter.validation.feedback}
                      </p>
                      {iter.planner_output && (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-[10px] font-medium text-black/45">planner_output</summary>
                          <pre className="mt-1 max-h-40 overflow-auto rounded-[8px] bg-black/[0.04] p-2 text-[10px] leading-4 text-black/65">
                            {JSON.stringify(iter.planner_output, null, 2)}
                          </pre>
                        </details>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function KV({ label, value, tone }: { label: string; value: string; tone?: 'green' | 'red' }) {
  const toneClass = tone === 'green' ? 'text-[#248a3d]' : tone === 'red' ? 'text-[#b42318]' : 'text-[#1d1d1f]';
  return (
    <div className="rounded-[10px] bg-[#f7f8fb] px-3 py-2">
      <span className="block text-[10px] font-semibold uppercase tracking-[0.1em] text-black/42">{label}</span>
      <span className={`mt-1 block text-[13px] font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

function MeshChescaPanel({
  mesh,
  error,
  step,
}: {
  mesh: MeshChescaBoardSnapshot['mesh_chesca'] | null;
  error: string | null;
  step: number;
}) {
  if (error) {
    return (
      <section className="mb-4 rounded-[18px] border border-[#ff453a]/30 bg-[#ff453a]/5 p-4 text-[12px] font-medium text-[#b42318]">
        {error}
      </section>
    );
  }
  if (!mesh) {
    return (
      <section className="mb-4 rounded-[18px] border border-dashed border-black/15 bg-white/60 p-4 text-[12px] text-black/55">
        mesh_chesca 템플릿입니다. Play 버튼을 누르면 실제 CHESCA 런타임이 step별로 구동되며, 각 건물 peer의 flex 협상 trace가 여기에 표시됩니다.
      </section>
    );
  }

  const neg = mesh.negotiation;
  const delta = neg ? neg.negotiated_predicted_grid - neg.official_predicted_grid : 0;
  // 건물(sender)별 마지막 round 메시지만 추출.
  const latestBySender = new Map<number, MeshChescaBoardSnapshot['mesh_chesca']['messages'][number]>();
  for (const msg of mesh.messages) {
    const prev = latestBySender.get(msg.sender);
    if (!prev || msg.round_id >= prev.round_id) latestBySender.set(msg.sender, msg);
  }
  const peerRows = Array.from(latestBySender.values()).sort((a, b) => a.sender - b.sender);

  return (
    <section className="mb-4 rounded-[18px] border border-black/10 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-black/38">MESH-CHESCA Negotiation · {mesh.scenario_label}</p>
          <h4 className="mt-1 text-[15px] font-semibold text-[#1d1d1f]">
            Step {step + 1}{neg ? ` · hour ${neg.hour}` : ''} · {peerRows.length} peers
          </h4>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${neg && neg.changed_peers > 0 ? 'bg-[#34c759]/14 text-[#248a3d]' : 'bg-black/[0.06] text-black/48'}`}>
          {neg ? `${neg.changed_peers}/${neg.active_peers} changed` : 'no negotiation'}
        </span>
      </div>

      {neg && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <KV label="Official grid" value={`${neg.official_predicted_grid.toFixed(2)}`} />
          <KV label="Negotiated grid" value={`${neg.negotiated_predicted_grid.toFixed(2)}`} />
          <KV label="Δ grid (kWh)" value={`${delta.toFixed(3)}`} tone={delta <= 0 ? 'green' : 'red'} />
          <KV label="Shadow signal" value={`${neg.final_shadow_signal.toFixed(3)}`} />
          {typeof neg.total_debt_soc === 'number' && (
            <KV label="Total debt (SOC)" value={`${neg.total_debt_soc.toFixed(3)}`} />
          )}
          {/* outage_mpc_mesh 전용: 정전 위험/예비/긴급방전 */}
          {typeof neg.outage_risk === 'number' && (
            <KV label="Outage risk" value={neg.outage_risk > 0 ? 'HIGH' : 'low'} tone={neg.outage_risk > 0 ? 'red' : 'green'} />
          )}
          {typeof neg.reserve_floor === 'number' && (
            <KV label="Reserve floor (SOC)" value={`${neg.reserve_floor.toFixed(2)}`} tone={neg.reserve_floor > 0 ? 'red' : undefined} />
          )}
          {typeof neg.emergency_deploy === 'number' && neg.emergency_deploy > 0 && (
            <KV label="Emergency discharge" value={`${neg.emergency_deploy} bldg`} tone="red" />
          )}
          <KV label="District target" value={`${neg.district_target.toFixed(2)}`} />
          <KV label="Msgs (logical)" value={`${neg.logical_message_count}`} />
        </div>
      )}

      {peerRows.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-black/42">Peer flex offers (last round)</p>
          <ul className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
            {peerRows.map((p) => {
              const changed = Math.abs(p.proposed_grid - p.official_grid) > 1e-6;
              return (
                <li
                  key={`peer-${p.sender}`}
                  className={`flex items-center gap-2 rounded-[8px] px-2 py-1 text-[11px] ${changed ? 'bg-[#0071e3]/8 text-[#005bb5]' : 'text-black/62'}`}
                >
                  <span className="font-semibold text-[#1d1d1f]">Building_{p.sender + 1}</span>
                  <span className="font-semibold">
                    {p.official_grid.toFixed(2)}{changed ? ` → ${p.proposed_grid.toFixed(2)}` : ''} kWh
                  </span>
                  <span className="ml-auto text-black/45">SOC {(p.soc * 100).toFixed(0)}%</span>
                  {typeof p.debt_soc === 'number' && (
                    <span className="text-[#b35d00]">debt {p.debt_soc.toFixed(2)}</span>
                  )}
                  {p.outage && (
                    <span className="rounded-full bg-[#ff453a]/14 px-1.5 py-0.5 text-[10px] font-semibold text-[#b42318]">정전</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* outage_mpc_mesh 전용: 에이전트 자연어 소통 트레이스 (노트북 step_reports 재현). */}
      {(mesh.agent_reports?.length ?? 0) > 0 && (
        <div className="mt-3 border-t border-black/[0.06] pt-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-black/42">에이전트 자연어 소통 · step {step + 1}</p>
          <ul className="mt-1.5 flex max-h-56 flex-col gap-1 overflow-y-auto pr-1">
            {mesh.agent_reports!.map((r, i) => {
              const isRisk = r.agent === 'outage_risk_agent';
              const isLead = r.agent.endsWith('_agent') && !isRisk;
              const isBuilding = r.agent.startsWith('building_');
              const name = isBuilding ? `Building_${Number(r.agent.split('_')[1]) + 1}` : r.agent;
              const tag = isRisk ? 'outage' : isLead ? r.role : (r.role_ko || r.role);
              return (
                <li
                  key={`rep-${i}-${r.agent}`}
                  className={`flex items-start gap-2 rounded-[8px] px-2 py-1 text-[11px] leading-4 ${
                    isRisk
                      ? (r.reserve_floor && r.reserve_floor > 0 ? 'bg-[#ff453a]/8 text-[#b42318]' : 'bg-[#34c759]/8 text-[#248a3d]')
                      : isLead
                        ? 'bg-[#0071e3]/6 text-[#005bb5]'
                        : r.outage
                          ? 'bg-[#ff453a]/8 text-[#b42318]'
                          : 'text-black/65'
                  }`}
                >
                  <span className="shrink-0 font-semibold text-[#1d1d1f]">{name}</span>
                  <span className="shrink-0 rounded-full bg-black/[0.05] px-1.5 py-0.5 text-[10px] font-medium text-black/55">{tag}</span>
                  {r.llm && (
                    <span className="shrink-0 rounded-full bg-[#5e5ce6]/14 px-1.5 py-0.5 text-[10px] font-semibold text-[#4b48c7]" title="로컬 Qwen 생성">Qwen</span>
                  )}
                  <span className="min-w-0 flex-1">{r.reason}</span>
                  {r.outage && (
                    <span className="shrink-0 rounded-full bg-[#ff453a]/14 px-1.5 py-0.5 text-[10px] font-semibold text-[#b42318]">⚡정전</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

function CityLearnBoardView({
  detail,
  simulation,
  onSendMessage,
  baselineModel,
  onBaselineModelChange,
  agentMeshMode,
  onAgentMeshModeChange,
  useLLMPlanner,
  onUseLLMPlannerChange,
  isMeshChesca = false,
  meshChescaScenario = 'chesca_mesh',
  onMeshChescaScenarioChange,
  onDetailRefresh,
}: {
  detail: WorkspaceDetail;
  simulation: CityLearnSimulationState;
  onSendMessage: (text: string) => Promise<void> | void;
  baselineModel: CityLearnBaselineModel;
  onBaselineModelChange: (model: CityLearnBaselineModel) => void;
  agentMeshMode: CityLearnAgentMeshMode;
  onAgentMeshModeChange: (mode: CityLearnAgentMeshMode) => void;
  useLLMPlanner: boolean;
  onUseLLMPlannerChange: (next: boolean) => void;
  isMeshChesca?: boolean;
  meshChescaScenario?: string;
  onMeshChescaScenarioChange?: (scenario: string) => void;
  onDetailRefresh?: () => void | Promise<void>;
}) {
  const setUseLLMPlanner = onUseLLMPlannerChange;
  const [meshChesca, setMeshChesca] = useState<MeshChescaBoardSnapshot['mesh_chesca'] | null>(null);
  const mapping = getCityLearnAgentBuildingMapping(detail.metadata_);
  const mappedBuildings = mapping?.buildings.filter((building) => building.assigned_agent_id).length || 0;
  const centralControllers = mapping?.central_controller_agents.length || 0;
  const totalBuildings = mapping?.buildings.length || CITYLEARN_BUILDING_NODES.length;
  const [selectedBuildingId, setSelectedBuildingId] = useState(CITYLEARN_BUILDING_NODES[0]?.id || '');
  const setBaselineModel = onBaselineModelChange;
  const setAgentMeshMode = onAgentMeshModeChange;
  const [metricView, setMetricView] = useState<CityLearnBoardMetricView>('power');
  const [heatmapCompareMode, setHeatmapCompareMode] = useState<CityLearnHeatmapCompareMode>('agent_mesh');
  const [boardSnapshot, setBoardSnapshot] = useState<CityLearnBoardSnapshot | null>(null);
  const [boardSnapshotError, setBoardSnapshotError] = useState<string | null>(null);
  // outage_mpc_mesh: 같은 (scenario, step)을 중복 발행하지 않도록 마지막 발행 키를 기억.
  const lastPublishedRef = useRef<string>('');
  const simulationStep = simulation.step;
  const chartData = boardSnapshot?.points || buildCityLearnPowerWindow(simulationStep, baselineModel, agentMeshMode);
  const metrics = cityLearnMetrics(chartData);
  const latestPoint = chartData[chartData.length - 1] || cityLearnPowerPoint(simulationStep, baselineModel, agentMeshMode);
  const baselineConfig = CITYLEARN_BASELINE_MODELS.find((model) => model.id === baselineModel) || CITYLEARN_BASELINE_MODELS[0];
  const meshConfig = CITYLEARN_AGENT_MESH_MODES.find((mode) => mode.id === agentMeshMode) || CITYLEARN_AGENT_MESH_MODES[0];
  const dataFeedConnected = Boolean(boardSnapshot?.runtime.citylearn_data_connected);
  const inferenceBundleDetected = Boolean(boardSnapshot?.runtime.inference_bundle_detected);
  const inferenceRunnerConnected = Boolean(boardSnapshot?.runtime.inference_runner_connected);

  const assignmentByBuildingId = new Map(
    (mapping?.buildings || []).map((building) => [building.building_id, building])
  );
  const buildingStatuses = boardSnapshot?.buildings || CITYLEARN_BUILDING_NODES.map((building, index) =>
    cityLearnBuildingStatus(building, index, simulationStep, baselineModel, agentMeshMode, assignmentByBuildingId.get(building.id))
  );
  const selectedBuildingStatus = buildingStatuses.find((status) => status.building_id === selectedBuildingId) || buildingStatuses[0];
  const meshMessageItems = cityLearnMeshMessageItems(detail, mapping, simulationStep, latestPoint, meshConfig.label);
  const baselineWeightSignals = cityLearnBaselineWeightSignals(
    selectedBuildingStatus,
    latestPoint,
    simulationStep,
    inferenceRunnerConnected
  );

  useEffect(() => {
    let cancelled = false;

    // mesh_chesca 템플릿: 실제 런타임을 시나리오별로 구동하는 전용 endpoint 사용.
    if (isMeshChesca) {
      const controller = new AbortController();
      // outage_mpc_mesh는 publish endpoint로 board snapshot을 받으면서 에이전트 자연어 소통을
      // 메시징 페이지 피드로 발행한다. 같은 step 중복 발행은 ref로 막는다.
      const isOutageMpc = meshChescaScenario === 'outage_mpc_mesh';
      const publishKey = `${meshChescaScenario}:${simulationStep}`;
      const shouldPublish = isOutageMpc && lastPublishedRef.current !== publishKey;

      const fetchPromise = shouldPublish
        ? meshChescaApi.publishBoard(
            { workspace_id: detail.workspace_id, step: simulationStep, scenario: meshChescaScenario, window: 72 },
            { signal: controller.signal },
          )
        : meshChescaApi.getBoard(
            { step: simulationStep, scenario: meshChescaScenario, dataset: MESH_CHESCA_DATASET, window: 72 },
            { signal: controller.signal },
          );

      fetchPromise
        .then(async (snapshot) => {
          if (cancelled) return;
          setBoardSnapshot(snapshot as unknown as CityLearnBoardSnapshot);
          setMeshChesca(snapshot.mesh_chesca);
          setBoardSnapshotError(null);
          if (shouldPublish) {
            lastPublishedRef.current = publishKey;
            // 발행된 메시지를 메시징 페이지/토폴로지에 반영하기 위해 detail 재조회.
            await onDetailRefresh?.();
          }
        })
        .catch((error) => {
          if (cancelled) return;
          const message = (error as { response?: { data?: { detail?: { message?: string } } } })
            .response?.data?.detail?.message;
          console.error(error);
          setBoardSnapshot(null);
          setMeshChesca(null);
          setBoardSnapshotError(
            message
              ? `CHESCA 런타임 오류: ${message}`
              : 'CHESCA 런타임을 사용할 수 없습니다 (백엔드 의존성/모델 확인 필요).',
          );
        });
      return () => {
        cancelled = true;
        controller.abort();
      };
    }

    citylearnApi.getBoardSnapshot({
      step: simulationStep,
      baseline_model: baselineModel,
      // deterministic/llm_planner은 UI 전용 mode이므로 백엔드 계약값(grid_agent)으로 매핑한다.
      agent_mesh_mode: agentMeshMode === 'deterministic' || agentMeshMode === 'llm_planner' ? 'grid_agent' : agentMeshMode,
      window: 72,
    })
      .then((snapshot) => {
        if (cancelled) return;
        setBoardSnapshot(snapshot);
        setBoardSnapshotError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        console.error(error);
        setBoardSnapshot(null);
        setBoardSnapshotError('Backend CityLearn feed unavailable; using frontend preview.');
      });

    return () => {
      cancelled = true;
    };
  }, [
    agentMeshMode,
    baselineModel,
    detail.workspace_id,
    isMeshChesca,
    meshChescaScenario,
    onDetailRefresh,
    simulationStep,
  ]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-[#eef0f4] p-4">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
	        <div>
	          <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-black/38">Board</p>
	          <h3 className="mt-1 text-[22px] font-semibold text-[#1d1d1f]">전력 관리 현황</h3>
	          <p className="mt-1 text-[13px] text-black/45">{CITYLEARN_DATASET_ID} · tick {simulationStep} · rolling 72 hours</p>
	        </div>
	        <div className="flex flex-wrap gap-2">
	          <div className="rounded-full bg-white px-3 py-1.5 text-[12px] font-semibold text-[#34a853] shadow-sm">
	            Schema verified
	          </div>
	          <div className={`rounded-full bg-white px-3 py-1.5 text-[12px] font-semibold shadow-sm ${dataFeedConnected ? 'text-[#248a3d]' : 'text-[#b35d00]'}`}>
	            Data {dataFeedConnected ? 'connected' : 'preview'}
	          </div>
	          <div className={`rounded-full bg-white px-3 py-1.5 text-[12px] font-semibold shadow-sm ${inferenceRunnerConnected ? 'text-[#005bb5]' : inferenceBundleDetected ? 'text-[#b35d00]' : 'text-[#d70015]'}`}>
	            SACRBC {inferenceRunnerConnected ? 'running' : inferenceBundleDetected ? 'artifact only' : 'missing'}
	          </div>
	          <div className="rounded-full bg-white px-3 py-1.5 text-[12px] font-semibold text-black/48 shadow-sm">
	            {mappedBuildings}/{totalBuildings} buildings · {centralControllers} central
	          </div>
	        </div>
	      </div>

	      <section className="mb-4 rounded-[18px] border border-black/10 bg-white p-4 shadow-sm">
	        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
	          <div>
	            <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-black/38">Dataset & Runtime</p>
	            <h4 className="mt-1 text-[15px] font-semibold text-[#1d1d1f]">CityLearn 2022 phase all</h4>
	            <p className="mt-1 text-[12px] leading-5 text-black/50">
	              Dataset path: {boardSnapshot?.dataset.path || CITYLEARN_DATASET_PATH}. Active actions: {(boardSnapshot?.dataset.active_actions || ['electrical_storage']).join(', ')}. EV charger and washing-machine actions are not part of this board configuration. SACRBC artifact: {boardSnapshot?.runtime.inference_bundle_path || 'CityLearn_old_system/citylearn/best_inference_bundle.pt'}.
	            </p>
	            {boardSnapshot?.runtime.inference_error && baselineModel === 'sacrbc' && (
	              <p className="mt-2 rounded-[10px] bg-[#ff453a]/10 px-3 py-2 text-[11px] font-medium text-[#b42318]">
	                SACRBC runner unavailable: {boardSnapshot.runtime.inference_error}
	              </p>
	            )}
	            {boardSnapshotError && (
	              <p className="mt-2 rounded-[10px] bg-[#ff9f0a]/12 px-3 py-2 text-[11px] font-medium text-[#9a6a00]">
	                {boardSnapshotError}
	              </p>
	            )}
	          </div>
	          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
	            <label className="block">
	              <span className="mb-1 block text-[11px] font-semibold text-black/42">Baseline model</span>
	              <select
	                className="w-full rounded-[10px] border border-black/10 bg-[#f7f8fb] px-3 py-2 text-[12px] font-medium text-black/70 outline-none"
	                value={baselineModel}
	                onChange={(event) => setBaselineModel(event.target.value as CityLearnBaselineModel)}
	              >
	                {CITYLEARN_BASELINE_MODELS.map((model) => (
	                  <option key={model.id} value={model.id}>{model.label} · {model.status}</option>
	                ))}
	              </select>
	            </label>
	            <label className="block">
	              <span className="mb-1 block text-[11px] font-semibold text-black/42">{isMeshChesca ? 'CHESCA 협상 시나리오' : 'Agent-Mesh mode'}</span>
	              {isMeshChesca ? (
	                <select
	                  className="w-full rounded-[10px] border border-black/10 bg-[#f7f8fb] px-3 py-2 text-[12px] font-medium text-black/70 outline-none"
	                  value={meshChescaScenario}
	                  onChange={(event) => onMeshChescaScenarioChange?.(event.target.value)}
	                >
	                  {(meshChesca?.available_scenarios ?? MESH_CHESCA_SCENARIO_FALLBACK).map((scenario) => (
	                    <option key={scenario.id} value={scenario.id}>{scenario.label}</option>
	                  ))}
	                </select>
	              ) : (
	                <select
	                  className="w-full rounded-[10px] border border-black/10 bg-[#f7f8fb] px-3 py-2 text-[12px] font-medium text-black/70 outline-none"
	                  value={agentMeshMode}
	                  onChange={(event) => setAgentMeshMode(event.target.value as CityLearnAgentMeshMode)}
	                >
	                  {CITYLEARN_AGENT_MESH_MODES.map((mode) => (
	                    <option key={mode.id} value={mode.id}>{mode.label} · {mode.status}</option>
	                  ))}
	                </select>
	              )}
	            </label>
	            <div className="rounded-[12px] bg-[#f7f8fb] px-3 py-2">
	              <span className="block text-[11px] font-semibold text-black/38">Baseline status</span>
	              <span className="mt-1 block text-[12px] leading-5 text-black/58">{isMeshChesca ? '공식 CHESCA(예측+PID+배터리 tree-search)가 baseline action을 제공합니다.' : baselineConfig.description}</span>
	            </div>
	            <div className="rounded-[12px] bg-[#f7f8fb] px-3 py-2">
	              <span className="block text-[11px] font-semibold text-black/38">{isMeshChesca ? '시나리오 설명' : 'Agent-Mesh status'}</span>
	              <span className="mt-1 block text-[12px] leading-5 text-black/58">{isMeshChesca ? (meshChesca?.scenario_description ?? 'CHESCA mesh 협상 시나리오') : meshConfig.description}</span>
	            </div>
	          </div>
	        </div>
	      </section>

	      {(agentMeshMode === 'deterministic' || agentMeshMode === 'llm_planner') && (
	        <GridAgentValidationPanel
	          run={simulation.lastGridAgentRun}
	          pendingStep={simulation.pendingGridAgentStep}
	          error={simulation.gridAgentError}
	          currentStep={simulationStep}
	          modeLabel={agentMeshMode === 'llm_planner' ? 'LLM Planner' : 'Deterministic'}
	          showLLMToggle={false}
	          useLLMPlanner={useLLMPlanner}
	          onToggleLLMPlanner={setUseLLMPlanner}
	        />
	      )}

	      {(agentMeshMode === 'macro_mesh' || agentMeshMode === 'macro_mesh_v2') && (
	        <NegotiationTracePanel
	          run={simulation.lastMacroMeshRun}
	          pendingStep={simulation.pendingMacroMeshStep}
	          error={simulation.macroMeshError}
	          currentStep={simulationStep}
	          useLLMProposers={useLLMPlanner}
	          onToggleLLMProposers={setUseLLMPlanner}
	        />
	      )}

	      {isMeshChesca && (
	        <MeshChescaPanel mesh={meshChesca} error={boardSnapshotError} step={simulationStep} />
	      )}

	      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
	        {metrics.map((metric) => (
	          <BoardMetricCard key={metric.id} metric={metric} />
	        ))}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
	        <section className="rounded-[18px] border border-black/10 bg-white p-4 shadow-sm">
	          <div className="mb-4 flex items-center justify-between gap-3">
	            <div>
	              <h4 className="text-[16px] font-semibold text-[#1d1d1f]">{metricView === 'power' ? '실시간 전력 소비 비교' : 'Reward 비교'}</h4>
	              <p className="mt-1 text-[12px] text-black/42">{baselineConfig.label} vs {meshConfig.label} · {metricView === 'power' ? 'kWh' : 'reward points'}</p>
	            </div>
	            <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold">
	              <div className="flex rounded-[10px] border border-black/10 bg-black/[0.04] p-1">
	                {(['power', 'reward'] as const).map((viewMode) => (
	                  <button
	                    key={viewMode}
	                    type="button"
	                    className={`rounded-[8px] px-2.5 py-1 ${metricView === viewMode ? 'bg-white text-[#0071e3] shadow-sm' : 'text-black/42'}`}
	                    onClick={() => setMetricView(viewMode)}
	                  >
	                    {viewMode === 'power' ? 'Power' : 'Reward'}
	                  </button>
	                ))}
	              </div>
	              <span className="rounded-full bg-[#ff6b6b]/12 px-2.5 py-1 text-[#d94848]">
	                Baseline {metricView === 'power' ? latestPoint.baseline.toFixed(1) : latestPoint.baseline_reward.toFixed(1)}
	              </span>
	              <span className="rounded-full bg-[#51cf66]/12 px-2.5 py-1 text-[#2f9e44]">
	                Agent-Mesh {metricView === 'power' ? latestPoint.agent_mesh.toFixed(1) : latestPoint.agent_mesh_reward.toFixed(1)}
	              </span>
	            </div>
	          </div>
          <div className="h-[360px] min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 12, left: -12, bottom: 4 }}>
                <defs>
                  <linearGradient id="baselineArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ff6b6b" stopOpacity={0.22} />
                    <stop offset="95%" stopColor="#ff6b6b" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="agentMeshArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#51cf66" stopOpacity={0.22} />
                    <stop offset="95%" stopColor="#51cf66" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#e5e5ea" strokeDasharray="4 4" vertical={false} />
                <XAxis
                  dataKey="time_step"
                  tickLine={false}
                  axisLine={false}
                  minTickGap={28}
                  tick={{ fill: '#8e8e93', fontSize: 11 }}
                  tickFormatter={(value) => `T+${value}`}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={44}
                  tick={{ fill: '#8e8e93', fontSize: 11 }}
                  tickFormatter={(value) => `${value}`}
                />
                <Tooltip
                  contentStyle={{
                    border: '1px solid rgba(0,0,0,0.08)',
                    borderRadius: 12,
                    boxShadow: '0 12px 34px rgba(0,0,0,0.14)',
                  }}
	                  formatter={(value, name) => [
	                    `${Number(value || 0).toFixed(2)} ${metricView === 'power' ? 'kWh' : 'pts'}`,
	                    name === 'baseline' || name === 'baseline_reward' ? baselineConfig.label : meshConfig.label,
	                  ]}
                  labelFormatter={(label) => `Time Step T+${label}`}
                />
                <Legend
                  verticalAlign="top"
                  height={32}
	                  iconType="circle"
	                  formatter={(value) => value === 'baseline' || value === 'baseline_reward' ? baselineConfig.label : meshConfig.label}
	                />
	                <Area
	                  type="monotone"
	                  dataKey={metricView === 'power' ? 'baseline' : 'baseline_reward'}
	                  stroke="#ff6b6b"
                  fill="url(#baselineArea)"
                  strokeWidth={2.4}
                  dot={false}
                  activeDot={{ r: 4 }}
                  isAnimationActive
                  animationDuration={300}
                />
	                <Area
	                  type="monotone"
	                  dataKey={metricView === 'power' ? 'agent_mesh' : 'agent_mesh_reward'}
                  stroke="#51cf66"
                  fill="url(#agentMeshArea)"
                  strokeWidth={2.4}
                  dot={false}
                  activeDot={{ r: 4 }}
                  isAnimationActive
                  animationDuration={300}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
	          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
	            <CityLearnMeshMiniPanel
	              items={meshMessageItems}
	              mappedBuildings={mappedBuildings}
	              totalBuildings={totalBuildings}
	              onSendMessage={onSendMessage}
	            />
	            <CityLearnBaselineWeightsPanel
	              signals={baselineWeightSignals}
	              inferenceRunnerConnected={inferenceRunnerConnected}
	              baselineLabel={baselineConfig.label}
	            />
	          </div>
        </section>

		        <section className="rounded-[18px] border border-black/10 bg-white p-4 shadow-sm">
		          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
		            <div>
		              <h4 className="text-[16px] font-semibold text-[#1d1d1f]">Building Heatmap</h4>
		              <p className="mt-1 text-[12px] text-black/42">
		                {cityLearnHeatmapLabel(heatmapCompareMode)} view · Delta는 Baseline net load - Agent-Mesh net load 절감량입니다.
		              </p>
		            </div>
		            <div className="flex flex-wrap items-center gap-2">
		              <div className="flex rounded-[10px] border border-black/10 bg-black/[0.04] p-1 text-[11px] font-semibold">
		                {(['baseline', 'agent_mesh', 'delta'] as const).map((mode) => (
		                  <button
		                    key={mode}
		                    type="button"
		                    className={`rounded-[8px] px-2.5 py-1 ${heatmapCompareMode === mode ? 'bg-white text-[#0071e3] shadow-sm' : 'text-black/42'}`}
		                    onClick={() => setHeatmapCompareMode(mode)}
		                  >
		                    {mode === 'baseline' ? 'Baseline' : mode === 'agent_mesh' ? 'Agent-Mesh' : 'Delta'}
		                  </button>
		                ))}
		              </div>
		              <div className="flex shrink-0 gap-1 text-[10px] font-semibold">
		                <span className="rounded-full bg-[#34c759]/16 px-2 py-1 text-[#248a3d]">low</span>
		                <span className="rounded-full bg-[#ffd60a]/22 px-2 py-1 text-[#9a6a00]">mid</span>
		                <span className="rounded-full bg-[#ff453a]/14 px-2 py-1 text-[#d70015]">high</span>
		              </div>
		            </div>
		          </div>
	          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
	            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
		              {buildingStatuses.map((status) => {
		                const assignment = assignmentByBuildingId.get(status.building_id);
		                const socPercent = Math.round(status.battery_soc * 100);
		                const isSelected = status.building_id === selectedBuildingStatus?.building_id;
		                const displayedNetLoad = cityLearnHeatmapValue(status, heatmapCompareMode);
		                const gridAgentAction = agentMeshMode === 'deterministic' || agentMeshMode === 'llm_planner'
		                  ? simulation.lastGridAgentRun?.final_plan.actions.find((a) => a.building_id === status.building_id) ?? null
		                  : null;
		                const gridAgentRejected = gridAgentAction
		                  ? simulation.lastGridAgentRun?.validation.new_violations.some(
		                      (v) => v.building_id === status.building_id && (v.type === 'soc' || v.type === 'invalid_action'),
		                    ) ?? false
		                  : false;
		                const actionLabel = status.battery_action === 'charging' ? 'charge' : status.battery_action === 'discharging' ? 'discharge' : 'idle';
	                const actionTone = status.battery_action === 'charging'
	                  ? 'bg-[#0071e3]/12 text-[#005bb5]'
	                  : status.battery_action === 'discharging'
	                    ? 'bg-[#ff9f0a]/16 text-[#a85b00]'
	                    : 'bg-black/[0.06] text-black/44';

	                return (
	                  <button
	                    key={status.building_id}
	                    type="button"
		                    onClick={() => setSelectedBuildingId(status.building_id)}
		                    className={`min-h-[112px] rounded-[12px] border px-3 py-2 text-left transition ${isSelected ? 'border-[#0071e3] ring-2 ring-[#0071e3]/20' : 'border-black/6 hover:border-black/18'}`}
		                    style={{ backgroundColor: cityLearnHeatmapColor(Math.abs(displayedNetLoad)) }}
		                  >
	                    <div className="mb-2 flex items-center justify-between gap-2">
	                      <span className="truncate text-[12px] font-semibold text-[#1d1d1f]">{cityLearnBuildingLabel(status.building_id)}</span>
	                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${status.agent_intervention ? 'bg-[#34c759]/16 text-[#248a3d]' : 'bg-black/[0.06] text-black/38'}`}>
	                        {status.agent_intervention ? 'agent' : 'open'}
	                      </span>
		                    </div>
		                    <div className="grid grid-cols-2 gap-1.5 text-[11px] text-black/54">
		                      <span>{cityLearnHeatmapLabel(heatmapCompareMode)} {displayedNetLoad.toFixed(1)} kWh</span>
		                      <span>PV {status.pv_generation_kwh.toFixed(1)} kWh</span>
		                      <span>SoC {socPercent}%</span>
	                      <span className={`rounded-full px-2 py-0.5 text-center font-semibold ${actionTone}`}>{actionLabel}</span>
	                    </div>
	                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/75">
	                      <div className="h-full rounded-full bg-[#34c759]" style={{ width: `${socPercent}%` }} />
	                    </div>
	                    <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-black/40">
	                      <span>{assignment?.assigned_agent_name || 'No assigned agent'}</span>
	                      <span>Battery-only phase_all</span>
	                    </div>
	                    {gridAgentAction && (
	                      <div
	                        className={`mt-2 flex items-center justify-between gap-2 rounded-[8px] px-2 py-1 text-[10px] font-semibold ${gridAgentRejected ? 'bg-[#ff453a]/14 text-[#b42318] ring-1 ring-[#ff453a]/40' : gridAgentAction.mode === 'charge' ? 'bg-[#0071e3]/12 text-[#005bb5]' : gridAgentAction.mode === 'discharge' ? 'bg-[#ff9f0a]/16 text-[#a05a00]' : 'bg-black/[0.06] text-black/55'}`}
	                        style={{ opacity: 0.5 + 0.5 * Math.max(0.1, Math.min(1, gridAgentAction.confidence)) }}
	                        title={`${gridAgentAction.reason} · confidence ${gridAgentAction.confidence.toFixed(2)} · expected ${gridAgentAction.expected_effect}${gridAgentRejected ? ' · REJECTED by validator' : ''}`}
	                      >
	                        <span>plan {gridAgentAction.mode} {gridAgentAction.action.toFixed(2)}</span>
	                        <span className="text-[9px] opacity-70">conf {Math.round(gridAgentAction.confidence * 100)}%</span>
	                      </div>
	                    )}
	                  </button>
	                );
	              })}
	            </div>
	            {selectedBuildingStatus && (
	              <aside className="rounded-[14px] border border-black/8 bg-[#f7f8fb] p-3">
	                <div className="mb-3 flex items-start justify-between gap-2">
	                  <div>
	                    <h5 className="text-[14px] font-semibold text-[#1d1d1f]">{cityLearnBuildingLabel(selectedBuildingStatus.building_id)}</h5>
	                    <p className="mt-0.5 text-[11px] text-black/42">최근 24시간 상태 · kWh 기준, SoC는 별도 % 값</p>
	                  </div>
	                  <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${selectedBuildingStatus.agent_intervention ? 'bg-[#34c759]/16 text-[#248a3d]' : 'bg-black/[0.06] text-black/42'}`}>
	                    {selectedBuildingStatus.agent_intervention ? 'intervention' : 'monitor'}
	                  </span>
	                </div>
	                <div className="grid grid-cols-2 gap-2">
		                  <BoardStatusKV label="Current net load" value={`${selectedBuildingStatus.net_load_kwh.toFixed(1)} kWh`} />
		                  <BoardStatusKV label="Baseline net load" value={`${selectedBuildingStatus.baseline_net_load_kwh.toFixed(1)} kWh`} />
		                  <BoardStatusKV label="Agent-Mesh net load" value={`${selectedBuildingStatus.agent_mesh_net_load_kwh.toFixed(1)} kWh`} />
		                  <BoardStatusKV label="PV generation" value={`${selectedBuildingStatus.pv_generation_kwh.toFixed(1)} kWh`} />
		                  <BoardStatusKV label="Battery SoC / action" value={`${Math.round(selectedBuildingStatus.battery_soc * 100)}% · ${selectedBuildingStatus.battery_action}`} />
		                  {typeof selectedBuildingStatus.baseline_action_value === 'number' && (
		                    <BoardStatusKV label="SACRBC action" value={selectedBuildingStatus.baseline_action_value.toFixed(3)} />
		                  )}
		                  <BoardStatusKV label="Delta saved" value={`${(selectedBuildingStatus.baseline_net_load_kwh - selectedBuildingStatus.agent_mesh_net_load_kwh).toFixed(1)} kWh`} />
		                  <BoardStatusKV label="Dataset" value="phase_all" />
		                </div>
	                <div className="mt-3 grid gap-1.5 rounded-[10px] bg-white px-3 py-2 text-[11px] leading-4 text-black/62">
	                  <BoardLegendItem color="#ff6b6b" value="baseline net load" />
	                  <BoardLegendItem color="#0071e3" value="Agent-Mesh net load" />
	                  <BoardLegendItem color="#34c759" value="PV generation" />
	                  <BoardLegendItem color="#1d1d1f" label="Delta" value="baseline net load - Agent-Mesh net load" />
	                </div>
	                <div className="mt-3 h-[160px] min-w-0">
	                  <ResponsiveContainer width="100%" height="100%">
	                    <AreaChart data={selectedBuildingStatus.history} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
	                      <CartesianGrid stroke="#e5e5ea" strokeDasharray="3 3" vertical={false} />
	                      <XAxis dataKey="time_step" hide />
	                      <YAxis tickLine={false} axisLine={false} tick={{ fill: '#8e8e93', fontSize: 10 }} width={34} />
	                      <Tooltip
	                        contentStyle={{ border: '1px solid rgba(0,0,0,0.08)', borderRadius: 10 }}
		                        formatter={(value, name) => [
		                          `${Number(value || 0).toFixed(2)} ${name === 'battery_soc' ? '' : 'kWh'}`,
		                          name === 'baseline_net_load_kwh' ? baselineConfig.label : name === 'agent_mesh_net_load_kwh' ? meshConfig.label : name === 'pv_generation_kwh' ? 'PV' : 'SoC',
		                        ]}
		                        labelFormatter={(label) => `Time Step T+${label}`}
		                      />
		                      <Area type="monotone" dataKey="baseline_net_load_kwh" stroke="#ff6b6b" fill="#ff6b6b" fillOpacity={0.1} strokeWidth={2} dot={false} />
		                      <Area type="monotone" dataKey="agent_mesh_net_load_kwh" stroke="#0071e3" fill="#0071e3" fillOpacity={0.08} strokeWidth={2} dot={false} />
		                      <Area type="monotone" dataKey="pv_generation_kwh" stroke="#34c759" fill="#34c759" fillOpacity={0.08} strokeWidth={2} dot={false} />
	                    </AreaChart>
	                  </ResponsiveContainer>
	                </div>
	                {selectedBuildingStatus.agent_action_description && (
	                  <p className="mt-3 rounded-[10px] bg-white px-3 py-2 text-[11px] leading-5 text-black/58">
	                    {selectedBuildingStatus.agent_action_description}
	                  </p>
	                )}
	              </aside>
	            )}
	          </div>
	        </section>
      </div>
    </div>
  );
}

function BoardMetricCard({ metric }: { metric: CityLearnMetric }) {
  const toneClass = {
    blue: 'bg-apple-blue/12 text-apple-blue',
    green: 'bg-[#34c759]/12 text-[#248a3d]',
    yellow: 'bg-[#ff9f0a]/14 text-[#b35d00]',
    red: 'bg-[#ff453a]/12 text-[#d70015]',
  }[metric.tone];
  const deltaIsBetter = metric.improvement >= 0;
  const deltaLabel = deltaIsBetter
    ? metric.improvementLabel
    : metric.improvementLabel.includes('개선')
      ? '% 악화'
      : '% 증가';
  const deltaClass = deltaIsBetter
    ? 'bg-[#34c759]/12 text-[#248a3d]'
    : 'bg-[#ff453a]/12 text-[#d70015]';

  return (
    <section className="rounded-[18px] border border-black/10 bg-white p-4 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className={`inline-flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-[11px] font-semibold ${toneClass}`}>
          {metric.label.slice(0, 2)}
        </div>
        <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${deltaClass}`}>
          {Math.abs(metric.improvement).toFixed(1)}{deltaLabel}
        </span>
      </div>
      <p className="text-[12px] font-medium text-black/42">{metric.label}</p>
      <p className="mt-1 text-[24px] font-semibold text-[#1d1d1f]">
        {metric.agentMesh.toLocaleString(undefined, { maximumFractionDigits: 1 })} {metric.unit}
      </p>
      <p className="mt-1 text-[12px] text-black/42">
        Baseline {metric.baseline.toLocaleString(undefined, { maximumFractionDigits: 1 })} {metric.unit}
      </p>
    </section>
  );
}

function CityLearnMeshMiniPanel({
  items,
  mappedBuildings,
  totalBuildings,
  onSendMessage,
}: {
  items: CityLearnMeshMessageItem[];
  mappedBuildings: number;
  totalBuildings: number;
  onSendMessage: (text: string) => Promise<void> | void;
}) {
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const feedRef = useRef<HTMLDivElement | null>(null);
  // 새 메시지가 추가되면 최신 메시지가 보이도록 맨 아래로 스크롤(실제 메시지 페이지와 동일 동작).
  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length]);
  const avatarClass = {
    blue: 'bg-[#0071e3] text-white',
    green: 'bg-white text-black/70 shadow-sm',
    yellow: 'bg-[#ff9f0a] text-white',
  };
  const sendDraft = async () => {
    const next = draft.trim();
    if (!next || sending) return;
    setSending(true);
    try {
      await onSendMessage(next);
      setDraft('');
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="min-h-[534px] overflow-hidden rounded-[14px] border border-black/8 bg-[#f4f5f7] shadow-sm">
      <div className="flex items-center justify-between border-b border-black/10 bg-white/90 px-3 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h5 className="truncate text-[13px] font-semibold text-[#1d1d1f]"># agentic-mesh</h5>
            <span className="h-2 w-2 rounded-full bg-[#34c759]" />
          </div>
          <p className="text-[10px] text-black/42">{mappedBuildings}/{totalBuildings} buildings mapped · board embedded messaging</p>
        </div>
      </div>
      <div ref={feedRef} className="h-[430px] space-y-2 overflow-y-auto px-3 py-3">
        {items.map((item) => (
          <div key={item.id} className="flex justify-start">
            <div className="flex max-w-[94%] gap-2">
              <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${avatarClass[item.tone]}`}>
                {item.sender.charAt(0)}
              </div>
              <div className="min-w-0 text-left">
                <div className="mb-1 flex items-center gap-1.5">
                  <span className="truncate text-[11px] font-semibold text-black/72">{item.sender}</span>
                  <span className="shrink-0 text-[9px] text-black/32">{item.meta}</span>
                </div>
                <div className="rounded-[14px] rounded-bl-[5px] border border-black/6 bg-white px-3 py-2 text-[11px] leading-4 text-black/68 shadow-sm">
                  {item.summary}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-black/10 bg-white/90 p-2">
        <div className="flex items-center gap-2 rounded-[12px] border border-black/10 bg-[#f7f8fa] p-1.5 shadow-inner">
          <textarea
            className="min-h-[28px] flex-1 resize-none bg-transparent px-2 py-1 text-[12px] leading-5 text-black/75 outline-none placeholder:text-black/35"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
              event.preventDefault();
              void sendDraft();
            }}
            placeholder="@agent_name 에게 메시지 보내기"
          />
          <button
            type="button"
            className="rounded-[9px] bg-[#0071e3] px-3 py-1.5 text-[11px] font-semibold text-white disabled:opacity-45"
            onClick={() => void sendDraft()}
            disabled={!draft.trim() || sending}
          >
            {sending ? '...' : 'Send'}
          </button>
        </div>
      </div>
    </section>
  );
}

function CityLearnBaselineWeightsPanel({
  signals,
  inferenceRunnerConnected,
  baselineLabel,
}: {
  signals: CityLearnBaselineWeightSignal[];
  inferenceRunnerConnected: boolean;
  baselineLabel: string;
}) {
  return (
    <section className="min-h-[534px] rounded-[14px] border border-black/8 bg-[#f7f8fb] p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h5 className="text-[13px] font-semibold text-[#1d1d1f]">Baseline RL vector stream</h5>
          <p className="mt-0.5 text-[11px] text-black/42">{baselineLabel} · opaque policy tensors</p>
        </div>
        <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${inferenceRunnerConnected ? 'bg-[#0071e3]/12 text-[#005bb5]' : 'bg-[#ff9f0a]/14 text-[#9a6a00]'}`}>
          {inferenceRunnerConnected ? 'running' : 'fallback'}
        </span>
      </div>
      <div className="mb-3 rounded-[10px] bg-white px-3 py-2 text-[11px] leading-5 text-black/54">
        RL baseline은 action만 출력되며 내부 tensor는 사람이 바로 해석하기 어렵습니다. 아래는 tick마다 변하는 policy vector projection입니다.
      </div>
      <div className="space-y-3">
        {signals.map((signal) => (
          <div key={signal.id}>
            <div className="mb-1 flex items-center justify-between gap-2 text-[11px]">
              <span className="truncate font-medium text-black/58">{signal.label}</span>
              <span className="shrink-0 font-mono text-[10px] text-black/34">dim {signal.values.length}</span>
            </div>
            <div className="grid gap-1 rounded-[8px] bg-black/[0.04] p-1" style={{ gridTemplateColumns: `repeat(${signal.values.length}, minmax(0, 1fr))` }}>
              {signal.values.map((value, index) => (
                <div
                  key={`${signal.id}-${index}`}
                  className="h-6 rounded-[4px] transition-colors duration-300"
                  title={`${signal.label}[${index}] = ${value.toFixed(3)}`}
                  style={{
                    backgroundColor: value >= 0
                      ? `rgba(0, 113, 227, ${0.18 + Math.abs(value) * 0.62})`
                      : `rgba(255, 69, 58, ${0.18 + Math.abs(value) * 0.62})`,
                  }}
                />
              ))}
            </div>
            <div className="mt-1 flex justify-between font-mono text-[9px] text-black/30">
              <span>-1.0</span>
              <span>0</span>
              <span>+1.0</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function BoardStatusKV({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[10px] bg-white px-2.5 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-black/38">{label}</p>
      <p className="mt-1 break-words text-[12px] font-semibold leading-4 text-[#1d1d1f]">{value}</p>
    </div>
  );
}

function BoardLegendItem({ color, label, value }: { color: string; label?: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      {label && (
        <>
          <span className="font-semibold text-[#1d1d1f]">{label}</span>
          <span className="text-black/42">:</span>
        </>
      )}
      <span className="text-black/58">{value}</span>
    </div>
  );
}

function Alert({ message }: { message: string }) {
  return <div className="mb-4 bg-[#ff3b30]/15 text-[#ff3b30] border border-[#ff3b30]/30 rounded-[10px] px-4 py-3 text-[14px]">{message}</div>;
}

function SidebarGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-white/30">{title}</p>
      {children}
    </section>
  );
}

function GoalTreeItem({
  goal,
  goals,
  selectedGoalId,
  onSelect,
  canManage,
  onCreateChild,
  onDelete,
  depth = 0,
}: {
  goal: Goal;
  goals: Goal[];
  selectedGoalId: string | null;
  onSelect: (goal: Goal) => void;
  canManage: boolean;
  onCreateChild: (goal: Goal) => void;
  onDelete: (goal: Goal) => void;
  depth?: number;
}) {
  const children = goals.filter((item) => item.parent_goal_id === goal.goal_id);
  const stateTone =
    goal.state === 'completed'
      ? 'bg-[#34c759]'
      : goal.state === 'blocked' || goal.state === 'failed'
        ? 'bg-[#ff453a]'
        : goal.state === 'running'
          ? 'bg-[#ffd60a]'
          : 'bg-white/30';

  return (
    <div>
      <div
        className={`group mb-1 flex w-full items-center gap-2 rounded-[12px] py-2 pr-2 text-left transition ${selectedGoalId === goal.goal_id ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07]'}`}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
      >
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${stateTone}`} />
        <button className="min-w-0 flex-1 text-left" onClick={() => onSelect(goal)}>
          <span className="block truncate text-[13px] font-medium">{goal.name}</span>
          <span className="block text-[11px] text-white/38">{goal.state} · {goal.progress}% · msg {goal.recent_message_count}</span>
        </button>
        {canManage && (
          <span className="flex shrink-0 items-center gap-1 opacity-70 transition group-hover:opacity-100 group-focus-within:opacity-100">
            <button
              className="rounded-[7px] bg-white/10 px-1.5 py-1 text-[11px] font-semibold text-white/60 hover:bg-apple-blue/25 hover:text-white"
              title="Sub Goal 생성"
              onClick={() => onCreateChild(goal)}
            >
              +
            </button>
            <button
              className="rounded-[7px] bg-[#ff453a]/12 px-1.5 py-1 text-[11px] font-semibold text-[#ff9f0a] hover:bg-[#ff453a]/20"
              title="Goal 삭제"
              onClick={() => onDelete(goal)}
            >
              x
            </button>
          </span>
        )}
      </div>
      {children.map((child) => (
        <GoalTreeItem
          key={child.goal_id}
          goal={child}
          goals={goals}
          selectedGoalId={selectedGoalId}
          onSelect={onSelect}
          canManage={canManage}
          onCreateChild={onCreateChild}
          onDelete={onDelete}
          depth={depth + 1}
        />
      ))}
    </div>
  );
}

function InspectorSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5 rounded-[16px] border border-white/8 bg-white/[0.035] p-4">
      <h3 className="mb-3 text-[13px] font-semibold text-white/78">{title}</h3>
      {children}
    </section>
  );
}

function InspectorKV({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-3">
      <p className="text-[11px] uppercase tracking-[0.12em] text-white/30">{label}</p>
      <p className="mt-1 break-words text-[13px] leading-5 text-white/68">{value}</p>
    </div>
  );
}
