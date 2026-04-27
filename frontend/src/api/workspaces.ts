import client from './client';
import { Agent } from './agents';

export interface Workspace {
  workspace_id: string;
  name?: string | null;
  owner_id: string;
  state: string;
  created_at: string;
  updated_at: string;
  agents: Agent[];
}

export interface RoutingSummary {
  queued: boolean;
  queue_message_id?: string | null;
  matched_agent_ids: string[];
  receipt_ids: string[];
  ignored_agent_ids: string[];
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
  routing: RoutingSummary;
}

export const workspacesApi = {
  list: async (): Promise<Workspace[]> => {
    const res = await client.get<Workspace[]>('/workspaces');
    return res.data;
  },

  create: async (name: string, agentIds: string[]): Promise<Workspace> => {
    const res = await client.post<Workspace>('/workspaces', {
      name,
      agent_ids: agentIds,
    });
    return res.data;
  },

  updateAgents: async (workspaceId: string, agentIds: string[]): Promise<Workspace> => {
    const res = await client.put<Workspace>(`/workspaces/${workspaceId}/agents`, {
      agent_ids: agentIds,
    });
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
    }
  ): Promise<PublishMessageResult> => {
    const res = await client.post<PublishMessageResult>('/messages/publish', {
      ...payload,
      workspace_id: workspaceId,
      scope: 'workspace',
    });
    return res.data;
  },
};
