import client from './client';

export interface AgentCard {
  agent_id: string;
  name: string;
  version: string;
  purpose?: string;
  description?: string;
  status: string;
  visibility: string;
  metadata_: {
    category?: string;
    [key: string]: any;
  };
  roles: string[];
  tools: string[];
  created_at: string;
}

export const getAgents = async (q?: string, category?: string): Promise<AgentCard[]> => {
  const params = new URLSearchParams();
  if (q) params.append('q', q);
  if (category && category !== 'All') params.append('category', category);
  
  const response = await client.get(`/marketplace/agents?${params.toString()}`);
  return response.data;
};
