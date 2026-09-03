import { useCallback, useEffect, useMemo, useState } from 'react';

import { agentsApi, type Agent } from '../api/agents';
import { sandboxApi, type SandboxRun } from '../api/sandbox';
import type { Workspace } from '../api/workspaces';


const DEFAULT_SCENARIO = {
  scenario_name: '긴급 이벤트 라우팅 점검',
  domain: 'security',
  intent: 'incident',
  message: 'critical 이벤트의 담당 에이전트 라우팅과 후속 위임을 점검합니다.',
  priority: 'critical' as const,
  tags: 'alert, sandbox',
};

export default function SandboxPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [sandboxes, setSandboxes] = useState<Workspace[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [runs, setRuns] = useState<SandboxRun[]>([]);
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [sandboxName, setSandboxName] = useState('Agent Mesh 안전성 검증');
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [agentRows, sandboxRows] = await Promise.all([
        agentsApi.listMyAgents(),
        sandboxApi.listWorkspaces(),
      ]);
      setAgents(agentRows);
      setSandboxes(sandboxRows);
      setSelectedId((current) => current || sandboxRows[0]?.workspace_id || '');
    } catch (err) {
      setError(detail(err, '샌드박스 정보를 불러오지 못했습니다.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setRuns([]);
      return;
    }
    sandboxApi.listRuns(selectedId).then(setRuns).catch((err) => setError(detail(err, '실행 기록을 불러오지 못했습니다.')));
  }, [selectedId]);

  const selected = useMemo(
    () => sandboxes.find((sandbox) => sandbox.workspace_id === selectedId) ?? null,
    [sandboxes, selectedId]
  );

  const createSandbox = async () => {
    if (!sandboxName.trim() || selectedAgents.length === 0) {
      setError('샌드박스 이름과 한 개 이상의 에이전트를 선택하세요.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await sandboxApi.createWorkspace({
        name: sandboxName.trim(),
        description: '운영 메시지와 상호작용을 기록하지 않는 격리 검증 환경',
        agent_placements: selectedAgents.map((agent_id) => ({ agent_id, quantity: 1 })),
      });
      setSandboxes((current) => [created, ...current]);
      setSelectedId(created.workspace_id);
      setSelectedAgents([]);
    } catch (err) {
      setError(detail(err, '샌드박스를 만들지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };

  const runScenario = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const run = await sandboxApi.run(selectedId, {
        scenario_name: scenario.scenario_name,
        domain: scenario.domain,
        intent: scenario.intent,
        message: scenario.message,
        priority: scenario.priority,
        tags: scenario.tags.split(',').map((tag) => tag.trim()).filter(Boolean),
      });
      setRuns((current) => [run, ...current]);
    } catch (err) {
      setError(detail(err, '시나리오 실행에 실패했습니다.'));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <div className="py-24 text-center text-white/55">격리 환경을 준비하는 중입니다…</div>;
  }

  return (
    <div className="animate-fade-in font-apple space-y-6">
      <header className="flex flex-col gap-2 border-b border-white/10 pb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-[40px] font-semibold tracking-[-0.28px] text-white">Sandbox</h1>
          <span className="rounded-full border border-[#30d158]/30 bg-[#30d158]/10 px-3 py-1 text-xs font-medium text-[#30d158]">운영 데이터 격리</span>
        </div>
        <p className="text-[16px] text-white/55">가상 이벤트의 구독·멘션·에이전트 위임 경로를 실제 운영 기록 없이 검증합니다.</p>
      </header>

      {error && <div className="rounded-xl border border-[#ff453a]/25 bg-[#ff453a]/10 px-4 py-3 text-sm text-[#ff6961]">{error}</div>}

      <section className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4 rounded-2xl border border-white/5 bg-apple-surface1 p-5">
          <div>
            <h2 className="text-lg font-semibold text-white">격리 환경 만들기</h2>
            <p className="mt-1 text-xs leading-5 text-white/45">ACTIVE 에이전트의 구독 규칙을 복제해 결정론적으로 리허설합니다.</p>
          </div>
          <input className="input-field w-full" value={sandboxName} onChange={(event) => setSandboxName(event.target.value)} placeholder="샌드박스 이름" />
          <div className="max-h-52 space-y-2 overflow-y-auto pr-1">
            {agents.map((agent) => {
              const checked = selectedAgents.includes(agent.agent_id);
              return (
                <label key={agent.agent_id} className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition-colors ${checked ? 'border-apple-blue/60 bg-apple-blue/10' : 'border-white/5 bg-black/10 hover:bg-white/5'}`}>
                  <input type="checkbox" checked={checked} onChange={() => setSelectedAgents((current) => checked ? current.filter((id) => id !== agent.agent_id) : [...current, agent.agent_id])} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-white">{agent.name}</span>
                    <span className="text-xs text-white/40">{agent.status} · 구독 {agent.subscription_rule?.is_active ? '활성' : '없음'}</span>
                  </span>
                </label>
              );
            })}
          </div>
          <button className="btn-primary w-full disabled:opacity-40" disabled={busy} onClick={createSandbox}>격리 환경 생성</button>

          <div className="border-t border-white/10 pt-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-white/35">환경 선택</p>
            <div className="space-y-2">
              {sandboxes.map((sandbox) => (
                <button key={sandbox.workspace_id} onClick={() => setSelectedId(sandbox.workspace_id)} className={`w-full rounded-xl border p-3 text-left ${selectedId === sandbox.workspace_id ? 'border-[#30d158]/50 bg-[#30d158]/10' : 'border-white/5 bg-black/10'}`}>
                  <span className="block truncate text-sm font-medium text-white">{sandbox.name}</span>
                  <span className="text-xs text-white/40">에이전트 {sandbox.agent_count}개 · {sandbox.state}</span>
                </button>
              ))}
              {sandboxes.length === 0 && <p className="rounded-xl border border-dashed border-white/10 p-4 text-center text-xs text-white/35">생성된 샌드박스가 없습니다.</p>}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <section className="rounded-2xl border border-white/5 bg-apple-surface1 p-6">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">시나리오 이벤트</h2>
                <p className="mt-1 text-xs text-white/45">{selected ? `${selected.name}에 이벤트를 주입합니다.` : '먼저 격리 환경을 선택하세요.'}</p>
              </div>
              <span className="text-xs text-white/35">운영 쓰기 0건 보장</span>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <input className="input-field" value={scenario.scenario_name} onChange={(event) => setScenario({ ...scenario, scenario_name: event.target.value })} placeholder="시나리오 이름" />
              <select className="input-field" value={scenario.priority} onChange={(event) => setScenario({ ...scenario, priority: event.target.value as typeof scenario.priority })}>
                <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
              </select>
              <input className="input-field" value={scenario.domain} onChange={(event) => setScenario({ ...scenario, domain: event.target.value })} placeholder="domain" />
              <input className="input-field" value={scenario.intent} onChange={(event) => setScenario({ ...scenario, intent: event.target.value })} placeholder="intent" />
              <input className="input-field md:col-span-2" value={scenario.tags} onChange={(event) => setScenario({ ...scenario, tags: event.target.value })} placeholder="tags (쉼표 구분)" />
              <textarea className="input-field min-h-24 md:col-span-2" value={scenario.message} onChange={(event) => setScenario({ ...scenario, message: event.target.value })} placeholder="가상 이벤트 메시지" />
            </div>
            <button className="btn-primary mt-4 disabled:opacity-40" disabled={!selectedId || busy} onClick={runScenario}>{busy ? '실행 중…' : '안전 리허설 실행'}</button>
          </section>

          <section className="rounded-2xl border border-white/5 bg-apple-surface1 p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">의사결정 로그</h2>
            {runs.length === 0 ? (
              <div className="rounded-xl border border-dashed border-white/10 py-12 text-center text-sm text-white/35">실행 결과가 여기에 표시됩니다.</div>
            ) : runs.map((run) => (
              <article key={run.run_id} className="mb-4 rounded-xl border border-white/5 bg-black/15 p-4 last:mb-0">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div><h3 className="text-sm font-semibold text-white">{run.scenario_name}</h3><p className="text-xs text-white/35">{new Date(run.created_at).toLocaleString('ko-KR')} · 라우팅 {run.routed_agent_ids.length}개</p></div>
                  <span className="rounded-full bg-[#30d158]/10 px-2.5 py-1 text-xs text-[#30d158]">운영 쓰기 {run.production_write_count}</span>
                </div>
                <div className="space-y-2">
                  {run.decision_log.map((row) => (
                    <div key={`${run.run_id}-${row.sequence}`} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 rounded-lg bg-white/[0.03] px-3 py-2">
                      <span className="text-center text-xs text-white/30">{row.sequence}</span>
                      <div className="min-w-0"><p className="truncate text-sm text-white/85">{row.agent_name}</p><p className="truncate text-xs text-white/35">{row.reason}</p></div>
                      <span className={`text-xs font-medium ${row.status === 'SIMULATED' ? 'text-apple-blue' : 'text-white/35'}`}>{row.action}</span>
                    </div>
                  ))}
                  {run.decision_log.length === 0 && <p className="text-xs text-white/35">배치된 에이전트가 없습니다.</p>}
                </div>
              </article>
            ))}
          </section>
        </div>
      </section>
    </div>
  );
}

function detail(error: unknown, fallback: string): string {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}
