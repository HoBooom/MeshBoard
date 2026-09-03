/**
 * MeshBoard — 운영 관리 (Operations Console)
 *
 * 회사 내부 운영자를 위한 최소 기능:
 * - 운영 현황 요약
 * - 에이전트 라이프사이클(상태) 관리
 * - 시스템 구성요소 상태
 * - 최근 실행 활동 로그
 */

import { useEffect, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  operationsApi,
  Activity,
  AgentOps,
  AgentStatus,
  HealthComponent,
  OperationsOverview,
  ExecutionNode,
  ExecutionSummary,
  OperationsAnalytics,
  ConnectorStatus,
} from '../api/operations';

const AGENT_STATUSES: AgentStatus[] = ['ACTIVE', 'DRAFT', 'SUSPENDED', 'DEPRECATED'];

const statusMeta: Record<AgentStatus, { label: string; cls: string }> = {
  ACTIVE: { label: '운영 중', cls: 'bg-[#34c759]/15 text-[#34c759] border-[#34c759]/30' },
  DRAFT: { label: '초안', cls: 'bg-white/10 text-white/60 border-white/15' },
  SUSPENDED: { label: '일시 중지', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  DEPRECATED: { label: '지원 종료', cls: 'bg-[#ff3b30]/15 text-[#ff453a] border-[#ff3b30]/30' },
};

const healthMeta: Record<string, string> = {
  online: 'bg-[#34c759]',
  degraded: 'bg-amber-400',
  offline: 'bg-[#ff3b30]',
};

function StatCard({ value, label, hint, accent }: { value: React.ReactNode; label: string; hint?: string; accent?: string }) {
  return (
    <div className="glass-card p-5">
      <p className={`text-[28px] font-semibold tracking-[0.196px] leading-[1.14] ${accent ?? 'text-white'}`}>{value}</p>
      <p className="text-[13px] text-white/60 tracking-[-0.13px] mt-1">{label}</p>
      {hint && <p className="text-[11px] text-white/35 mt-1.5">{hint}</p>}
    </div>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return '활동 없음';
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return '방금 전';
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  return `${Math.floor(hr / 24)}일 전`;
}

export default function OperationsPage() {
  const [overview, setOverview] = useState<OperationsOverview | null>(null);
  const [agents, setAgents] = useState<AgentOps[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [health, setHealth] = useState<HealthComponent[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [selectedExecution, setSelectedExecution] = useState<string | null>(null);
  const [executionNodes, setExecutionNodes] = useState<ExecutionNode[]>([]);
  const [analytics, setAnalytics] = useState<OperationsAnalytics | null>(null);
  const [connector, setConnector] = useState<ConnectorStatus | null>(null);
  const [connectorResult, setConnectorResult] = useState<string | null>(null);

  const reload = async () => {
    setLoading(true);
    try {
      const [ov, ag, ac, he, ex, an, connectorStatus] = await Promise.all([
        operationsApi.getOverview(),
        operationsApi.getAgents(),
        operationsApi.getActivity(20),
        operationsApi.getHealth(),
        operationsApi.getExecutions(),
        operationsApi.getAnalytics(),
        operationsApi.getSecurityConnector(),
      ]);
      setOverview(ov);
      setAgents(ag);
      setActivity(ac);
      setHealth(he);
      setExecutions(ex);
      setAnalytics(an);
      setConnector(connectorStatus);
    } finally {
      setLoading(false);
    }
  };

  const openExecution = async (executionTreeId: string) => {
    setSelectedExecution(executionTreeId);
    const tree = await operationsApi.getExecutionTree(executionTreeId);
    setExecutionNodes(tree.nodes);
  };

  useEffect(() => {
    reload();
  }, []);

  const changeStatus = async (agent: AgentOps, status: AgentStatus) => {
    setSavingId(agent.agent_id);
    try {
      await operationsApi.updateAgentStatus(agent.agent_id, status);
      const [ag, ov] = await Promise.all([operationsApi.getAgents(), operationsApi.getOverview()]);
      setAgents(ag);
      setOverview(ov);
    } finally {
      setSavingId(null);
    }
  };

  const testConnector = async () => {
    const result = await operationsApi.testSecurityConnector();
    setConnectorResult(
      !result.configured ? '환경 변수에 웹훅 URL이 설정되지 않았습니다.' : result.delivered ? `전송 성공 (${result.status_code})` : `전송 실패 (${result.error ?? '응답 없음'})`
    );
  };

  return (
    <div className="space-y-8 animate-fade-in font-apple">
      {/* Header */}
      <div className="pb-6 border-b border-surface-800">
        <h1 className="text-[34px] md:text-[40px] font-semibold text-white tracking-[-0.28px] leading-[1.1]">
          운영 관리
        </h1>
        <p className="text-[17px] text-white/60 tracking-[-0.374px] mt-2">
          조직 내 모든 에이전트의 운영 상태와 시스템 가동 현황을 한곳에서 관리합니다.
        </p>
      </div>

      {/* Overview */}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
          <StatCard value={overview.total_agents} label="전체 에이전트" hint={`운영 ${overview.status_breakdown.ACTIVE} · 초안 ${overview.status_breakdown.DRAFT}`} />
          <StatCard value={overview.status_breakdown.SUSPENDED + overview.status_breakdown.DEPRECATED} label="중지/종료" accent={overview.status_breakdown.SUSPENDED ? 'text-amber-400' : undefined} />
          <StatCard value={overview.interactions_24h} label="24시간 실행" hint={`누적 ${overview.total_interactions}`} />
          <StatCard value={`${overview.success_rate}%`} label="실행 성공률" accent={overview.success_rate >= 95 ? 'text-[#34c759]' : 'text-amber-400'} hint={`실패 ${overview.failed_interactions}`} />
          <StatCard value={overview.total_tokens.toLocaleString()} label="누적 토큰" />
        </div>
      )}

      {loading && <div className="text-white/40 text-[14px]">불러오는 중...</div>}

      {!loading && (
        <>
          {/* Agent lifecycle */}
          <section>
            <h3 className="text-[21px] font-semibold text-white tracking-[0.231px] mb-4">에이전트 운영 관리</h3>
            <div className="glass-card overflow-hidden">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-white/5 text-[12px] text-white/40 uppercase tracking-wider">
                    <th className="px-6 py-4 font-medium">에이전트</th>
                    <th className="px-4 py-4 font-medium">소유자</th>
                    <th className="px-4 py-4 font-medium">도구</th>
                    <th className="px-4 py-4 font-medium">최근 활동</th>
                    <th className="px-4 py-4 font-medium">상태</th>
                    <th className="px-6 py-4 font-medium text-right">상태 변경</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((a) => {
                    const meta = statusMeta[a.status];
                    return (
                      <tr key={a.agent_id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                        <td className="px-6 py-4">
                          <p className="text-[15px] font-medium text-white">{a.name}</p>
                          <p className="text-[12px] text-white/40 mt-0.5">v{a.version} · {a.visibility}</p>
                        </td>
                        <td className="px-4 py-4 text-[13px] text-white/60">{a.owner_name ?? '—'}</td>
                        <td className="px-4 py-4 text-[13px] text-white/60">{a.tool_count}개</td>
                        <td className="px-4 py-4 text-[13px] text-white/50">
                          {a.active_executions > 0 ? <span className="text-apple-blue">실행 중 {a.active_executions}건</span> : relativeTime(a.last_activity)}
                        </td>
                        <td className="px-4 py-4">
                          <span className={`px-2.5 py-1 text-[11px] font-medium rounded-full border whitespace-nowrap ${meta.cls}`}>{meta.label}</span>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <select
                            value={a.status}
                            disabled={savingId === a.agent_id}
                            onChange={(e) => changeStatus(a, e.target.value as AgentStatus)}
                            className="bg-apple-surface2 text-white text-[13px] rounded-[8px] px-3 py-1.5 border border-white/10 focus:outline-none focus:ring-2 focus:ring-apple-blue cursor-pointer disabled:opacity-50"
                          >
                            {AGENT_STATUSES.map((s) => (
                              <option key={s} value={s}>{statusMeta[s].label}</option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <div className="mb-4 flex items-end justify-between gap-4">
              <div>
                <h3 className="text-[21px] font-semibold text-white tracking-[0.231px]">A2A 실행 트리</h3>
                <p className="mt-1 text-[13px] text-white/40">메시지에서 에이전트 위임과 도구 실행까지 ltree 경로로 추적합니다.</p>
              </div>
              <span className="text-xs text-white/30">최근 {executions.length}건</span>
            </div>
            <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
              <div className="glass-card max-h-[440px] overflow-y-auto p-3">
                {executions.map((execution) => (
                  <button key={execution.execution_tree_id} onClick={() => openExecution(execution.execution_tree_id)} className={`mb-2 w-full rounded-xl border p-3 text-left last:mb-0 ${selectedExecution === execution.execution_tree_id ? 'border-apple-blue/50 bg-apple-blue/10' : 'border-white/5 bg-black/10 hover:bg-white/5'}`}>
                    <div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-medium text-white">{execution.actor_name}</span><span className={execution.state === 'FAILED' ? 'text-xs text-[#ff453a]' : 'text-xs text-[#30d158]'}>{execution.state}</span></div>
                    <p className="mt-1 truncate text-xs text-white/45">{execution.prompt || '메시지 실행'}</p>
                    <p className="mt-2 text-[11px] text-white/30">노드 {execution.node_count} · {execution.duration_ms ?? 0}ms · {relativeTime(execution.started_at)}</p>
                  </button>
                ))}
                {executions.length === 0 && <p className="py-12 text-center text-sm text-white/35">메시지를 실행하면 트리가 생성됩니다.</p>}
              </div>
              <div className="glass-card min-h-[240px] p-5">
                {executionNodes.length === 0 ? <p className="py-16 text-center text-sm text-white/35">왼쪽 실행을 선택해 위임 체인을 확인하세요.</p> : (
                  <div className="space-y-2">
                    {executionNodes.map((node) => (
                      <div key={node.interaction_id} className="relative rounded-xl border border-white/5 bg-black/10 p-3" style={{ marginLeft: `${Math.min(node.tree_depth, 4) * 24}px` }}>
                        {node.tree_depth > 0 && <span className="absolute -left-4 top-0 h-1/2 w-3 rounded-bl-lg border-b border-l border-white/15" />}
                        <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium text-white">{node.actor_name}{node.target_name ? ` → ${node.target_name}` : ''}</p><span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-white/45">{node.kind}</span></div>
                        <p className="mt-1 text-xs text-white/40">{node.payload.tool?.name || node.payload.reasoning || node.payload.output || node.error_message || node.state}</p>
                        <p className="mt-1 text-[10px] text-white/20">schema {node.payload.source_schema_version} → {node.payload.schema_version}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section>
            <div className="mb-4">
              <h3 className="text-[21px] font-semibold text-white tracking-[0.231px]">모델·병렬 실행 분석</h3>
              <p className="mt-1 text-[13px] text-white/40">모델별 토큰 사용량과 병렬 그룹의 wall time 절감 효과입니다.</p>
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <div className="glass-card h-[300px] p-5">
                <p className="mb-4 text-sm font-medium text-white/75">모델별 토큰</p>
                {analytics?.models.length ? (
                  <ResponsiveContainer width="100%" height="85%">
                    <BarChart data={analytics.models}>
                      <CartesianGrid stroke="rgba(255,255,255,.06)" vertical={false} />
                      <XAxis dataKey="model" tick={{ fill: 'rgba(255,255,255,.45)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fill: 'rgba(255,255,255,.4)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <Tooltip contentStyle={{ background: '#202020', border: '1px solid rgba(255,255,255,.1)', borderRadius: 10 }} />
                      <Bar dataKey="token_input" name="입력" stackId="tokens" fill="#0a84ff" />
                      <Bar dataKey="token_output" name="출력" stackId="tokens" fill="#64d2ff" radius={[5, 5, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <p className="py-24 text-center text-sm text-white/30">모델 사용 데이터가 없습니다.</p>}
              </div>
              <div className="glass-card h-[300px] p-5">
                <p className="mb-4 text-sm font-medium text-white/75">병렬 실행 시간</p>
                {analytics?.parallel_groups.length ? (
                  <ResponsiveContainer width="100%" height="85%">
                    <BarChart data={analytics.parallel_groups.map((group) => ({ ...group, group: group.parallel_group_id.slice(0, 6) }))}>
                      <CartesianGrid stroke="rgba(255,255,255,.06)" vertical={false} />
                      <XAxis dataKey="group" tick={{ fill: 'rgba(255,255,255,.45)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fill: 'rgba(255,255,255,.4)', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <Tooltip contentStyle={{ background: '#202020', border: '1px solid rgba(255,255,255,.1)', borderRadius: 10 }} />
                      <Bar dataKey="wall_duration_ms" name="실제 wall time" fill="#30d158" radius={[5, 5, 0, 0]} />
                      <Bar dataKey="saved_duration_ms" name="절감 시간" fill="#bf5af2" radius={[5, 5, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <p className="py-24 text-center text-sm text-white/30">병렬 그룹 데이터가 없습니다.</p>}
              </div>
            </div>
          </section>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* System health */}
            <section>
              <h3 className="text-[21px] font-semibold text-white tracking-[0.231px] mb-4">시스템 상태</h3>
              <div className="glass-card p-6 space-y-3">
                {health.map((c) => (
                  <div key={c.name} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                    <div className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full ${healthMeta[c.status] ?? 'bg-white/20'} ${c.status === 'online' ? 'animate-pulse' : ''}`} />
                      <span className="text-[14px] font-medium text-white/80">{c.name}</span>
                    </div>
                    <span className="text-[12px] text-white/45">{c.detail}</span>
                  </div>
                ))}
                <div className="flex items-center justify-between gap-3 pt-3">
                  <div className="min-w-0"><p className="truncate text-xs text-white/45">{connector?.endpoint || 'SECURITY_WEBHOOK_URL 미설정'}</p>{connectorResult && <p className="mt-1 text-[11px] text-white/35">{connectorResult}</p>}</div>
                  <button onClick={testConnector} className="rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white/70 hover:bg-white/15">테스트 전송</button>
                </div>
              </div>
            </section>

            {/* Activity log */}
            <section>
              <h3 className="text-[21px] font-semibold text-white tracking-[0.231px] mb-4">최근 실행 활동</h3>
              <div className="glass-card p-6">
                {activity.length === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-[14px] text-white/40">최근 실행 기록이 없습니다.</p>
                    <p className="text-[12px] text-white/25 mt-1.5">에이전트가 실행되면 실행 이력이 여기에 표시됩니다.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {activity.map((a) => (
                      <div key={a.interaction_id} className="flex items-start justify-between py-2 border-b border-white/5 last:border-0">
                        <div className="min-w-0">
                          <p className="text-[14px] text-white/85">
                            {a.actor_name}
                            {a.target_name && <span className="text-white/40"> → {a.target_name}</span>}
                          </p>
                          <p className="text-[12px] text-white/40 mt-0.5">
                            {a.kind} · {a.model_used ?? '—'}
                            {a.error_message && <span className="text-[#ff453a]"> · {a.error_message}</span>}
                          </p>
                        </div>
                        <div className="text-right flex-shrink-0 ml-3">
                          <p className="text-[11px] text-white/40">{relativeTime(a.start_timestamp)}</p>
                          <p className={`text-[11px] mt-0.5 ${a.state === 'FAILED' ? 'text-[#ff453a]' : a.state === 'COMPLETED' ? 'text-[#34c759]' : 'text-white/40'}`}>{a.state}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
