import client from './client';

export type AgentStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED' | 'SUSPENDED';

export interface OperationsOverview {
  total_agents: number;
  status_breakdown: {
    ACTIVE: number;
    DRAFT: number;
    DEPRECATED: number;
    SUSPENDED: number;
  };
  visibility_breakdown: Record<string, number>;
  total_interactions: number;
  interactions_24h: number;
  failed_interactions: number;
  success_rate: number;
  total_tokens: number;
}

export interface AgentOps {
  agent_id: string;
  name: string;
  version: string;
  status: AgentStatus;
  visibility: string;
  owner_name: string | null;
  tool_count: number;
  updated_at: string;
  last_activity: string | null;
}

export interface Activity {
  interaction_id: string;
  actor_name: string;
  target_name: string | null;
  kind: string;
  state: string;
  start_timestamp: string;
  duration_ms: number | null;
  model_used: string | null;
  error_message: string | null;
}

export interface HealthComponent {
  name: string;
  status: 'online' | 'degraded' | 'offline';
  detail: string;
}

export const operationsApi = {
  getOverview: () =>
    client.get<OperationsOverview>('/operations/overview').then((r) => r.data),
  getAgents: () => client.get<AgentOps[]>('/operations/agents').then((r) => r.data),
  updateAgentStatus: (agentId: string, status: AgentStatus) =>
    client
      .patch<AgentOps>(`/operations/agents/${agentId}/status`, { status })
      .then((r) => r.data),
  getActivity: (limit = 25) =>
    client
      .get<Activity[]>('/operations/activity', { params: { limit } })
      .then((r) => r.data),
  getHealth: () =>
    client
      .get<{ components: HealthComponent[] }>('/operations/health')
      .then((r) => r.data.components),
};
