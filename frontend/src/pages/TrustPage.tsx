/**
 * MeshBoard — 신뢰 관리 (Trust Workbench)
 *
 * 회사 내부 거버넌스/신뢰 운영을 위한 최소 기능:
 * - 신뢰 현황 요약
 * - 에이전트별 신뢰 현황(인증·정책 연결)
 * - 정책 관리 (발급/상태)
 * - 인증 관리 (발급/심사 상태)
 */

import { useEffect, useState } from 'react';
import {
  trustApi,
  AgentTrust,
  Certification,
  CertState,
  Policy,
  PolicyStatus,
  TrustLevel,
  TrustOverview,
} from '../api/trust';

type Tab = 'agents' | 'policies' | 'certifications';

const trustLevelMeta: Record<TrustLevel, { label: string; cls: string }> = {
  certified: { label: '인증 완료', cls: 'bg-[#34c759]/15 text-[#34c759] border-[#34c759]/30' },
  partial: { label: '부분 검증', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  unverified: { label: '미검증', cls: 'bg-white/10 text-white/50 border-white/15' },
};

const policyStatusMeta: Record<PolicyStatus, { label: string; cls: string }> = {
  ACTIVE: { label: '활성', cls: 'bg-[#34c759]/15 text-[#34c759] border-[#34c759]/30' },
  DRAFT: { label: '초안', cls: 'bg-white/10 text-white/60 border-white/15' },
  REVOKED: { label: '폐기', cls: 'bg-[#ff3b30]/15 text-[#ff453a] border-[#ff3b30]/30' },
};

const certStateMeta: Record<CertState, { label: string; cls: string }> = {
  PASSED: { label: '통과', cls: 'bg-[#34c759]/15 text-[#34c759] border-[#34c759]/30' },
  PENDING: { label: '심사 대기', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  FAILED: { label: '반려', cls: 'bg-[#ff3b30]/15 text-[#ff453a] border-[#ff3b30]/30' },
  REVOKED: { label: '취소', cls: 'bg-white/10 text-white/50 border-white/15' },
};

function Badge({ label, cls }: { label: string; cls: string }) {
  return (
    <span className={`px-2.5 py-1 text-[11px] font-medium rounded-full border whitespace-nowrap ${cls}`}>
      {label}
    </span>
  );
}

function StatCard({ value, label, hint, accent }: { value: React.ReactNode; label: string; hint?: string; accent?: string }) {
  return (
    <div className="glass-card p-5">
      <p className={`text-[28px] font-semibold tracking-[0.196px] leading-[1.14] ${accent ?? 'text-white'}`}>{value}</p>
      <p className="text-[13px] text-white/60 tracking-[-0.13px] mt-1">{label}</p>
      {hint && <p className="text-[11px] text-white/35 mt-1.5">{hint}</p>}
    </div>
  );
}

export default function TrustPage() {
  const [tab, setTab] = useState<Tab>('agents');
  const [overview, setOverview] = useState<TrustOverview | null>(null);
  const [agents, setAgents] = useState<AgentTrust[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [certs, setCerts] = useState<Certification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [manageAgent, setManageAgent] = useState<AgentTrust | null>(null);

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, ag, po, ce] = await Promise.all([
        trustApi.getOverview(),
        trustApi.getAgents(),
        trustApi.getPolicies(),
        trustApi.getCertifications(),
      ]);
      setOverview(ov);
      setAgents(ag);
      setPolicies(po);
      setCerts(ce);
    } catch (e: unknown) {
      setError('데이터를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <div className="space-y-8 animate-fade-in font-apple">
      {/* Header */}
      <div className="pb-6 border-b border-surface-800">
        <h1 className="text-[34px] md:text-[40px] font-semibold text-white tracking-[-0.28px] leading-[1.1]">
          신뢰 관리
        </h1>
        <p className="text-[17px] text-white/60 tracking-[-0.374px] mt-2">
          에이전트의 인증·정책을 발급하고 연결하여 조직의 AI 신뢰 기준을 운영합니다.
        </p>
      </div>

      {/* Overview */}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
          <StatCard value={overview.total_agents} label="전체 에이전트" />
          <StatCard value={overview.certified_agents} label="인증 완료" accent="text-[#34c759]" hint={`부분 검증 ${overview.partial_agents} · 미검증 ${overview.unverified_agents}`} />
          <StatCard value={overview.pending_certifications} label="심사 대기 인증" accent={overview.pending_certifications ? 'text-amber-400' : undefined} />
          <StatCard value={overview.active_policies} label="활성 정책" hint={`초안 ${overview.draft_policies}`} />
          <StatCard
            value={overview.uncertified_exposed_agents}
            label="미인증 공개 에이전트"
            accent={overview.uncertified_exposed_agents ? 'text-[#ff453a]' : 'text-[#34c759]'}
            hint="PUBLIC/DEPARTMENT 중 미인증"
          />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-apple-surface1 p-1 rounded-[12px] w-fit">
        {([
          ['agents', '에이전트 신뢰현황'],
          ['policies', '정책 관리'],
          ['certifications', '인증 관리'],
        ] as [Tab, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-5 py-2 text-[14px] font-medium rounded-[9px] transition-colors ${
              tab === key ? 'bg-apple-surface2 text-white' : 'text-white/50 hover:text-white/80'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && <div className="text-[#ff453a] text-[14px]">{error}</div>}
      {loading && <div className="text-white/40 text-[14px]">불러오는 중...</div>}

      {!loading && tab === 'agents' && (
        <AgentTrustTable agents={agents} onManage={setManageAgent} />
      )}
      {!loading && tab === 'policies' && (
        <PolicyPanel policies={policies} onChanged={reload} />
      )}
      {!loading && tab === 'certifications' && (
        <CertPanel certs={certs} onChanged={reload} />
      )}

      {manageAgent && (
        <ManageAgentModal
          agent={manageAgent}
          allPolicies={policies}
          allCerts={certs}
          onClose={() => setManageAgent(null)}
          onChanged={reload}
        />
      )}
    </div>
  );
}

// ── 에이전트 신뢰현황 ───────────────────────────────────────────
function AgentTrustTable({ agents, onManage }: { agents: AgentTrust[]; onManage: (a: AgentTrust) => void }) {
  return (
    <div className="glass-card overflow-hidden">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-white/5 text-[12px] text-white/40 uppercase tracking-wider">
            <th className="px-6 py-4 font-medium">에이전트</th>
            <th className="px-4 py-4 font-medium">신뢰 등급</th>
            <th className="px-4 py-4 font-medium">인증</th>
            <th className="px-4 py-4 font-medium">정책</th>
            <th className="px-6 py-4 font-medium text-right">관리</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => {
            const meta = trustLevelMeta[a.trust_level];
            return (
              <tr key={a.agent_id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                <td className="px-6 py-4">
                  <p className="text-[15px] font-medium text-white">{a.name}</p>
                  <p className="text-[12px] text-white/40 mt-0.5">
                    v{a.version} · {a.visibility} · {a.owner_name ?? '—'}
                  </p>
                </td>
                <td className="px-4 py-4"><Badge label={meta.label} cls={meta.cls} /></td>
                <td className="px-4 py-4">
                  <div className="flex flex-wrap gap-1.5 max-w-[260px]">
                    {a.certifications.length === 0 && <span className="text-[12px] text-white/30">—</span>}
                    {a.certifications.map((c) => (
                      <Badge key={c.id} label={c.name} cls={certStateMeta[(c.state as CertState)]?.cls ?? 'bg-white/10 text-white/60 border-white/15'} />
                    ))}
                  </div>
                </td>
                <td className="px-4 py-4">
                  <div className="flex flex-wrap gap-1.5 max-w-[260px]">
                    {a.policies.length === 0 && <span className="text-[12px] text-white/30">—</span>}
                    {a.policies.map((p) => (
                      <Badge key={p.id} label={p.name} cls={policyStatusMeta[(p.state as PolicyStatus)]?.cls ?? 'bg-white/10 text-white/60 border-white/15'} />
                    ))}
                  </div>
                </td>
                <td className="px-6 py-4 text-right">
                  <button
                    onClick={() => onManage(a)}
                    className="text-[13px] text-apple-link hover:underline whitespace-nowrap"
                  >
                    연결 관리
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── 정책 관리 ───────────────────────────────────────────────────
function PolicyPanel({ policies, onChanged }: { policies: Policy[]; onChanged: () => void }) {
  const [name, setName] = useState('');
  const [purpose, setPurpose] = useState('');
  const [description, setDescription] = useState('');
  const [templateText, setTemplateText] = useState('{\n  "pii_masking": true,\n  "max_input_chars": 4000\n}');
  const [validationMessage, setValidationMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const template = JSON.parse(templateText) as Record<string, unknown>;
      const validation = await trustApi.validatePolicy(template);
      if (!validation.valid) {
        setValidationMessage(validation.errors.join(' '));
        return;
      }
      await trustApi.createPolicy({ name, purpose, description, template, status: 'DRAFT' });
      setName(''); setPurpose(''); setDescription('');
      setValidationMessage('템플릿 검증을 통과해 초안으로 저장했습니다.');
      onChanged();
    } catch (error) {
      setValidationMessage(error instanceof SyntaxError ? '템플릿 JSON 형식을 확인하세요.' : '정책을 저장하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  };

  const changeStatus = async (p: Policy, status: PolicyStatus) => {
    await trustApi.updatePolicyStatus(p.policy_id, status);
    onChanged();
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Create form */}
      <div className="glass-card p-6 lg:col-span-1 h-fit">
        <h3 className="text-[17px] font-semibold text-white mb-4">정책 발급</h3>
        <div className="space-y-3">
          <input className="input-field text-[15px]" placeholder="정책 이름" value={name} onChange={(e) => setName(e.target.value)} />
          <input className="input-field text-[15px]" placeholder="목적 (예: 개인정보 처리 통제)" value={purpose} onChange={(e) => setPurpose(e.target.value)} />
          <textarea className="input-field text-[15px] min-h-[88px]" placeholder="설명" value={description} onChange={(e) => setDescription(e.target.value)} />
          <textarea className="input-field min-h-[150px] font-mono text-[12px]" aria-label="정책 템플릿 JSON" value={templateText} onChange={(e) => setTemplateText(e.target.value)} />
          {validationMessage && <p className="text-[12px] leading-5 text-white/55">{validationMessage}</p>}
          <button onClick={create} disabled={busy || !name.trim()} className="btn-primary w-full text-[15px]">
            {busy ? '발급 중...' : '정책 발급 (초안)'}
          </button>
        </div>
      </div>

      {/* List */}
      <div className="lg:col-span-2 space-y-3">
        {policies.length === 0 && <div className="glass-card p-6 text-white/40 text-[14px]">등록된 정책이 없습니다.</div>}
        {policies.map((p) => {
          const meta = policyStatusMeta[p.status];
          return (
            <div key={p.policy_id} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h4 className="text-[16px] font-semibold text-white">{p.name}</h4>
                    <Badge label={meta.label} cls={meta.cls} />
                  </div>
                  {p.purpose && <p className="text-[13px] text-white/55 mt-1">{p.purpose}</p>}
                  {p.description && <p className="text-[13px] text-white/40 mt-1.5 leading-[1.5]">{p.description}</p>}
                  <p className="text-[12px] text-white/30 mt-2">적용 에이전트 {p.applied_count}개</p>
                </div>
                <div className="flex flex-col gap-1.5 flex-shrink-0">
                  {p.status !== 'ACTIVE' && (
                    <button onClick={() => changeStatus(p, 'ACTIVE')} className="text-[12px] px-3 py-1.5 rounded-[8px] bg-[#34c759]/15 text-[#34c759] hover:bg-[#34c759]/25 transition-colors">활성화</button>
                  )}
                  {p.status === 'ACTIVE' && (
                    <button onClick={() => changeStatus(p, 'REVOKED')} className="text-[12px] px-3 py-1.5 rounded-[8px] bg-[#ff3b30]/15 text-[#ff453a] hover:bg-[#ff3b30]/25 transition-colors">폐기</button>
                  )}
                  {p.status === 'REVOKED' && (
                    <button onClick={() => changeStatus(p, 'DRAFT')} className="text-[12px] px-3 py-1.5 rounded-[8px] bg-white/10 text-white/70 hover:bg-white/20 transition-colors">초안 복원</button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 인증 관리 ───────────────────────────────────────────────────
function CertPanel({ certs, onChanged }: { certs: Certification[]; onChanged: () => void }) {
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await trustApi.createCertification({ name, notes, state: 'PENDING' });
      setName(''); setNotes('');
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const changeState = async (c: Certification, state: CertState) => {
    await trustApi.updateCertState(c.certification_id, state);
    onChanged();
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="glass-card p-6 lg:col-span-1 h-fit">
        <h3 className="text-[17px] font-semibold text-white mb-4">인증 발급</h3>
        <div className="space-y-3">
          <input className="input-field text-[15px]" placeholder="인증 이름" value={name} onChange={(e) => setName(e.target.value)} />
          <textarea className="input-field text-[15px] min-h-[88px]" placeholder="심사 메모" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <button onClick={create} disabled={busy || !name.trim()} className="btn-primary w-full text-[15px]">
            {busy ? '발급 중...' : '인증 발급 (심사 대기)'}
          </button>
        </div>
      </div>

      <div className="lg:col-span-2 space-y-3">
        {certs.length === 0 && <div className="glass-card p-6 text-white/40 text-[14px]">등록된 인증이 없습니다.</div>}
        {certs.map((c) => {
          const meta = certStateMeta[c.state];
          return (
            <div key={c.certification_id} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h4 className="text-[16px] font-semibold text-white">{c.name}</h4>
                    <Badge label={meta.label} cls={meta.cls} />
                  </div>
                  {c.notes && <p className="text-[13px] text-white/45 mt-1.5 leading-[1.5]">{c.notes}</p>}
                  <p className="text-[12px] text-white/30 mt-2">
                    연결 에이전트 {c.linked_count}개
                    {c.expires_at && ` · 만료 ${new Date(c.expires_at).toLocaleDateString('ko-KR')}`}
                  </p>
                </div>
                <div className="flex flex-col gap-1.5 flex-shrink-0">
                  {c.state !== 'PASSED' && (
                    <button onClick={() => changeState(c, 'PASSED')} className="text-[12px] px-3 py-1.5 rounded-[8px] bg-[#34c759]/15 text-[#34c759] hover:bg-[#34c759]/25 transition-colors">승인</button>
                  )}
                  {c.state !== 'FAILED' && (
                    <button onClick={() => changeState(c, 'FAILED')} className="text-[12px] px-3 py-1.5 rounded-[8px] bg-[#ff3b30]/15 text-[#ff453a] hover:bg-[#ff3b30]/25 transition-colors">반려</button>
                  )}
                  {c.state === 'PASSED' && (
                    <button onClick={() => changeState(c, 'REVOKED')} className="text-[12px] px-3 py-1.5 rounded-[8px] bg-white/10 text-white/70 hover:bg-white/20 transition-colors">취소</button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 에이전트 연결 관리 모달 ─────────────────────────────────────
function ManageAgentModal({
  agent,
  allPolicies,
  allCerts,
  onClose,
  onChanged,
}: {
  agent: AgentTrust;
  allPolicies: Policy[];
  allCerts: Certification[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const linkedPolicyIds = new Set(agent.policies.map((p) => p.id));
  const linkedCertIds = new Set(agent.certifications.map((c) => c.id));

  const toggle = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      onChanged();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-apple-surface1 rounded-[16px] w-full max-w-lg max-h-[80vh] overflow-y-auto shadow-[0_5px_40px_rgba(0,0,0,0.5)] border border-white/5" onClick={(e) => e.stopPropagation()}>
        <div className="p-6 border-b border-white/5">
          <h3 className="text-[19px] font-semibold text-white">{agent.name} — 연결 관리</h3>
          <p className="text-[13px] text-white/45 mt-1">정책·인증을 연결하거나 해제합니다.</p>
        </div>

        <div className="p-6 space-y-6">
          <div>
            <p className="text-[13px] font-medium text-white/60 mb-3">인증</p>
            <div className="space-y-2">
              {allCerts.map((c) => {
                const linked = linkedCertIds.has(c.certification_id);
                return (
                  <div key={c.certification_id} className="flex items-center justify-between bg-apple-surface2 rounded-[10px] px-4 py-2.5">
                    <span className="text-[14px] text-white/85">{c.name} <span className="text-white/35 text-[12px]">· {certStateMeta[c.state].label}</span></span>
                    <button
                      disabled={busy}
                      onClick={() => toggle(() => linked ? trustApi.unlinkCertification(agent.agent_id, c.certification_id) : trustApi.linkCertification(agent.agent_id, c.certification_id))}
                      className={`text-[12px] px-3 py-1.5 rounded-[8px] transition-colors ${linked ? 'bg-[#ff3b30]/15 text-[#ff453a] hover:bg-[#ff3b30]/25' : 'bg-apple-blue/20 text-apple-link hover:bg-apple-blue/30'}`}
                    >
                      {linked ? '해제' : '연결'}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <p className="text-[13px] font-medium text-white/60 mb-3">정책</p>
            <div className="space-y-2">
              {allPolicies.map((p) => {
                const linked = linkedPolicyIds.has(p.policy_id);
                return (
                  <div key={p.policy_id} className="flex items-center justify-between bg-apple-surface2 rounded-[10px] px-4 py-2.5">
                    <span className="text-[14px] text-white/85">{p.name} <span className="text-white/35 text-[12px]">· {policyStatusMeta[p.status].label}</span></span>
                    <button
                      disabled={busy}
                      onClick={() => toggle(() => linked ? trustApi.unlinkPolicy(agent.agent_id, p.policy_id) : trustApi.linkPolicy(agent.agent_id, p.policy_id))}
                      className={`text-[12px] px-3 py-1.5 rounded-[8px] transition-colors ${linked ? 'bg-[#ff3b30]/15 text-[#ff453a] hover:bg-[#ff3b30]/25' : 'bg-apple-blue/20 text-apple-link hover:bg-apple-blue/30'}`}
                    >
                      {linked ? '해제' : '연결'}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="p-6 border-t border-white/5 flex justify-end">
          <button onClick={onClose} className="btn-secondary text-[15px]">닫기</button>
        </div>
      </div>
    </div>
  );
}
