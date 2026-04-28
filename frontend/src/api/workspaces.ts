import client from './client';
import { Agent } from './agents';

export interface WorkspacePlacement {
  agent: Agent;
  quantity: number;
}

export interface Workspace {
  workspace_id: string;
  name?: string | null;
  description?: string | null;
  tags: string[];
  owner_id: string;
  state: string;
  created_at: string;
  updated_at: string;
  placements: WorkspacePlacement[];
  active_agent_count: number;
  recent_message_count: number;
  access_status: 'system' | 'owner' | 'approved' | 'pending' | 'none';
  pending_request_id?: string | null;
  user_can_access: boolean;
  user_can_manage: boolean;
}

export interface WorkspaceMessage {
  message_id: string;
  sender_id: string;
  sender_type: string;
  sender_name?: string | null;
  domain?: string | null;
  intent?: string | null;
  conversation_id?: string | null;
  priority: string;
  tags: string[];
  body_ref: string;
  sent_at: string;
  processed_count: number;
  queued: boolean;
  receipt_count: number;
}

export interface Goal {
  goal_id: string;
  workspace_id: string;
  parent_goal_id?: string | null;
  conversation_id?: string | null;
  name: string;
  description?: string | null;
  priority: 'low' | 'medium' | 'high' | 'critical';
  state: 'pending' | 'running' | 'blocked' | 'completed' | 'failed';
  assigned_agent_ids: string[];
  success_criteria?: string | null;
  recent_message_count: number;
  progress: number;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceDetail extends Workspace {
  messages: WorkspaceMessage[];
  goals: Goal[];
}

export interface WorkspaceAccessRequest {
  request_id: string;
  workspace_id: string;
  requester_id: string;
  reason?: string | null;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  decided_by?: string | null;
  decided_at?: string | null;
  created_at: string;
}

export interface PublishMessageResult {
  accepted: boolean;
  message: {
    message_id: string;
    domain?: string | null;
    intent?: string | null;
    priority: string;
    tags: string[];
    scope: string;
    workspace_id?: string | null;
    body_ref: string;
    processed_count: number;
    sent_at: string;
  };
  routing: {
    queued: boolean;
    queue_message_id?: string | null;
    matched_agent_ids: string[];
    receipt_ids: string[];
    ignored_agent_ids: string[];
  };
}

export const workspacesApi = {
  list: async (): Promise<Workspace[]> => {
    const res = await client.get<Workspace[]>('/workspaces');
    return res.data;
  },

  get: async (workspaceId: string): Promise<WorkspaceDetail> => {
    const res = await client.get<WorkspaceDetail>(`/workspaces/${workspaceId}`);
    return res.data;
  },

  delete: async (workspaceId: string): Promise<void> => {
    await client.delete(`/workspaces/${workspaceId}`);
  },

  create: async (payload: {
    name: string;
    description?: string;
    tags?: string[];
    agent_placements: Array<{ agent_id: string; quantity: number }>;
  }): Promise<Workspace> => {
    const res = await client.post<Workspace>('/workspaces', payload);
    return res.data;
  },

  updateAgents: async (
    workspaceId: string,
    agentPlacements: Array<{ agent_id: string; quantity: number }>
  ): Promise<Workspace> => {
    const res = await client.put<Workspace>(`/workspaces/${workspaceId}/agents`, {
      agent_placements: agentPlacements,
    });
    return res.data;
  },

  listMessages: async (workspaceId: string, conversationId?: string | null): Promise<WorkspaceMessage[]> => {
    const res = await client.get<WorkspaceMessage[]>(`/workspaces/${workspaceId}/messages`, {
      params: conversationId ? { conversation_id: conversationId } : undefined,
    });
    return res.data;
  },

  listGoals: async (workspaceId: string): Promise<Goal[]> => {
    const res = await client.get<Goal[]>(`/workspaces/${workspaceId}/goals`);
    return res.data;
  },

  createGoal: async (
    workspaceId: string,
    payload: {
      name: string;
      description?: string;
      priority?: Goal['priority'];
      state?: Goal['state'];
      parent_goal_id?: string | null;
      assigned_agent_ids?: string[];
      success_criteria?: string;
    }
  ): Promise<Goal> => {
    const res = await client.post<Goal>(`/workspaces/${workspaceId}/goals`, payload);
    return res.data;
  },

  updateGoal: async (
    workspaceId: string,
    goalId: string,
    payload: Partial<Pick<Goal, 'name' | 'description' | 'priority' | 'state' | 'assigned_agent_ids' | 'success_criteria'>>
  ): Promise<Goal> => {
    const res = await client.put<Goal>(`/workspaces/${workspaceId}/goals/${goalId}`, payload);
    return res.data;
  },

  publish: async (
    workspaceId: string,
    payload: {
      domain: string;
      intent: string;
      payload: Record<string, unknown>;
      priority?: 'low' | 'medium' | 'high' | 'critical';
      tags?: string[];
      conversation_id?: string | null;
    }
  ): Promise<PublishMessageResult> => {
    const res = await client.post<PublishMessageResult>('/messages/publish', {
      ...payload,
      workspace_id: workspaceId,
      scope: 'workspace',
    });
    return res.data;
  },

  requestAccess: async (workspaceId: string, reason?: string): Promise<WorkspaceAccessRequest> => {
    const res = await client.post<WorkspaceAccessRequest>(
      `/workspaces/${workspaceId}/access-requests`,
      { reason }
    );
    return res.data;
  },

  listAccessRequests: async (): Promise<WorkspaceAccessRequest[]> => {
    const res = await client.get<WorkspaceAccessRequest[]>('/workspaces/access-requests');
    return res.data;
  },

  approveAccessRequest: async (requestId: string): Promise<WorkspaceAccessRequest> => {
    const res = await client.post<WorkspaceAccessRequest>(
      `/workspaces/access-requests/${requestId}/approve`
    );
    return res.data;
  },

  rejectAccessRequest: async (requestId: string): Promise<WorkspaceAccessRequest> => {
    const res = await client.post<WorkspaceAccessRequest>(
      `/workspaces/access-requests/${requestId}/reject`
    );
    return res.data;
  },
};
