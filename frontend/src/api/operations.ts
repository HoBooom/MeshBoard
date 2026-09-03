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
  active_executions: number;
  control_generation: number;
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

export interface ExecutionSummary {
  execution_tree_id: string;
  root_interaction_id: string;
  conversation_id: string;
  actor_name: string;
  prompt: string | null;
  state: string;
  node_count: number;
  duration_ms: number | null;
  started_at: string;
}

export interface ExecutionNode {
  interaction_id: string;
  parent_id: string | null;
  execution_tree_id: string;
  tree_depth: number;
  tree_path: string;
  actor_name: string;
  target_name: string | null;
  kind: string;
  state: string;
  duration_ms: number | null;
  reasoning_trace: string | null;
  results: string | null;
  tool_name: string | null;
  error_message: string | null;
  start_timestamp: string;
  payload: {
    schema_version: string;
    source_schema_version: string;
    input?: string | null;
    output?: string | null;
    reasoning?: string | null;
    tool?: { name?: string | null; arguments?: unknown; result?: unknown } | null;
    metadata?: Record<string, unknown>;
  };
}

export interface OperationsAnalytics {
  models: Array<{
    model: string;
    execution_count: number;
    failed_count: number;
    token_input: number;
    token_output: number;
    total_tokens: number;
    average_duration_ms: number;
    estimated_cost_usd: number | null;
  }>;
  parallel_groups: Array<{
    parallel_group_id: string;
    execution_count: number;
    wall_duration_ms: number;
    serial_duration_ms: number;
    saved_duration_ms: number;
  }>;
}

export interface ConnectorStatus {
  configured: boolean;
  endpoint: string | null;
  production_https_required: boolean;
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
  getExecutions: (limit = 20) =>
    client.get<ExecutionSummary[]>('/operations/executions', { params: { limit } }).then((r) => r.data),
  getExecutionTree: (executionTreeId: string) =>
    client.get<{ execution_tree_id: string; nodes: ExecutionNode[] }>(`/operations/executions/${executionTreeId}`).then((r) => r.data),
  getAnalytics: () =>
    client.get<OperationsAnalytics>('/operations/analytics').then((r) => r.data),
  getSecurityConnector: () =>
    client.get<ConnectorStatus>('/operations/connectors/security-webhook').then((r) => r.data),
  testSecurityConnector: () =>
    client.post<{ configured: boolean; delivered: boolean; status_code: number | null; error?: string }>('/operations/connectors/security-webhook/test').then((r) => r.data),
};
