/**
 * MeshBoard — Creator Workbench API Client
 *
 * /api/v1/agents 관련 엔드포인트 래퍼.
 */

import client from './client';

export type AgentStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED' | 'SUSPENDED';
export type AgentVisibility = 'PUBLIC' | 'DEPARTMENT' | 'PRIVATE';
export type RulePriority = 'low' | 'medium' | 'high' | 'critical';

export interface ToolDescriptor {
  id: string;
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
  mcp_definition?: {
    name: string;
    description: string;
    inputSchema: Record<string, unknown>;
  };
}

export interface SubscriptionRule {
  rule_id?: string;
  agent_id?: string;
  watch_domains: string[];
  watch_intents: string[];
  watch_tags: string[];
  watch_senders: string[];
  watch_roles: string[];
  ignore_senders: string[];
  ignore_tags: string[];
  min_priority: RulePriority;
  is_active: boolean;
  updated_at?: string;
}

export interface Agent {
  agent_id: string;
  owner_id: string;
  name: string;
  version: string;
  purpose?: string | null;
  description?: string | null;
  approach?: string | null;
  status: AgentStatus;
  visibility: AgentVisibility;
  agent_card: Record<string, unknown>;
  roles: string[];
  collaborators: string[];
  tools: string[];
  metadata_: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  subscription_rule?: SubscriptionRule | null;
}

export interface AgentCreatePayload {
  name: string;
  version: string;
  purpose?: string;
  description?: string;
  approach?: string;
  status?: AgentStatus;
  visibility?: AgentVisibility;
  agent_card?: Record<string, unknown>;
  roles?: string[];
  collaborators?: string[];
  tools?: string[];
  metadata?: Record<string, unknown>;
  subscription_rule?: Partial<SubscriptionRule> | null;
}

export interface AgentUpdatePayload {
  name?: string;
  version?: string;
  purpose?: string;
  description?: string;
  approach?: string;
  status?: AgentStatus;
  visibility?: AgentVisibility;
  agent_card?: Record<string, unknown>;
  roles?: string[];
  collaborators?: string[];
  tools?: string[];
  metadata?: Record<string, unknown>;
}

export interface InvokeResult {
  agent_id: string;
  agent_name: string;
  model_used: string;
  input: string;
  output: string;
  tool_calls: Array<{ name: string; args: Record<string, unknown> }>;
  steps: Array<{ role: string; content: string; node?: string; name?: string; tool_calls?: unknown[] }>;
  transitions: Array<{ from: string; to: string; reason: string }>;
  checkpoint: {
    thread_id?: string;
    checkpoint_id?: string;
    next_nodes?: string[];
    resumable?: boolean;
  };
  graph: {
    name?: string;
    nodes?: string[];
    entrypoint?: string;
    checkpointer?: string;
  };
  error?: string | null;
}

export interface InvokeOptions {
  model?: string;
  checkpoint_thread_id?: string;
  resume?: boolean;
  interrupt_after_node?: 'agent_node' | 'mcp_tool_node';
}

export const agentsApi = {
  listTools: async (): Promise<ToolDescriptor[]> => {
    const res = await client.get<ToolDescriptor[]>('/agents/tools');
    return res.data;
  },

  listMyAgents: async (): Promise<Agent[]> => {
    const res = await client.get<Agent[]>('/agents');
    return res.data;
  },

  getAgent: async (agentId: string): Promise<Agent> => {
    const res = await client.get<Agent>(`/agents/${agentId}`);
    return res.data;
  },

  createAgent: async (payload: AgentCreatePayload): Promise<Agent> => {
    const res = await client.post<Agent>('/agents', payload);
    return res.data;
  },

  updateAgent: async (agentId: string, payload: AgentUpdatePayload): Promise<Agent> => {
    const res = await client.put<Agent>(`/agents/${agentId}`, payload);
    return res.data;
  },

  getSubscriptionRule: async (agentId: string): Promise<SubscriptionRule | null> => {
    const res = await client.get<SubscriptionRule | null>(`/agents/${agentId}/subscription-rule`);
    return res.data;
  },

  upsertSubscriptionRule: async (
    agentId: string,
    rule: Partial<SubscriptionRule>
  ): Promise<SubscriptionRule> => {
    const res = await client.put<SubscriptionRule>(
      `/agents/${agentId}/subscription-rule`,
      rule
    );
    return res.data;
  },

  invokeAgent: async (
    agentId: string,
    message: string,
    options?: InvokeOptions
  ): Promise<InvokeResult> => {
    const res = await client.post<InvokeResult>(`/agents/${agentId}/invoke`, {
      message,
      ...options,
    });
    return res.data;
  },
};
