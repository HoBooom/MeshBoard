import client from './client';

export type PolicyStatus = 'DRAFT' | 'ACTIVE' | 'REVOKED';
export type CertState = 'PENDING' | 'PASSED' | 'FAILED' | 'REVOKED';
export type TrustLevel = 'certified' | 'partial' | 'unverified';

export interface Policy {
  policy_id: string;
  name: string;
  purpose: string | null;
  description: string | null;
  template: Record<string, unknown>;
  status: PolicyStatus;
  created_at: string;
  updated_at: string;
  applied_count: number;
}

export interface Certification {
  certification_id: string;
  name: string;
  certifier_id: string | null;
  state: CertState;
  notes: string | null;
  issued_at: string | null;
  expires_at: string | null;
  created_at: string;
  linked_count: number;
}

export interface TrustBadge {
  id: string;
  name: string;
  state: string;
}

export interface AgentTrust {
  agent_id: string;
  name: string;
  version: string;
  status: string;
  visibility: string;
  owner_name: string | null;
  certifications: TrustBadge[];
  policies: TrustBadge[];
  trust_level: TrustLevel;
}

export interface TrustOverview {
  total_agents: number;
  certified_agents: number;
  partial_agents: number;
  unverified_agents: number;
  pending_certifications: number;
  active_policies: number;
  draft_policies: number;
  uncertified_exposed_agents: number;
}

export const trustApi = {
  getOverview: () => client.get<TrustOverview>('/trust/overview').then((r) => r.data),
  getAgents: () => client.get<AgentTrust[]>('/trust/agents').then((r) => r.data),

  getPolicies: () => client.get<Policy[]>('/trust/policies').then((r) => r.data),
  createPolicy: (payload: {
    name: string;
    purpose?: string;
    description?: string;
    template?: Record<string, unknown>;
    status?: PolicyStatus;
  }) => client.post<Policy>('/trust/policies', payload).then((r) => r.data),
  updatePolicyStatus: (policyId: string, status: PolicyStatus) =>
    client
      .patch<Policy>(`/trust/policies/${policyId}/status`, { status })
      .then((r) => r.data),

  getCertifications: () =>
    client.get<Certification[]>('/trust/certifications').then((r) => r.data),
  createCertification: (payload: {
    name: string;
    notes?: string;
    state?: CertState;
    expires_at?: string | null;
  }) =>
    client.post<Certification>('/trust/certifications', payload).then((r) => r.data),
  updateCertState: (certId: string, state: CertState, notes?: string) =>
    client
      .patch<Certification>(`/trust/certifications/${certId}/state`, { state, notes })
      .then((r) => r.data),

  linkPolicy: (agentId: string, policyId: string) =>
    client.post(`/trust/agents/${agentId}/policies`, { policy_id: policyId }),
  unlinkPolicy: (agentId: string, policyId: string) =>
    client.delete(`/trust/agents/${agentId}/policies/${policyId}`),
  linkCertification: (agentId: string, certificationId: string) =>
    client.post(`/trust/agents/${agentId}/certifications`, {
      certification_id: certificationId,
    }),
  unlinkCertification: (agentId: string, certId: string) =>
    client.delete(`/trust/agents/${agentId}/certifications/${certId}`),
};
