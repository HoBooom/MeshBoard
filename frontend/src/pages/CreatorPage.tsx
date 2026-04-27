import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Agent,
  AgentCreatePayload,
  AgentStatus,
  AgentUpdatePayload,
  AgentVisibility,
  InvokeResult,
  RulePriority,
  SubscriptionRule,
  ToolDescriptor,
  agentsApi,
} from '../api/agents';

const STATUS_OPTIONS: AgentStatus[] = ['DRAFT', 'ACTIVE', 'DEPRECATED', 'SUSPENDED'];
const VISIBILITY_OPTIONS: AgentVisibility[] = ['PRIVATE', 'DEPARTMENT', 'PUBLIC'];
const PRIORITY_OPTIONS: RulePriority[] = ['low', 'medium', 'high', 'critical'];

const STATUS_BADGE: Record<AgentStatus, string> = {
  DRAFT: 'bg-white/10 text-white/70 border border-white/15',
  ACTIVE: 'bg-[#34c759]/15 text-[#34c759] border border-[#34c759]/30',
  DEPRECATED: 'bg-white/10 text-white/50 border border-white/15',
  SUSPENDED: 'bg-[#ff3b30]/15 text-[#ff3b30] border border-[#ff3b30]/30',
};

interface FormState {
  name: string;
  version: string;
  purpose: string;
  description: string;
  approach: string;
  status: AgentStatus;
  visibility: AgentVisibility;
  rolesInput: string;
  collaboratorsInput: string;
  category: string;
  systemPrompt: string;
  selectedTools: string[];
  watchDomains: string;
  watchIntents: string;
  watchTags: string;
  minPriority: RulePriority;
  ruleActive: boolean;
}

const EMPTY_FORM: FormState = {
  name: '',
  version: '1.0.0',
  purpose: '',
  description: '',
  approach: '',
  status: 'DRAFT',
  visibility: 'PRIVATE',
  rolesInput: '',
  collaboratorsInput: '',
  category: '',
  systemPrompt: '',
  selectedTools: [],
  watchDomains: '',
  watchIntents: '',
  watchTags: '',
  minPriority: 'medium',
  ruleActive: true,
};

function csvToList(text: string): string[] {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function listToCsv(items: string[] | undefined): string {
  return (items || []).join(', ');
}

function agentToForm(agent: Agent, rule: SubscriptionRule | null): FormState {
  const metadata = (agent.metadata_ || {}) as Record<string, unknown>;
  const card = (agent.agent_card || {}) as Record<string, unknown>;
  return {
    name: agent.name,
    version: agent.version,
    purpose: agent.purpose ?? '',
    description: agent.description ?? '',
    approach: agent.approach ?? '',
    status: agent.status,
    visibility: agent.visibility,
    rolesInput: listToCsv(agent.roles),
    collaboratorsInput: listToCsv(agent.collaborators),
    category: typeof metadata.category === 'string' ? (metadata.category as string) : '',
    systemPrompt: typeof card.system_prompt === 'string' ? (card.system_prompt as string) : '',
    selectedTools: [...(agent.tools || [])],
    watchDomains: listToCsv(rule?.watch_domains),
    watchIntents: listToCsv(rule?.watch_intents),
    watchTags: listToCsv(rule?.watch_tags),
    minPriority: (rule?.min_priority as RulePriority) || 'medium',
    ruleActive: rule?.is_active ?? true,
  };
}

function formToCreatePayload(form: FormState): AgentCreatePayload {
  const metadata: Record<string, unknown> = {};
  if (form.category.trim()) metadata.category = form.category.trim();

  const agentCard: Record<string, unknown> = {};
  if (form.systemPrompt.trim()) agentCard.system_prompt = form.systemPrompt.trim();

  return {
    name: form.name.trim(),
    version: form.version.trim(),
    purpose: form.purpose.trim() || undefined,
    description: form.description.trim() || undefined,
    approach: form.approach.trim() || undefined,
    status: form.status,
    visibility: form.visibility,
    agent_card: agentCard,
    roles: csvToList(form.rolesInput),
    collaborators: csvToList(form.collaboratorsInput),
    tools: [...form.selectedTools],
    metadata,
    subscription_rule: {
      watch_domains: csvToList(form.watchDomains),
      watch_intents: csvToList(form.watchIntents),
      watch_tags: csvToList(form.watchTags),
      watch_senders: [],
      watch_roles: [],
      ignore_senders: [],
      ignore_tags: [],
      min_priority: form.minPriority,
      is_active: form.ruleActive,
    },
  };
}

function formToUpdatePayload(form: FormState): AgentUpdatePayload {
  const metadata: Record<string, unknown> = {};
  if (form.category.trim()) metadata.category = form.category.trim();
  const agentCard: Record<string, unknown> = {};
  if (form.systemPrompt.trim()) agentCard.system_prompt = form.systemPrompt.trim();

  return {
    name: form.name.trim(),
    version: form.version.trim(),
    purpose: form.purpose.trim() || undefined,
    description: form.description.trim() || undefined,
    approach: form.approach.trim() || undefined,
    status: form.status,
    visibility: form.visibility,
    agent_card: agentCard,
    roles: csvToList(form.rolesInput),
    collaborators: csvToList(form.collaboratorsInput),
    tools: [...form.selectedTools],
    metadata,
  };
}

function formToRulePayload(form: FormState): Partial<SubscriptionRule> {
  return {
    watch_domains: csvToList(form.watchDomains),
    watch_intents: csvToList(form.watchIntents),
    watch_tags: csvToList(form.watchTags),
    watch_senders: [],
    watch_roles: [],
    ignore_senders: [],
    ignore_tags: [],
    min_priority: form.minPriority,
    is_active: form.ruleActive,
  };
}

export default function CreatorPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [loading, setLoading] = useState(true);
  const [editorMode, setEditorMode] = useState<'closed' | 'create' | 'edit'>('closed');
  const [activeAgent, setActiveAgent] = useState<Agent | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [invokeMessage, setInvokeMessage] = useState('');
  const [invoking, setInvoking] = useState(false);
  const [invokeResult, setInvokeResult] = useState<InvokeResult | null>(null);
  const [invokeError, setInvokeError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [myAgents, toolCatalog] = await Promise.all([
        agentsApi.listMyAgents(),
        agentsApi.listTools(),
      ]);
      setAgents(myAgents);
      setTools(toolCatalog);
    } catch (err) {
      console.error('Failed to load creator data', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const openCreate = () => {
    setActiveAgent(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setInvokeResult(null);
    setInvokeError(null);
    setEditorMode('create');
  };

  const openEdit = async (agent: Agent) => {
    setActiveAgent(agent);
    setFormError(null);
    setInvokeResult(null);
    setInvokeError(null);
    setEditorMode('edit');
    try {
      const rule = await agentsApi.getSubscriptionRule(agent.agent_id);
      setForm(agentToForm(agent, rule));
    } catch (err) {
      console.error(err);
      setForm(agentToForm(agent, agent.subscription_rule ?? null));
    }
  };

  const closeEditor = () => {
    setEditorMode('closed');
    setActiveAgent(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setInvokeResult(null);
    setInvokeError(null);
  };

  const handleToolToggle = (toolId: string) => {
    setForm((prev) => ({
      ...prev,
      selectedTools: prev.selectedTools.includes(toolId)
        ? prev.selectedTools.filter((id) => id !== toolId)
        : [...prev.selectedTools, toolId],
    }));
  };

  const handleFormField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setFormError(null);
    if (!form.name.trim() || !form.version.trim()) {
      setFormError('에이전트 이름과 버전은 필수입니다.');
      return;
    }
    setSaving(true);
    try {
      if (editorMode === 'create') {
        const created = await agentsApi.createAgent(formToCreatePayload(form));
        await loadAll();
        await openEdit(created);
      } else if (editorMode === 'edit' && activeAgent) {
        await agentsApi.updateAgent(activeAgent.agent_id, formToUpdatePayload(form));
        await agentsApi.upsertSubscriptionRule(activeAgent.agent_id, formToRulePayload(form));
        const refreshed = await agentsApi.getAgent(activeAgent.agent_id);
        setActiveAgent(refreshed);
        await loadAll();
      }
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '저장 중 오류가 발생했습니다.';
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleInvoke = async () => {
    if (!activeAgent) return;
    if (!invokeMessage.trim()) {
      setInvokeError('에이전트에 전달할 메시지를 입력하세요.');
      return;
    }
    setInvokeError(null);
    setInvoking(true);
    setInvokeResult(null);
    try {
      const result = await agentsApi.invokeAgent(activeAgent.agent_id, invokeMessage);
      setInvokeResult(result);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'LLM 호출 중 오류가 발생했습니다.';
      setInvokeError(msg);
    } finally {
      setInvoking(false);
    }
  };

  const toolMap = useMemo(() => {
    const map = new Map<string, ToolDescriptor>();
    tools.forEach((tool) => map.set(tool.id, tool));
    return map;
  }, [tools]);

  return (
    <div className="animate-fade-in font-apple">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8 pb-6 border-b border-white/10">
        <div>
          <h1 className="text-[40px] font-semibold text-white tracking-[-0.28px] leading-[1.07] mb-2">
            크리에이터 워크벤치
          </h1>
          <p className="text-[17px] text-white/60 tracking-[-0.374px] leading-[1.47]">
            에이전트의 메타데이터, 도구(MCP), 구독 규칙을 등록하고 실제 LLM 으로 테스트 합니다.
          </p>
        </div>
        <button
          onClick={openCreate}
          className="btn-primary inline-flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          새 에이전트 등록
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-20">
          <div className="w-8 h-8 border-2 border-white/20 border-t-apple-blue rounded-full animate-spin" />
        </div>
      ) : agents.length === 0 ? (
        <div className="bg-apple-surface1 rounded-[16px] p-12 text-center border border-white/5">
          <div className="w-14 h-14 mx-auto mb-4 rounded-[12px] bg-apple-surface2 flex items-center justify-center">
            <svg className="w-7 h-7 text-apple-blue" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
            </svg>
          </div>
          <h2 className="text-[21px] font-semibold text-white tracking-[0.231px] mb-2">
            등록된 에이전트가 없습니다
          </h2>
          <p className="text-[14px] text-white/50 tracking-[-0.224px]">
            오른쪽 상단의 '새 에이전트 등록' 버튼으로 첫 번째 에이전트를 만들어 보세요.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {agents.map((agent) => (
            <button
              key={agent.agent_id}
              onClick={() => openEdit(agent)}
              className="text-left bg-apple-surface1 rounded-[16px] p-6 border border-white/5 shadow-[0_5px_30px_rgba(0,0,0,0.22)] transition-transform duration-200 hover:scale-[1.02]"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-11 h-11 rounded-[12px] bg-apple-surface2 flex items-center justify-center">
                    <span className="text-[17px] font-semibold text-white">
                      {agent.name.charAt(0)}
                    </span>
                  </div>
                  <div>
                    <h3 className="text-[17px] font-semibold text-white leading-tight tracking-[-0.224px]">
                      {agent.name}
                    </h3>
                    <p className="text-[12px] text-white/50 mt-0.5">v{agent.version}</p>
                  </div>
                </div>
                <span
                  className={`px-2 py-0.5 rounded-[6px] text-[11px] font-medium ${STATUS_BADGE[agent.status]}`}
                >
                  {agent.status}
                </span>
              </div>
              <p className="text-[14px] text-white/70 tracking-[-0.12px] leading-relaxed line-clamp-3 mb-4">
                {agent.purpose || agent.description || '설명이 없습니다.'}
              </p>
              <div className="flex items-center justify-between text-[12px] text-white/50">
                <span>도구 {agent.tools.length}개</span>
                <span>
                  구독 {agent.subscription_rule?.is_active ? '활성' : '비활성'}
                </span>
                <span>{agent.visibility}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {editorMode !== 'closed' && (
        <AgentEditor
          mode={editorMode}
          activeAgent={activeAgent}
          form={form}
          saving={saving}
          formError={formError}
          tools={tools}
          toolMap={toolMap}
          invokeMessage={invokeMessage}
          invoking={invoking}
          invokeResult={invokeResult}
          invokeError={invokeError}
          onFormField={handleFormField}
          onToolToggle={handleToolToggle}
          onClose={closeEditor}
          onSave={handleSave}
          onInvokeMessageChange={setInvokeMessage}
          onInvoke={handleInvoke}
        />
      )}
    </div>
  );
}

interface AgentEditorProps {
  mode: 'create' | 'edit';
  activeAgent: Agent | null;
  form: FormState;
  saving: boolean;
  formError: string | null;
  tools: ToolDescriptor[];
  toolMap: Map<string, ToolDescriptor>;
  invokeMessage: string;
  invoking: boolean;
  invokeResult: InvokeResult | null;
  invokeError: string | null;
  onFormField: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
  onToolToggle: (toolId: string) => void;
  onClose: () => void;
  onSave: () => void;
  onInvokeMessageChange: (value: string) => void;
  onInvoke: () => void;
}

function AgentEditor(props: AgentEditorProps) {
  const {
    mode,
    activeAgent,
    form,
    saving,
    formError,
    tools,
    toolMap,
    invokeMessage,
    invoking,
    invokeResult,
    invokeError,
    onFormField,
    onToolToggle,
    onClose,
    onSave,
    onInvokeMessageChange,
    onInvoke,
  } = props;

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl bg-[#1c1c1e] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 bg-[#1c1c1e]/95 backdrop-blur-[20px] border-b border-white/10 px-8 py-5 flex items-center justify-between z-10">
          <div>
            <p className="text-[12px] uppercase tracking-[0.08em] text-apple-blue font-semibold">
              {mode === 'create' ? '새 에이전트 등록' : '에이전트 편집'}
            </p>
            <h2 className="text-[24px] font-semibold text-white tracking-[-0.374px] leading-tight mt-0.5">
              {form.name || '이름 없음'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="btn-secondary">
              닫기
            </button>
            <button onClick={onSave} className="btn-primary" disabled={saving}>
              {saving ? '저장 중...' : mode === 'create' ? '등록' : '변경 저장'}
            </button>
          </div>
        </div>

        <div className="px-8 py-6 space-y-8">
          {formError && (
            <div className="bg-[#ff3b30]/15 text-[#ff3b30] border border-[#ff3b30]/30 rounded-[10px] px-4 py-3 text-[14px]">
              {formError}
            </div>
          )}

          <Section title="1. 기본 정보">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="이름" required>
                <input
                  className="input-field"
                  value={form.name}
                  onChange={(e) => onFormField('name', e.target.value)}
                  placeholder="예: 인사 도우미 v2"
                />
              </Field>
              <Field label="버전" required>
                <input
                  className="input-field"
                  value={form.version}
                  onChange={(e) => onFormField('version', e.target.value)}
                />
              </Field>
              <Field label="상태">
                <select
                  className="input-field"
                  value={form.status}
                  onChange={(e) => onFormField('status', e.target.value as AgentStatus)}
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="공개 범위">
                <select
                  className="input-field"
                  value={form.visibility}
                  onChange={(e) =>
                    onFormField('visibility', e.target.value as AgentVisibility)
                  }
                >
                  {VISIBILITY_OPTIONS.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="카테고리 (메타데이터)">
                <input
                  className="input-field"
                  value={form.category}
                  onChange={(e) => onFormField('category', e.target.value)}
                  placeholder="예: HR, IT, Finance"
                />
              </Field>
              <Field label="역할 (쉼표로 구분)">
                <input
                  className="input-field"
                  value={form.rolesInput}
                  onChange={(e) => onFormField('rolesInput', e.target.value)}
                  placeholder="예: hr_manager, analyst"
                />
              </Field>
              <Field label="협업 에이전트 (쉼표로 구분)">
                <input
                  className="input-field"
                  value={form.collaboratorsInput}
                  onChange={(e) => onFormField('collaboratorsInput', e.target.value)}
                  placeholder="예: sales_bot, finance_bot"
                />
              </Field>
            </div>
          </Section>

          <Section title="2. 에이전트 자질 (프롬프트 & 설명)">
            <Field label="목적 (purpose)">
              <textarea
                className="input-field min-h-[60px]"
                value={form.purpose}
                onChange={(e) => onFormField('purpose', e.target.value)}
                placeholder="이 에이전트가 존재하는 이유"
              />
            </Field>
            <Field label="실행 방식 (approach)">
              <textarea
                className="input-field min-h-[60px]"
                value={form.approach}
                onChange={(e) => onFormField('approach', e.target.value)}
                placeholder="예: Tool-augmented ReAct, RAG + Agent, Orchestration"
              />
            </Field>
            <Field label="상세 설명 (description)">
              <textarea
                className="input-field min-h-[80px]"
                value={form.description}
                onChange={(e) => onFormField('description', e.target.value)}
                placeholder="사용자에게 노출될 상세 설명"
              />
            </Field>
            <Field label="System Prompt (agent_card.system_prompt)">
              <textarea
                className="input-field min-h-[120px] font-mono text-[14px]"
                value={form.systemPrompt}
                onChange={(e) => onFormField('systemPrompt', e.target.value)}
                placeholder="에이전트가 LLM 에 전달할 시스템 프롬프트. 비워두면 기본 템플릿이 사용됩니다."
              />
            </Field>
          </Section>

          <Section title="3. 도구 (MCP) 선택">
            {tools.length === 0 ? (
              <p className="text-[14px] text-white/50">사용 가능한 도구가 없습니다.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {tools.map((tool) => {
                  const checked = form.selectedTools.includes(tool.id);
                  return (
                    <button
                      key={tool.id}
                      type="button"
                      onClick={() => onToolToggle(tool.id)}
                      className={`text-left rounded-[12px] border px-4 py-3 transition-all ${
                        checked
                          ? 'bg-apple-blue/15 border-apple-blue/60'
                          : 'bg-apple-surface2 border-white/10 hover:border-white/20'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[14px] font-semibold text-white tracking-[-0.224px]">
                          {tool.name}
                        </span>
                        <span
                          className={`w-4 h-4 rounded-[4px] border flex items-center justify-center ${
                            checked ? 'bg-apple-blue border-apple-blue' : 'border-white/30'
                          }`}
                        >
                          {checked && (
                            <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </span>
                      </div>
                      <p className="text-[12px] text-white/60 tracking-[-0.12px] leading-snug">
                        {tool.description}
                      </p>
                      <p className="text-[11px] text-white/30 mt-1 font-mono">{tool.id}</p>
                      {tool.mcp_definition && (
                        <p className="text-[11px] text-apple-blue/80 mt-1 font-mono">
                          MCP inputSchema · {Object.keys(tool.mcp_definition.inputSchema || {}).length} keys
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            {form.selectedTools.length > 0 && (
              <div className="mt-3 text-[12px] text-white/50">
                선택됨: {form.selectedTools.map((id) => toolMap.get(id)?.name || id).join(', ')}
              </div>
            )}
          </Section>

          <Section title="4. 구독 규칙 (AGENT_SUBSCRIPTION_RULES)">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="watch_domains (쉼표로 구분)">
                <input
                  className="input-field"
                  value={form.watchDomains}
                  onChange={(e) => onFormField('watchDomains', e.target.value)}
                  placeholder="예: finance, hr"
                />
              </Field>
              <Field label="watch_intents (쉼표로 구분)">
                <input
                  className="input-field"
                  value={form.watchIntents}
                  onChange={(e) => onFormField('watchIntents', e.target.value)}
                  placeholder="예: data_request, alert"
                />
              </Field>
              <Field label="watch_tags (쉼표로 구분)">
                <input
                  className="input-field"
                  value={form.watchTags}
                  onChange={(e) => onFormField('watchTags', e.target.value)}
                  placeholder="예: KPI, quarterly"
                />
              </Field>
              <Field label="min_priority">
                <select
                  className="input-field"
                  value={form.minPriority}
                  onChange={(e) => onFormField('minPriority', e.target.value as RulePriority)}
                >
                  {PRIORITY_OPTIONS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="활성 여부">
                <label className="inline-flex items-center gap-2 h-[42px]">
                  <input
                    type="checkbox"
                    className="w-4 h-4 accent-apple-blue"
                    checked={form.ruleActive}
                    onChange={(e) => onFormField('ruleActive', e.target.checked)}
                  />
                  <span className="text-[14px] text-white/80">구독 규칙 활성</span>
                </label>
              </Field>
            </div>
          </Section>

          {mode === 'edit' && activeAgent && (
            <Section title="5. 실행 테스트 (LLM API 호출)">
              <p className="text-[13px] text-white/50 mb-3 leading-relaxed">
                등록된 system prompt 와 선택한 도구(MCP) 로 RunYour AI 의 OpenAI 호환 엔드포인트를
                호출합니다. 구독 규칙 변경사항은 저장 후 반영됩니다.
              </p>
              <Field label="사용자 메시지">
                <textarea
                  className="input-field min-h-[80px]"
                  value={invokeMessage}
                  onChange={(e) => onInvokeMessageChange(e.target.value)}
                  placeholder="예: E001 사번의 연차 잔여일을 알려줘."
                />
              </Field>
              <div className="flex gap-2">
                <button
                  onClick={onInvoke}
                  className="btn-primary"
                  disabled={invoking}
                >
                  {invoking ? '실행 중...' : '에이전트 실행'}
                </button>
                {invokeResult && (
                  <span className="text-[12px] text-white/50 self-center">
                    모델: {invokeResult.model_used} · 그래프: {invokeResult.graph.entrypoint}
                  </span>
                )}
              </div>
              {invokeError && (
                <div className="mt-3 bg-[#ff3b30]/15 text-[#ff3b30] border border-[#ff3b30]/30 rounded-[10px] px-4 py-3 text-[14px]">
                  {invokeError}
                </div>
              )}
              {invokeResult && (
                <div className="mt-4 space-y-3">
                  {invokeResult.error && (
                    <div className="bg-[#ff9f0a]/15 text-[#ff9f0a] border border-[#ff9f0a]/30 rounded-[10px] px-4 py-3 text-[13px]">
                      런타임 오류: {invokeResult.error}
                    </div>
                  )}
                  <div className="bg-apple-surface2 rounded-[12px] px-4 py-3 border border-white/10">
                    <p className="text-[11px] uppercase text-white/50 tracking-[0.08em] mb-2">
                      에이전트 응답
                    </p>
                    <pre className="whitespace-pre-wrap text-[14px] text-white leading-relaxed">
                      {invokeResult.output || '(빈 응답)'}
                    </pre>
                  </div>
                  {invokeResult.tool_calls.length > 0 && (
                    <div className="bg-apple-surface2 rounded-[12px] px-4 py-3 border border-white/10">
                      <p className="text-[11px] uppercase text-white/50 tracking-[0.08em] mb-2">
                        호출된 도구 ({invokeResult.tool_calls.length})
                      </p>
                      <ul className="space-y-2 text-[13px] text-white/80">
                        {invokeResult.tool_calls.map((call, idx) => (
                          <li key={idx} className="font-mono">
                            <span className="text-apple-link">{call.name}</span>(
                            {JSON.stringify(call.args)})
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {invokeResult.transitions.length > 0 && (
                    <div className="bg-apple-surface2 rounded-[12px] px-4 py-3 border border-white/10">
                      <p className="text-[11px] uppercase text-white/50 tracking-[0.08em] mb-3">
                        LangGraph 전이 ({invokeResult.transitions.length})
                      </p>
                      <div className="space-y-2">
                        {invokeResult.transitions.map((transition, idx) => (
                          <div
                            key={`${transition.from}-${transition.to}-${idx}`}
                            className="flex items-center gap-2 text-[12px] text-white/70 font-mono"
                          >
                            <span className="px-2 py-1 rounded-[6px] bg-white/5 text-white">
                              {transition.from}
                            </span>
                            <span className="text-apple-blue">→</span>
                            <span className="px-2 py-1 rounded-[6px] bg-white/5 text-white">
                              {transition.to}
                            </span>
                            <span className="text-white/40">({transition.reason})</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {invokeResult.checkpoint.thread_id && (
                    <div className="bg-apple-surface2 rounded-[12px] px-4 py-3 border border-white/10">
                      <p className="text-[11px] uppercase text-white/50 tracking-[0.08em] mb-2">
                        Checkpointer
                      </p>
                      <div className="space-y-1 text-[12px] text-white/70 font-mono">
                        <p>thread_id: {invokeResult.checkpoint.thread_id}</p>
                        <p>checkpoint_id: {invokeResult.checkpoint.checkpoint_id || '-'}</p>
                        <p>
                          next_nodes:{' '}
                          {(invokeResult.checkpoint.next_nodes || []).join(', ') || '(완료)'}
                        </p>
                        <p>resumable: {invokeResult.checkpoint.resumable ? 'true' : 'false'}</p>
                      </div>
                    </div>
                  )}
                  {invokeResult.steps.length > 0 && (
                    <details className="bg-apple-surface2 rounded-[12px] px-4 py-3 border border-white/10">
                      <summary className="text-[12px] text-white/60 cursor-pointer">
                        전체 메시지 스텝 ({invokeResult.steps.length})
                      </summary>
                      <pre className="whitespace-pre-wrap text-[11px] text-white/70 mt-3 leading-relaxed font-mono">
                        {JSON.stringify(invokeResult.steps, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-[17px] font-semibold text-white tracking-[-0.374px] mb-4">
        {title}
      </h3>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[12px] text-white/60 tracking-[-0.12px] uppercase mb-1.5">
        {label}
        {required && <span className="text-apple-blue ml-1">*</span>}
      </span>
      {children}
    </label>
  );
}
