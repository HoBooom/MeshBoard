import client from './client';
import type { Workspace } from './workspaces';


export interface SandboxDecision {
  sequence: number;
  agent_id: string;
  agent_name: string;
  action: 'consume' | 'handoff' | 'skip';
  reason: string;
  status: 'SIMULATED' | 'SKIPPED';
}

export interface SandboxRun {
  run_id: string;
  workspace_id: string;
  created_by: string;
  scenario_name: string;
  status: 'COMPLETED' | 'FAILED';
  event: {
    domain: string;
    intent: string;
    message: string;
    priority: string;
    tags: string[];
  };
  decision_log: SandboxDecision[];
  routed_agent_ids: string[];
  production_write_count: number;
  isolation: {
    mode: 'sandbox_only';
    message_headers_written: number;
    messages_written: number;
    interactions_written: number;
  };
  created_at: string;
  completed_at?: string | null;
}

export const sandboxApi = {
  listWorkspaces: async (): Promise<Workspace[]> => {
    const response = await client.get<Workspace[]>('/sandbox/workspaces');
    return response.data;
  },

  createWorkspace: async (payload: {
    name: string;
    description?: string;
    agent_placements: Array<{ agent_id: string; quantity: number }>;
  }): Promise<Workspace> => {
    const response = await client.post<Workspace>('/sandbox/workspaces', payload);
    return response.data;
  },

  listRuns: async (workspaceId: string): Promise<SandboxRun[]> => {
    const response = await client.get<SandboxRun[]>(`/sandbox/workspaces/${workspaceId}/runs`);
    return response.data;
  },

  run: async (
    workspaceId: string,
    payload: {
      scenario_name: string;
      domain: string;
      intent: string;
      message: string;
      priority: 'low' | 'medium' | 'high' | 'critical';
      tags: string[];
    }
  ): Promise<SandboxRun> => {
    const response = await client.post<SandboxRun>(`/sandbox/workspaces/${workspaceId}/runs`, payload);
    return response.data;
  },
};
