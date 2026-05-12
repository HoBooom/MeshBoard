import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Background,
  Controls,
  Edge,
  EdgeMouseHandler,
  MiniMap,
  Node,
  NodeMouseHandler,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { agentsApi, AgentCreatePayload } from '../api/agents';
import { AgentCard, getAgents } from '../api/marketplace';
import {
  Goal,
  PublishMessageResult,
  Workspace,
  WorkspaceAccessRequest,
  WorkspaceDetail,
  WorkspaceJoinable,
  workspacesApi,
} from '../api/workspaces';
import { useAuthStore } from '../stores/authStore';

const CATEGORIES = ['All', 'HR', 'IT', 'Sales', 'Security', 'Finance'];

function csvToList(text: string): string[] {
  return text.split(',').map((item) => item.trim()).filter(Boolean);
}

function bodyPreview(bodyRef: string): string {
  if (!bodyRef.startsWith('inline:json:')) return bodyRef;
  try {
    const parsed = JSON.parse(bodyRef.replace('inline:json:', ''));
    return parsed.message || parsed.question || JSON.stringify(parsed);
  } catch {
    return bodyRef;
  }
}

function agentStatus(index: number): 'active' | 'processing' | 'idle' {
  if (index === 0) return 'active';
  if (index === 1) return 'processing';
  return 'idle';
}

function statusTone(status: 'active' | 'processing' | 'idle' | 'error'): string {
  if (status === 'active') return 'bg-[#34c759]';
  if (status === 'processing') return 'bg-[#ffd60a]';
  if (status === 'error') return 'bg-[#ff453a]';
  return 'bg-white/30';
}

function statusLabel(status: 'active' | 'processing' | 'idle' | 'error'): string {
  if (status === 'active') return 'active';
  if (status === 'processing') return 'processing';
  if (status === 'error') return 'error';
  return 'idle';
}

function topologyStatusTone(status: 'active' | 'processing' | 'idle' | 'error'): string {
  if (status === 'active') return '#34c759';
  if (status === 'processing') return '#ffd60a';
  if (status === 'error') return '#ff453a';
  return '#8e8e93';
}

function agentType(agentName: string): string {
  const normalized = agentName.toLowerCase();
  if (normalized.includes('inspect') || normalized.includes('검수')) return 'inspector';
  if (normalized.includes('plan') || normalized.includes('planner')) return 'planner';
  if (normalized.includes('coord') || normalized.includes('orchestrator')) return 'coordinator';
  if (normalized.includes('monitor') || normalized.includes('감시')) return 'monitor';
  if (normalized.includes('exec') || normalized.includes('실행')) return 'executor';
  return 'custom';
}

export default function WorkspacePage() {
  const { user } = useAuthStore();
  const navigate = useNavigate();
  const [view, setView] = useState<'list' | 'create' | 'detail'>('list');
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [detail, setDetail] = useState<WorkspaceDetail | null>(null);
  const [joinableWorkspaces, setJoinableWorkspaces] = useState<WorkspaceJoinable[]>([]);
  const [accessRequests, setAccessRequests] = useState<WorkspaceAccessRequest[]>([]);
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [joiningId, setJoiningId] = useState<string | null>(null);
  const [joinLoading, setJoinLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joinOpen, setJoinOpen] = useState(false);
  const [joinCode, setJoinCode] = useState('1234');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('All');
  const [wizardStep, setWizardStep] = useState(1);
  const [workspaceName, setWorkspaceName] = useState('');
  const [workspaceDescription, setWorkspaceDescription] = useState('');
  const [workspaceTags, setWorkspaceTags] = useState('');
  const [basket, setBasket] = useState<Record<string, { agent: AgentCard; quantity: number }>>({});
  const [subscriptionTargets, setSubscriptionTargets] = useState<Record<string, string[]>>({});
  const [subscriptionFilter, setSubscriptionFilter] = useState<'all' | 'user' | 'agent'>('all');
  const [draftAgentName, setDraftAgentName] = useState('');
  const [draftAgentPurpose, setDraftAgentPurpose] = useState('');
  const [messageText, setMessageText] = useState('E001 사번의 연차 잔여일을 확인해줘');
  const [publishResult, setPublishResult] = useState<PublishMessageResult | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [expandedMessageId, setExpandedMessageId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorMode, setInspectorMode] = useState<'agent' | 'message' | 'logs'>('agent');
  const [workspaceMode, setWorkspaceMode] = useState<'messaging' | 'map'>('messaging');
  const [selectedGoalId, setSelectedGoalId] = useState<string | null>(null);
  const [showGoalForm, setShowGoalForm] = useState(false);
  const [goalName, setGoalName] = useState('');
  const [goalDescription, setGoalDescription] = useState('');
  const [goalPriority, setGoalPriority] = useState<Goal['priority']>('medium');
  const [goalSuccessCriteria, setGoalSuccessCriteria] = useState('');
  const [goalParentId, setGoalParentId] = useState<string | null>(null);
  const [goalAssignedAgents, setGoalAssignedAgents] = useState<string[]>([]);
  const [mapFilter, setMapFilter] = useState<'all' | 'active' | 'processing' | 'idle' | 'error'>('all');
  const [selectedMapNodeId, setSelectedMapNodeId] = useState<string | null>(null);
  const [selectedMapEdgeId, setSelectedMapEdgeId] = useState<string | null>(null);
  const [mapNodes, setMapNodes, onMapNodesChange] = useNodesState<Node>([]);
  const [mapEdges, setMapEdges, onMapEdgesChange] = useEdgesState<Edge>([]);
  const messageFeedEndRef = useRef<HTMLDivElement | null>(null);

  const roles = new Set(user?.roles || []);
  const canCreateWorkspace =
    roles.has('agent_owner') ||
    roles.has('agent_engineer') ||
    roles.has('trust_ops') ||
    roles.has('release_manager');
  const canGrantAccess =
    roles.has('trust_ops') || roles.has('release_manager') || roles.has('evaluator');

  const basketItems = Object.values(basket);
  const selectedGoal = detail?.goals.find((goal) => goal.goal_id === selectedGoalId) || null;
  const topLevelGoals = detail?.goals.filter((goal) => !goal.parent_goal_id) || [];
  const workspaceMembers = detail?.nodes.filter((node) => node.node_type === 'user') || [];
  const activeMessages = useMemo(
    () =>
      selectedGoal?.conversation_id
        ? detail?.messages.filter((message) => message.conversation_id === selectedGoal.conversation_id) || []
        : detail?.messages || [],
    [detail?.messages, selectedGoal?.conversation_id]
  );
  const selectedMapNode = mapNodes.find((node) => node.id === selectedMapNodeId);
  const selectedMapEdge = mapEdges.find((edge) => edge.id === selectedMapEdgeId);

  const loadList = async () => {
    setLoading(true);
    setError(null);
    try {
      const requestPromise = canGrantAccess
        ? workspacesApi.listAccessRequests()
        : Promise.resolve([]);
      const [workspaceList, requestList] = await Promise.all([
        workspacesApi.list(),
        requestPromise,
      ]);
      setWorkspaces(workspaceList);
      setAccessRequests(requestList);
    } catch (err) {
      console.error(err);
      setError('워크스페이스 목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const loadAgents = async () => {
    const marketplaceAgents = await getAgents(searchQuery, activeCategory);
    setAgents(marketplaceAgents);
  };

  const openJoinWorkspace = async () => {
    setJoinOpen(true);
    setJoinLoading(true);
    setJoinError(null);
    try {
      const data = await workspacesApi.listJoinable();
      setJoinableWorkspaces(data);
    } catch (err) {
      console.error(err);
      setJoinError('참여 가능한 워크스페이스 목록을 불러오지 못했습니다.');
    } finally {
      setJoinLoading(false);
    }
  };

  useEffect(() => {
    void loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canGrantAccess]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadAgents();
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, activeCategory]);

  useEffect(() => {
    if (view !== 'detail') return;
    messageFeedEndRef.current?.scrollIntoView({ block: 'end' });
  }, [view, detail?.messages.length]);

  const openDetail = async (workspaceId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await workspacesApi.get(workspaceId);
      setDetail(data);
      setView('detail');
    } catch (err) {
      console.error(err);
      setError('워크스페이스 상세를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const addAgent = (agent: AgentCard) => {
    setBasket((prev) => ({
      ...prev,
      [agent.agent_id]: {
        agent,
        quantity: (prev[agent.agent_id]?.quantity || 0) + 1,
      },
    }));
  };

  const setQuantity = (agentId: string, quantity: number) => {
    setBasket((prev) => {
      const current = prev[agentId];
      if (!current) return prev;
      if (quantity <= 0) {
        const next = { ...prev };
        delete next[agentId];
        setSubscriptionTargets((targets) => {
          const cleaned = { ...targets };
          delete cleaned[agentId];
          Object.keys(cleaned).forEach((sourceAgentId) => {
            cleaned[sourceAgentId] = cleaned[sourceAgentId].filter((targetKey) => targetKey !== `agent:${agentId}`);
          });
          return cleaned;
        });
        return next;
      }
      return { ...prev, [agentId]: { ...current, quantity } };
    });
  };

  const toggleSubscriptionTarget = (sourceAgentId: string, targetKey: string) => {
    setSubscriptionTargets((prev) => {
      const current = prev[sourceAgentId] || [];
      const nextTargets = current.includes(targetKey)
        ? current.filter((item) => item !== targetKey)
        : [...current, targetKey];
      return { ...prev, [sourceAgentId]: nextTargets };
    });
  };

  const createDraftAgent = async () => {
    if (!draftAgentName.trim()) return;
    const payload: AgentCreatePayload = {
      name: draftAgentName.trim(),
      version: '0.1.0',
      purpose: draftAgentPurpose.trim() || '워크스페이스 생성 흐름에서 작성된 초안 에이전트',
      status: 'DRAFT',
      visibility: 'PRIVATE',
      tools: [],
      metadata: { category: 'Draft' },
    };
    const created = await agentsApi.createAgent(payload);
    const card: AgentCard = {
      agent_id: created.agent_id,
      name: created.name,
      version: created.version,
      purpose: created.purpose || undefined,
      description: created.description || undefined,
      status: created.status,
      visibility: created.visibility,
      metadata_: created.metadata_,
      roles: created.roles,
      tools: created.tools,
      created_at: created.created_at,
    };
    addAgent(card);
    setDraftAgentName('');
    setDraftAgentPurpose('');
  };

  const validateAgentSubscriptions = () => {
    const agentsMissingSubscriptions = basketItems.filter(
      (item) => (subscriptionTargets[item.agent.agent_id] || []).length === 0
    );
    if (agentsMissingSubscriptions.length === 0) return true;
    setError(`구독 대상을 선택하지 않은 에이전트가 있습니다: ${agentsMissingSubscriptions.map((item) => item.agent.name).join(', ')}`);
    setWizardStep(2);
    return false;
  };

  const createWorkspace = async () => {
    if (!workspaceName.trim()) {
      setError('워크스페이스 이름을 입력하세요.');
      return;
    }
    if (!validateAgentSubscriptions()) return;
    setSaving(true);
    setError(null);
    try {
      const workspace = await workspacesApi.create({
        name: workspaceName.trim(),
        description: workspaceDescription.trim() || undefined,
        tags: csvToList(workspaceTags),
        agent_placements: basketItems.map((item) => ({
          agent_id: item.agent.agent_id,
          quantity: item.quantity,
        })),
        agent_subscriptions: basketItems.flatMap((item) =>
          (subscriptionTargets[item.agent.agent_id] || []).map((targetKey) => {
            const [targetType, targetRefId] = targetKey.split(':');
            return {
              source_agent_id: item.agent.agent_id,
              target_node_type: targetType as 'user' | 'agent',
              target_ref_id: targetRefId,
            };
          })
        ),
      });
      await loadList();
      await openDetail(workspace.workspace_id);
    } catch (err) {
      console.error(err);
      setError('워크스페이스 생성 중 오류가 발생했습니다.');
    } finally {
      setSaving(false);
    }
  };

  const decideRequest = async (requestId: string, decision: 'approve' | 'reject') => {
    if (decision === 'approve') {
      await workspacesApi.approveAccessRequest(requestId);
    } else {
      await workspacesApi.rejectAccessRequest(requestId);
    }
    await loadList();
  };

  const joinWorkspace = async (workspace: WorkspaceJoinable) => {
    setJoiningId(workspace.workspace_id);
    setJoinError(null);
    try {
      const joined = await workspacesApi.join(workspace.workspace_id, joinCode);
      await loadList();
      setJoinOpen(false);
      setJoinableWorkspaces([]);
      await openDetail(joined.workspace_id);
    } catch (err) {
      console.error(err);
      setJoinError('참여 코드가 올바르지 않거나 참여할 수 없는 워크스페이스입니다.');
    } finally {
      setJoiningId(null);
    }
  };

  const markRoutedAgentsProcessing = () => {
    if (!detail || !user?.user_id) return;
    const senderNode = detail.nodes.find(
      (node) => node.node_type === 'user' && node.ref_id === user.user_id
    );
    if (!senderNode) return;
    const routedAgentNodeIds = new Set(
      detail.edges
        .filter((edge) => edge.edge_type === 'subscription' && edge.status === 'active' && edge.target_node_id === senderNode.node_id)
        .map((edge) => edge.source_node_id)
    );
    if (routedAgentNodeIds.size === 0) return;
    setDetail({
      ...detail,
      nodes: detail.nodes.map((node) =>
        node.node_type === 'agent' && routedAgentNodeIds.has(node.node_id)
          ? { ...node, status: 'processing' }
          : node
      ),
    });
  };

  const publishMessage = async () => {
    if (!detail) return;
    const nextMessage = messageText.trim();
    if (!nextMessage) return;
    setError(null);
    markRoutedAgentsProcessing();
    try {
      const result = await workspacesApi.publish(detail.workspace_id, {
        domain: 'workspace',
        intent: selectedGoal ? 'goal_message' : 'operator_message',
        payload: { message: nextMessage },
        tags: selectedGoal ? ['workspace', 'goal'] : ['workspace'],
        priority: 'medium',
        conversation_id: selectedGoal?.conversation_id,
      });
      setMessageText('');
      setPublishResult(result);
      if (result.routing.matched_agent_ids.length === 0) {
        setError('응답 가능한 에이전트가 없습니다.');
      }
      const nextDetail = await workspacesApi.get(detail.workspace_id);
      if (selectedGoal?.conversation_id) {
        nextDetail.messages = await workspacesApi.listMessages(detail.workspace_id, selectedGoal.conversation_id);
      }
      setDetail(nextDetail);
    } catch (err) {
      console.error(err);
      setError('메시지 전송 중 오류가 발생했습니다.');
    }
  };

  const selectGoal = async (goal: Goal | null) => {
    if (!detail) return;
    setSelectedGoalId(goal?.goal_id || null);
    if (!goal?.conversation_id) {
      const nextDetail = await workspacesApi.get(detail.workspace_id);
      setDetail(nextDetail);
      return;
    }
    const messages = await workspacesApi.listMessages(detail.workspace_id, goal.conversation_id);
    setDetail({ ...detail, messages });
    setWorkspaceMode('messaging');
    setInspectorMode('logs');
    setInspectorOpen(true);
  };

  const resetGoalForm = () => {
    setGoalName('');
    setGoalDescription('');
    setGoalPriority('medium');
    setGoalSuccessCriteria('');
    setGoalParentId(null);
    setGoalAssignedAgents([]);
  };

  const createGoal = async () => {
    if (!detail || !goalName.trim()) return;
    await workspacesApi.createGoal(detail.workspace_id, {
      name: goalName.trim(),
      description: goalDescription.trim() || undefined,
      priority: goalPriority,
      state: 'pending',
      parent_goal_id: goalParentId,
      assigned_agent_ids: goalAssignedAgents,
      success_criteria: goalSuccessCriteria.trim() || undefined,
    });
    const nextDetail = await workspacesApi.get(detail.workspace_id);
    setDetail(nextDetail);
    resetGoalForm();
    setShowGoalForm(false);
  };

  const updateGoalState = async (goal: Goal, nextState: Goal['state']) => {
    if (!detail) return;
    const updated = await workspacesApi.updateGoal(detail.workspace_id, goal.goal_id, { state: nextState });
    setDetail({
      ...detail,
      goals: detail.goals.map((item) => (item.goal_id === updated.goal_id ? updated : item)),
    });
  };

  const deleteWorkspace = async () => {
    if (!detail || !window.confirm('이 워크스페이스를 삭제하시겠습니까?')) return;
    await workspacesApi.delete(detail.workspace_id);
    await loadList();
    setDetail(null);
    setView('list');
  };

  useEffect(() => {
    if (!detail) return;

    const agentStatusById = new Map(
      detail.nodes
        .filter((node) => node.node_type === 'agent')
        .map((node) => [node.ref_id, node.status])
    );
    const expandedAgents = detail.placements.flatMap((placement) =>
      Array.from({ length: placement.quantity }, (_, index) => {
        const instanceNumber = index + 1;
        const messageCount = activeMessages.filter(
          (message) => message.sender_id === placement.agent.agent_id
        ).length;
        const fallbackStatus =
          messageCount > 3 ? 'active' : index === 0 && messageCount > 0 ? 'processing' : 'idle';
        const status = agentStatusById.get(placement.agent.agent_id) || fallbackStatus;
        return {
          id: `${placement.agent.agent_id}-${instanceNumber}`,
          agentId: placement.agent.agent_id,
          name: placement.quantity > 1 ? `${placement.agent.name} #${instanceNumber}` : placement.agent.name,
          role: placement.agent.roles[0] || agentType(placement.agent.name),
          type: agentType(placement.agent.name),
          status: status as 'active' | 'processing' | 'idle' | 'error',
          messageCount,
          eventCount: messageCount + placement.agent.tools.length,
          version: placement.agent.version,
          tools: placement.agent.tools,
          nodeType: 'agent' as const,
        };
      })
    );
    const expandedUsers = detail.nodes
      .filter((node) => node.node_type === 'user')
      .map((node) => {
        const messageCount = activeMessages.filter((message) => message.sender_id === node.ref_id).length;
        return {
          id: `user-${node.node_id}`,
          refId: node.ref_id,
          name: node.display_name,
          role: 'workspace member',
          type: 'user',
          status: node.status,
          messageCount,
          eventCount: messageCount,
          version: '',
          tools: [] as string[],
          nodeType: 'user' as const,
        };
      });

    const graphItems = [...expandedUsers, ...expandedAgents];
    const filteredGraphItems = graphItems.filter((item) =>
      mapFilter === 'all' ? true : item.status === mapFilter
    );
    const columns = Math.max(3, Math.ceil(Math.sqrt(Math.max(filteredGraphItems.length, 1))));
    const nodes: Node[] = filteredGraphItems.map((item, index) => {
      const x = (index % columns) * 260;
      const y = Math.floor(index / columns) * 170;
      const statusColor = topologyStatusTone(item.status);
      const highlighted =
        (item.nodeType === 'agent' && selectedAgentId === item.agentId) ||
        selectedMapNodeId === item.id;

      return {
        id: item.id,
        position: { x, y },
        data: {
          agentId: item.nodeType === 'agent' ? item.agentId : undefined,
          refId: item.nodeType === 'user' ? item.refId : item.agentId,
          nodeType: item.nodeType,
          displayName: item.name,
          status: item.status,
          role: item.role,
          messageCount: item.messageCount,
          eventCount: item.eventCount,
          tools: item.tools,
          label: (
            <div className={`min-w-[210px] rounded-[18px] border bg-white px-4 py-3 shadow-sm ${highlighted ? 'border-apple-blue shadow-[0_0_0_4px_rgba(0,113,227,0.14)]' : 'border-black/10'}`}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${item.nodeType === 'user' ? 'bg-[#0071e3] text-white' : 'bg-black/[0.06] text-black/60'}`}>
                    {item.nodeType === 'user' ? item.name.charAt(0) : 'A'}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-[#1d1d1f]">{item.name}</p>
                    <p className="text-[11px] uppercase tracking-[0.08em] text-black/38">{item.type}</p>
                  </div>
                </div>
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: statusColor }} />
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px] text-black/55">
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">msg {item.messageCount}</span>
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">event {item.eventCount}</span>
              </div>
              <p className="mt-2 text-[11px] text-black/40">
                {item.status}{item.nodeType === 'agent' ? ` · v${item.version}` : ' · member'}
              </p>
            </div>
          ),
        },
        style: {
          border: 'none',
          background: 'transparent',
          padding: 0,
          width: 220,
        },
      };
    });

    const nodeIds = new Set(nodes.map((node) => node.id));
    const messageEdges: Edge[] = [];
    const graphNodeByRefId = new Map<string, string>();
    expandedAgents.forEach((agent) => {
      if (!graphNodeByRefId.has(agent.agentId)) {
        graphNodeByRefId.set(agent.agentId, agent.id);
      }
    });
    expandedUsers.forEach((member) => {
      graphNodeByRefId.set(member.refId, member.id);
    });

    activeMessages.forEach((message, index, messages) => {
      const nextMessage = messages[index + 1];
      if (!nextMessage) return;
      const source = graphNodeByRefId.get(message.sender_id);
      const target = graphNodeByRefId.get(nextMessage.sender_id);
      if (!source || !target || source === target || !nodeIds.has(source) || !nodeIds.has(target)) return;
      const edgeId = `message-${source}-${target}`;
      if (messageEdges.some((edge) => edge.id === edgeId)) return;
      messageEdges.push({
        id: edgeId,
        source,
        target,
        animated: true,
        label: 'message',
        data: { relation_type: 'message', last_interaction_at: nextMessage.sent_at },
        style: { stroke: '#0071e3', strokeWidth: 2 },
        labelStyle: { fill: '#3a3a3c', fontSize: 11 },
      });
    });

    const fallbackEdges: Edge[] = [];
    if (messageEdges.length === 0 && nodes.length > 1) {
      nodes.slice(1).forEach((node, index) => {
        fallbackEdges.push({
          id: `supervision-${nodes[0].id}-${node.id}`,
          source: nodes[0].id,
          target: node.id,
          label: index % 2 === 0 ? 'supervision' : 'data_flow',
          data: { relation_type: index % 2 === 0 ? 'supervision' : 'data_flow' },
          style: { stroke: '#8e8e93', strokeDasharray: '5 5' },
          labelStyle: { fill: '#6e6e73', fontSize: 11 },
        });
      });
    }

    setMapNodes(nodes);
    setMapEdges(messageEdges.length > 0 ? messageEdges : fallbackEdges);
  }, [activeMessages, detail, mapFilter, selectedAgentId, selectedMapNodeId, setMapEdges, setMapNodes]);

  const onTopologyNodeClick: NodeMouseHandler = (_, node) => {
    setSelectedMapNodeId(node.id);
    setSelectedMapEdgeId(null);
    setSelectedAgentId(node.data.nodeType === 'agent' ? String(node.data.agentId || '').split('-')[0] : null);
    setInspectorMode('agent');
    setInspectorOpen(true);
  };

  const onTopologyEdgeClick: EdgeMouseHandler = (_, edge) => {
    setSelectedMapEdgeId(edge.id);
    setSelectedMapNodeId(null);
    setInspectorMode('logs');
    setInspectorOpen(true);
  };

  if (view === 'create') {
    return (
      <div className="animate-fade-in font-apple">
        <Header
          title="새 워크스페이스 생성"
          subtitle="환경 정보, 에이전트 배치, 추후 환경 구성 슬롯을 순서대로 설정합니다."
          actionLabel="목록으로"
          onAction={() => setView('list')}
        />
        {error && <Alert message={error} />}
        <div className="bg-apple-surface1 rounded-[18px] border border-white/5 p-6">
          <div className="flex gap-2 mb-6">
            {[1, 2, 3].map((step) => (
              <div
                key={step}
                className={`flex-1 h-2 rounded-full ${wizardStep >= step ? 'bg-apple-blue' : 'bg-white/10'}`}
              />
            ))}
          </div>
          {wizardStep === 1 && (
            <section className="space-y-4">
              <Field label="워크스페이스 이름">
                <input className="input-field" value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} placeholder="예: 자동차 공장 전체" />
              </Field>
              <Field label="설명">
                <textarea className="input-field min-h-[110px]" value={workspaceDescription} onChange={(e) => setWorkspaceDescription(e.target.value)} placeholder="환경 범위, 데이터 소스, 에이전트가 감시할 상황을 설명하세요." />
              </Field>
              <Field label="태그 (쉼표 구분)">
                <input className="input-field" value={workspaceTags} onChange={(e) => setWorkspaceTags(e.target.value)} placeholder="factory, quality, logistics" />
              </Field>
              <button className="btn-primary" onClick={() => setWizardStep(2)}>다음: 에이전트 배치</button>
            </section>
          )}
          {wizardStep === 2 && (
            <section>
              <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-6">
                <div>
                  <div className="flex gap-2 mb-4">
                    <input className="input-field" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="마켓플레이스 에이전트 검색" />
                    <button className="btn-secondary" onClick={() => navigate('/dashboard/creator')}>새 에이전트 즉시 생성</button>
                  </div>
                  <div className="flex gap-2 mb-4 overflow-x-auto">
                    {CATEGORIES.map((category) => (
                      <button key={category} onClick={() => setActiveCategory(category)} className={`px-3 py-1.5 rounded-full text-[13px] ${activeCategory === category ? 'bg-apple-blue text-white' : 'bg-white/10 text-white/60'}`}>
                        {category}
                      </button>
                    ))}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {agents.map((agent) => (
                      <button key={agent.agent_id} onClick={() => addAgent(agent)} className="text-left bg-apple-surface2 rounded-[14px] p-4 border border-white/10 hover:border-apple-blue/60">
                        <p className="text-[15px] font-semibold text-white">{agent.name}</p>
                        <p className="text-[12px] text-white/50">v{agent.version} · {agent.metadata_?.category || 'General'}</p>
                        <p className="text-[13px] text-white/60 line-clamp-2 mt-2">{agent.description || agent.purpose || '설명이 없습니다.'}</p>
                      </button>
                    ))}
                  </div>
                </div>
                <aside className="bg-apple-surface2 rounded-[14px] p-4 border border-white/10 h-fit">
                  <h3 className="text-[17px] font-semibold text-white mb-3">배치 바구니</h3>
                  <div className="space-y-3">
                    {basketItems.length === 0 ? (
                      <p className="text-[13px] text-white/50">동일 에이전트를 여러 번 추가할 수 있습니다.</p>
                    ) : (
                      basketItems.map((item) => (
                        <div key={item.agent.agent_id} className="flex items-center justify-between gap-2">
                          <span className="text-[13px] text-white">{item.agent.name}</span>
                          <div className="flex items-center gap-2">
                            <button className="btn-secondary !px-2 !py-1" onClick={() => setQuantity(item.agent.agent_id, item.quantity - 1)}>-</button>
                            <span className="text-white/70 text-[13px] w-8 text-center">x{item.quantity}</span>
                            <button className="btn-secondary !px-2 !py-1" onClick={() => setQuantity(item.agent.agent_id, item.quantity + 1)}>+</button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                  {basketItems.length > 0 && (
                    <div className="border-t border-white/10 mt-4 pt-4">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <p className="text-[12px] text-white/50">구독 대상</p>
                        <div className="flex rounded-[10px] bg-white/10 p-1">
                          {(['all', 'user', 'agent'] as const).map((filter) => (
                            <button
                              key={filter}
                              className={`rounded-[8px] px-2 py-1 text-[11px] font-medium ${subscriptionFilter === filter ? 'bg-apple-blue text-white' : 'text-white/50'}`}
                              onClick={() => setSubscriptionFilter(filter)}
                            >
                              {filter}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="space-y-4">
                        {basketItems.map((item) => {
                          const selectedTargets = subscriptionTargets[item.agent.agent_id] || [];
                          const targetOptions = [
                            ...(user?.user_id
                              ? [{ key: `user:${user.user_id}`, label: user.name || '나', type: 'user' as const }]
                              : []),
                            ...basketItems
                              .filter((target) => target.agent.agent_id !== item.agent.agent_id)
                              .map((target) => ({
                                key: `agent:${target.agent.agent_id}`,
                                label: target.agent.name,
                                type: 'agent' as const,
                              })),
                          ].filter((target) => subscriptionFilter === 'all' || target.type === subscriptionFilter);
                          return (
                            <div key={`subscriptions-${item.agent.agent_id}`} className="rounded-[12px] bg-black/18 p-3">
                              <div className="mb-2 flex items-center justify-between gap-2">
                                <p className="truncate text-[12px] font-semibold text-white">{item.agent.name}</p>
                                <span className={`text-[11px] ${selectedTargets.length > 0 ? 'text-[#34c759]' : 'text-[#ff9f0a]'}`}>
                                  {selectedTargets.length} selected
                                </span>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                {targetOptions.length === 0 ? (
                                  <span className="text-[11px] text-white/35">선택 가능한 대상이 없습니다.</span>
                                ) : (
                                  targetOptions.map((target) => {
                                    const selected = selectedTargets.includes(target.key);
                                    return (
                                      <button
                                        key={target.key}
                                        className={`rounded-[9px] border px-2.5 py-1.5 text-[11px] transition ${selected ? 'border-apple-blue bg-apple-blue/20 text-white' : 'border-white/10 bg-white/[0.04] text-white/55 hover:border-apple-blue/50 hover:text-white'}`}
                                        onClick={() => toggleSubscriptionTarget(item.agent.agent_id, target.key)}
                                      >
                                        {target.type === 'user' ? '사용자' : '에이전트'} · {target.label}
                                      </button>
                                    );
                                  })
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <div className="border-t border-white/10 mt-4 pt-4">
                    <p className="text-[12px] text-white/50 mb-2">인라인 에이전트 초안</p>
                    <input className="input-field mb-2" value={draftAgentName} onChange={(e) => setDraftAgentName(e.target.value)} placeholder="초안 에이전트 이름" />
                    <textarea className="input-field min-h-[70px] mb-2" value={draftAgentPurpose} onChange={(e) => setDraftAgentPurpose(e.target.value)} placeholder="목적" />
                    <button className="btn-secondary w-full" onClick={createDraftAgent}>초안 생성 후 추가</button>
                  </div>
                </aside>
              </div>
              <div className="flex justify-between mt-6">
                <button className="btn-secondary" onClick={() => setWizardStep(1)}>이전</button>
                <button className="btn-primary" onClick={() => {
                  setError(null);
                  if (validateAgentSubscriptions()) setWizardStep(3);
                }}>다음: 환경 구성</button>
              </div>
            </section>
          )}
          {wizardStep === 3 && (
            <section className="space-y-4">
              <div className="rounded-[14px] border border-dashed border-white/20 p-8 text-center bg-apple-surface2">
                <p className="text-[17px] font-semibold text-white mb-1">환경 구성</p>
                <p className="text-[14px] text-white/50">Coming Soon · 에이전트가 동작할 환경 변수, 데이터 연결, 권한 정책은 후속 단계에서 구현합니다.</p>
              </div>
              <div className="flex justify-between">
                <button className="btn-secondary" onClick={() => setWizardStep(2)}>이전</button>
                <button className="btn-primary" onClick={createWorkspace} disabled={saving}>
                  {saving ? '생성 중...' : '워크스페이스 생성'}
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    );
  }

  if (view === 'detail' && detail) {
    const selectedAgent =
      detail.placements.find((placement) => placement.agent.agent_id === selectedAgentId) ||
      detail.placements[0] ||
      null;
    const expandedMessage = detail.messages.find((message) => message.message_id === expandedMessageId);
    const agentLabel = selectedAgent ? selectedAgent.agent.name : 'environment-messages';
    const detailAgentStatusById = new Map(
      detail.nodes
        .filter((node) => node.node_type === 'agent')
        .map((node) => [node.ref_id, node.status])
    );

    return (
      <div className="animate-fade-in font-apple">
        <div className="mb-4 flex items-center justify-between">
          <button className="btn-secondary" onClick={() => setView('list')}>← 워크스페이스 목록</button>
          <div className="hidden md:flex items-center gap-2 text-[12px] text-white/45">
            <span>{detail.tags.join(' · ') || 'untagged environment'}</span>
            <span>·</span>
            <span>{detail.active_agent_count} agent instances</span>
          </div>
        </div>

        <div className={`grid h-[calc(100vh-190px)] min-h-0 grid-cols-1 ${inspectorOpen ? 'xl:grid-cols-[280px_minmax(0,1fr)_340px]' : 'xl:grid-cols-[280px_minmax(0,1fr)]'} gap-0 overflow-hidden rounded-[22px] border border-white/10 bg-[#101114] shadow-[0_18px_70px_rgba(0,0,0,0.35)]`}>
          <aside className="flex min-h-0 flex-col border-b border-white/10 bg-[#17181c] xl:border-b-0 xl:border-r">
            <div className="border-b border-white/10 p-5">
              <p className="text-[11px] uppercase tracking-[0.16em] text-white/35">Workspace</p>
              <h1 className="mt-1 truncate text-[19px] font-semibold text-white">{detail.name || '워크스페이스'}</h1>
              <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-white/45">{detail.description || '다중 에이전트 그래프 환경'}</p>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              <SidebarGroup title="Active Agents">
                {detail.placements.map((placement, index) => {
                  const status = detailAgentStatusById.get(placement.agent.agent_id) || agentStatus(index);
                  const unreadCount = detail.messages.filter(
                    (message) => message.sender_id === placement.agent.agent_id
                  ).length;
                  const selected = selectedAgent?.agent.agent_id === placement.agent.agent_id;
                  return (
                    <button
                      key={placement.agent.agent_id}
                      className={`mb-1 flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left transition ${selected ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07] hover:text-white'}`}
                      onClick={() => {
                        setSelectedAgentId(placement.agent.agent_id);
                        setInspectorMode('agent');
                        setInspectorOpen(true);
                      }}
                    >
                      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusTone(status)}`} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">{placement.agent.name}</span>
                        <span className="block text-[11px] text-white/38">instance x{placement.quantity} · {statusLabel(status)}</span>
                      </span>
                      {unreadCount > 0 && (
                        <span className="rounded-full bg-apple-blue px-2 py-0.5 text-[11px] font-semibold text-white">{unreadCount}</span>
                      )}
                    </button>
                  );
                })}
              </SidebarGroup>

              <SidebarGroup title="Workspace Members">
                {workspaceMembers.length === 0 ? (
                  <div className="rounded-[12px] px-3 py-2 text-[12px] text-white/38">참여한 사용자가 없습니다.</div>
                ) : (
                  workspaceMembers.map((member) => {
                    const memberNodeId = `user-${member.node_id}`;
                    const selected = selectedMapNodeId === memberNodeId;
                    const messageCount = detail.messages.filter((message) => message.sender_id === member.ref_id).length;
                    return (
                      <button
                        key={member.node_id}
                        className={`mb-1 flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left transition ${selected ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07] hover:text-white'}`}
                        onClick={() => {
                          setSelectedAgentId(null);
                          setSelectedMapNodeId(memberNodeId);
                          setSelectedMapEdgeId(null);
                          setInspectorMode('agent');
                          setInspectorOpen(true);
                        }}
                      >
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-apple-blue text-[11px] font-semibold text-white">
                          {member.display_name.charAt(0)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium">{member.display_name}</span>
                          <span className="block text-[11px] text-white/38">{member.status} · messages {messageCount}</span>
                        </span>
                      </button>
                    );
                  })
                )}
              </SidebarGroup>

              <SidebarGroup title="Goals">
                <button
                  className={`mb-1 flex w-full items-center justify-between rounded-[12px] px-3 py-2.5 text-left transition ${!selectedGoal ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07]'}`}
                  onClick={() => void selectGoal(null)}
                >
                  <span className="truncate text-[13px] font-medium"># workspace-wide</span>
                  <span className="text-[11px] text-white/38">{detail.recent_message_count}</span>
                </button>
                {topLevelGoals.map((goal) => (
                  <GoalTreeItem
                    key={goal.goal_id}
                    goal={goal}
                    goals={detail.goals}
                    selectedGoalId={selectedGoalId}
                    onSelect={selectGoal}
                  />
                ))}
                {detail.user_can_manage && (
                  <button
                    className="mt-2 w-full rounded-[12px] border border-dashed border-white/18 px-3 py-2 text-left text-[12px] font-medium text-white/55 hover:border-apple-blue/60 hover:text-white"
                    onClick={() => {
                      setGoalParentId(null);
                      setShowGoalForm((value) => !value);
                    }}
                  >
                    + Goal 생성
                  </button>
                )}
                {showGoalForm && (
                  <div className="mt-3 rounded-[14px] bg-black/20 p-3">
                    <input className="mb-2 w-full rounded-[10px] border border-white/10 bg-white/[0.06] px-3 py-2 text-[12px] text-white outline-none" value={goalName} onChange={(e) => setGoalName(e.target.value)} placeholder="Goal 이름" />
                    <textarea className="mb-2 min-h-[64px] w-full rounded-[10px] border border-white/10 bg-white/[0.06] px-3 py-2 text-[12px] text-white outline-none" value={goalDescription} onChange={(e) => setGoalDescription(e.target.value)} placeholder="설명" />
                    <select className="mb-2 w-full rounded-[10px] border border-white/10 bg-[#202126] px-3 py-2 text-[12px] text-white outline-none" value={goalParentId || ''} onChange={(e) => setGoalParentId(e.target.value || null)}>
                      <option value="">상위 Goal 없음</option>
                      {detail.goals.map((goal) => <option key={goal.goal_id} value={goal.goal_id}>{goal.name}</option>)}
                    </select>
                    <select className="mb-2 w-full rounded-[10px] border border-white/10 bg-[#202126] px-3 py-2 text-[12px] text-white outline-none" value={goalPriority} onChange={(e) => setGoalPriority(e.target.value as Goal['priority'])}>
                      {(['low', 'medium', 'high', 'critical'] as const).map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                    </select>
                    <div className="mb-2 max-h-[92px] overflow-y-auto rounded-[10px] border border-white/10 p-2">
                      {detail.placements.map((placement) => (
                        <label key={placement.agent.agent_id} className="mb-1 flex items-center gap-2 text-[11px] text-white/60">
                          <input
                            type="checkbox"
                            checked={goalAssignedAgents.includes(placement.agent.agent_id)}
                            onChange={(event) => {
                              setGoalAssignedAgents((prev) =>
                                event.target.checked
                                  ? [...prev, placement.agent.agent_id]
                                  : prev.filter((agentId) => agentId !== placement.agent.agent_id)
                              );
                            }}
                          />
                          {placement.agent.name}
                        </label>
                      ))}
                    </div>
                    <textarea className="mb-2 min-h-[54px] w-full rounded-[10px] border border-white/10 bg-white/[0.06] px-3 py-2 text-[12px] text-white outline-none" value={goalSuccessCriteria} onChange={(e) => setGoalSuccessCriteria(e.target.value)} placeholder="종료 조건" />
                    <div className="flex gap-2">
                      <button className="flex-1 rounded-[10px] bg-apple-blue px-3 py-2 text-[12px] font-semibold text-white" onClick={createGoal}>생성</button>
                      <button className="rounded-[10px] bg-white/10 px-3 py-2 text-[12px] text-white/70" onClick={() => { resetGoalForm(); setShowGoalForm(false); }}>취소</button>
                    </div>
                  </div>
                )}
              </SidebarGroup>

              <SidebarGroup title="System Agents">
                <button className="flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left text-white/55 hover:bg-white/[0.07]">
                  <span className="h-2.5 w-2.5 rounded-full bg-white/30" />
                  <span className="text-[13px]">Graph Orchestrator</span>
                </button>
                <button className="flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left text-white/55 hover:bg-white/[0.07]">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#ffd60a]" />
                  <span className="text-[13px]">Memory Indexer</span>
                </button>
              </SidebarGroup>
            </div>

            <div className="border-t border-white/10 p-4">
              <div className="flex items-center gap-3 rounded-[14px] bg-white/[0.04] p-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-apple-blue text-[13px] font-semibold text-white">
                  {(user?.name || 'U').charAt(0)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-white">{user?.name || '사용자'}</p>
                  <p className="text-[11px] text-white/38">Settings · Profile</p>
                </div>
              </div>
            </div>
          </aside>

          <main className="flex min-h-0 min-w-0 flex-col bg-[#f4f5f7] text-[#1d1d1f]">
            <div className="flex items-center justify-between border-b border-black/10 bg-white/86 px-5 py-4 backdrop-blur-xl">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-[18px] font-semibold text-[#1d1d1f]"># {selectedGoal ? selectedGoal.name : agentLabel}</h2>
                  <span className={`h-2.5 w-2.5 rounded-full ${selectedGoal?.state === 'blocked' || selectedGoal?.state === 'failed' ? 'bg-[#ff453a]' : selectedAgent ? statusTone(agentStatus(detail.placements.indexOf(selectedAgent))) : 'bg-[#34c759]'}`} />
                </div>
                <p className="text-[12px] text-black/45">
                  {selectedGoal
                    ? `${selectedGoal.state} · ${selectedGoal.progress}% · ${selectedGoal.assigned_agent_ids.length} assigned agents`
                    : selectedAgent ? `${statusLabel(agentStatus(detail.placements.indexOf(selectedAgent)))} · ${selectedAgent.quantity} instance(s)` : 'workspace-wide agent collaboration'}
                </p>
              </div>
              <div className="flex gap-2">
                {detail.user_can_manage && selectedGoal && (
                  <select
                    className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-medium text-black/70 shadow-sm outline-none"
                    value={selectedGoal.state}
                    onChange={(e) => void updateGoalState(selectedGoal, e.target.value as Goal['state'])}
                  >
                    {(['pending', 'running', 'blocked', 'completed', 'failed'] as const).map((state) => (
                      <option key={state} value={state}>{state}</option>
                    ))}
                  </select>
                )}
                <div className="mr-2 flex rounded-[12px] border border-black/10 bg-black/[0.04] p-1">
                  <button
                    className={`rounded-[9px] px-3 py-1.5 text-[12px] font-medium ${workspaceMode === 'messaging' ? 'bg-white text-black/80 shadow-sm' : 'text-black/45'}`}
                    onClick={() => setWorkspaceMode('messaging')}
                  >
                    Messaging
                  </button>
                  <button
                    className={`rounded-[9px] px-3 py-1.5 text-[12px] font-medium ${workspaceMode === 'map' ? 'bg-white text-black/80 shadow-sm' : 'text-black/45'}`}
                    onClick={() => setWorkspaceMode('map')}
                  >
                    Map
                  </button>
                </div>
                <button
                  className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-medium text-black/70 shadow-sm hover:bg-black/[0.03]"
                  onClick={() => {
                    setInspectorMode('agent');
                    setInspectorOpen(true);
                  }}
                >
                  View Agent Info
                </button>
                <button
                  className="rounded-[10px] border border-black/10 bg-white px-3 py-2 text-[12px] font-medium text-black/70 shadow-sm hover:bg-black/[0.03]"
                  onClick={() => {
                    setInspectorMode('logs');
                    setInspectorOpen(true);
                  }}
                >
                  Expand Logs
                </button>
                {detail.user_can_manage && (
                  <button
                    className="rounded-[10px] border border-[#ff453a]/20 bg-[#ff453a]/10 px-3 py-2 text-[12px] font-medium text-[#d70015] shadow-sm hover:bg-[#ff453a]/15"
                    onClick={deleteWorkspace}
                  >
                    Delete Workspace
                  </button>
                )}
              </div>
            </div>

            {workspaceMode === 'messaging' ? (
              <>
                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-6 md:px-7">
                  {activeMessages.length === 0 ? (
                    <div className="mx-auto mt-20 max-w-[420px] rounded-[18px] border border-black/8 bg-white p-6 text-center shadow-sm">
                      <p className="text-[17px] font-semibold text-[#1d1d1f]">아직 메시지가 없습니다</p>
                      <p className="mt-2 text-[13px] leading-5 text-black/50">워크스페이스에 첫 메시지를 보내면 에이전트 협업 타임라인이 이곳에 표시됩니다.</p>
                    </div>
                  ) : (
                    activeMessages.map((message) => {
                      const isMine = message.sender_id === user?.user_id;
                      const isExpanded = expandedMessageId === message.message_id;
                      return (
                        <div key={message.message_id} className={`flex ${isMine ? 'justify-end' : 'justify-start'}`}>
                          <div className={`flex max-w-[780px] gap-3 ${isMine ? 'flex-row-reverse' : ''}`}>
                            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold ${isMine ? 'bg-apple-blue text-white' : 'bg-white text-black/70 shadow-sm'}`}>
                              {(isMine ? user?.name : message.sender_name || message.sender_type || 'A')?.charAt(0)}
                            </div>
                            <div className={`min-w-0 ${isMine ? 'items-end text-right' : 'items-start text-left'}`}>
                              <div className={`mb-1 flex items-center gap-2 ${isMine ? 'justify-end' : 'justify-start'}`}>
                                <span className="text-[13px] font-semibold text-black/75">{isMine ? 'You' : message.sender_name || message.sender_type}</span>
                                <span className="text-[11px] text-black/35">{new Date(message.sent_at).toLocaleString()}</span>
                              </div>
                              <div className={`rounded-[18px] px-4 py-3 text-[14px] leading-6 shadow-sm ${isMine ? 'rounded-br-[6px] bg-apple-blue text-white' : 'rounded-bl-[6px] border border-black/6 bg-white text-black/78'}`}>
                                {bodyPreview(message.body_ref)}
                              </div>
                              <button
                                className={`mt-1.5 text-[11px] font-medium ${isMine ? 'text-apple-blue' : 'text-black/42 hover:text-apple-blue'}`}
                                onClick={() => {
                                  setExpandedMessageId(isExpanded ? null : message.message_id);
                                  setInspectorMode('message');
                                  setInspectorOpen(true);
                                }}
                              >
                                {isExpanded ? 'Hide details' : 'Inspect details'}
                              </button>
                              {isExpanded && (
                                <div className={`mt-2 rounded-[12px] border border-black/8 bg-white/70 px-3 py-2 text-[11px] text-black/45 ${isMine ? 'text-right' : 'text-left'}`}>
                                  Inspector opened · {message.receipt_count} receipts · {message.priority} priority
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                  <div ref={messageFeedEndRef} />
                </div>
                <div className="border-t border-black/10 bg-white/90 p-3">
                  <div className="flex items-center gap-2 rounded-[14px] border border-black/10 bg-[#f7f8fa] p-1.5 shadow-inner">
                    <textarea
                      className="min-h-[36px] flex-1 resize-none bg-transparent px-3 py-1.5 text-[14px] leading-5 text-black/80 outline-none placeholder:text-black/35"
                      value={messageText}
                      onChange={(e) => setMessageText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return;
                        e.preventDefault();
                        void publishMessage();
                      }}
                      placeholder="@agent_name 에게 메시지 보내기"
                    />
                    <button className="btn-primary !h-9 !rounded-[10px] !px-4 !py-0" onClick={publishMessage}>Send</button>
                  </div>
                  {publishResult && (
                    <p className="mt-2 text-[11px] text-black/38">
                      Last routing: queued={String(publishResult.routing.queued)} · receipts={publishResult.routing.receipt_ids.length}
                    </p>
                  )}
                </div>
              </>
            ) : (
              <div className="min-h-0 flex-1 bg-[#eef0f4] p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap gap-2">
                    {(['all', 'active', 'processing', 'idle', 'error'] as const).map((filter) => (
                      <button
                        key={filter}
                        className={`rounded-full px-3 py-1.5 text-[12px] font-medium ${mapFilter === filter ? 'bg-apple-blue text-white' : 'bg-white text-black/55 shadow-sm'}`}
                        onClick={() => setMapFilter(filter)}
                      >
                        {filter}
                      </button>
                    ))}
                  </div>
                  <p className="text-[12px] text-black/45">{mapNodes.length} nodes · {mapEdges.length} edges</p>
                </div>
                <div className="h-[calc(100%-44px)] overflow-hidden rounded-[18px] border border-black/10 bg-white">
                  <ReactFlow
                    nodes={mapNodes}
                    edges={mapEdges}
                    onNodesChange={onMapNodesChange}
                    onEdgesChange={onMapEdgesChange}
                    onNodeClick={onTopologyNodeClick}
                    onEdgeClick={onTopologyEdgeClick}
                    fitView
                    minZoom={0.25}
                    maxZoom={1.8}
                  >
                    <Background color="#d1d1d6" gap={18} />
                    <Controls />
                    <MiniMap
                      nodeColor={(node) => topologyStatusTone(String(node.data.status || 'idle') as 'active' | 'processing' | 'idle' | 'error')}
                      pannable
                      zoomable
                    />
                  </ReactFlow>
                </div>
              </div>
            )}
          </main>

          {inspectorOpen && (
            <aside className="min-h-0 overflow-y-auto border-t border-white/10 bg-[#17181c] p-5 xl:border-l xl:border-t-0">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.16em] text-white/35">Inspector</p>
                  <h2 className="mt-1 text-[17px] font-semibold text-white">
                    {inspectorMode === 'message'
                      ? 'Message Details'
                      : inspectorMode === 'logs'
                        ? 'Execution Logs'
                        : selectedMapNode?.data.nodeType === 'user'
                          ? 'User Node Info'
                          : 'Agent Info'}
                  </h2>
                </div>
                <button className="text-[20px] text-white/45 hover:text-white" onClick={() => setInspectorOpen(false)}>×</button>
              </div>

              {inspectorMode === 'message' && expandedMessage ? (
                <InspectorSection title="Structured Message">
                  <InspectorKV label="Natural output" value={bodyPreview(expandedMessage.body_ref)} />
                  <InspectorKV label="Domain / intent" value={`${expandedMessage.domain || '-'} / ${expandedMessage.intent || '-'}`} />
                  <InspectorKV label="Priority" value={expandedMessage.priority} />
                  <InspectorKV label="Receipts" value={`${expandedMessage.receipt_count}`} />
                  <InspectorKV label="Queued" value={String(expandedMessage.queued)} />
                  <pre className="mt-3 max-h-[260px] overflow-auto rounded-[12px] bg-black/28 p-3 text-[11px] leading-5 text-white/58">
                    {JSON.stringify(expandedMessage, null, 2)}
                  </pre>
                </InspectorSection>
              ) : inspectorMode === 'logs' ? (
                <>
                  {selectedGoal && (
                    <InspectorSection title="Goal Details">
                      <InspectorKV label="Goal" value={selectedGoal.name} />
                      <InspectorKV label="Status / progress" value={`${selectedGoal.state} / ${selectedGoal.progress}%`} />
                      <InspectorKV label="Priority" value={selectedGoal.priority} />
                      <InspectorKV label="Assigned agents" value={`${selectedGoal.assigned_agent_ids.length}`} />
                      <InspectorKV label="Success criteria" value={selectedGoal.success_criteria || '-'} />
                    </InspectorSection>
                  )}
                  <InspectorSection title="Execution Summary">
                    <InspectorKV label="Recent messages" value={`${activeMessages.length}`} />
                    <InspectorKV label="Active instances" value={`${detail.active_agent_count}`} />
                    <InspectorKV label="Last routing receipts" value={`${publishResult?.routing.receipt_ids.length || 0}`} />
                    {selectedMapEdge && (
                      <>
                        <InspectorKV label="Selected edge" value={selectedMapEdge.id} />
                        <InspectorKV label="Relation" value={String(selectedMapEdge.data?.relation_type || selectedMapEdge.label || '-')} />
                        <InspectorKV label="Source → Target" value={`${selectedMapEdge.source} → ${selectedMapEdge.target}`} />
                      </>
                    )}
                  </InspectorSection>
                  <InspectorSection title="Graph Relationships">
                    <div className="rounded-[14px] border border-dashed border-white/16 p-4 text-[13px] leading-5 text-white/45">
                      Future-ready placeholder for agent graph edges, message dependencies, and parallel execution groups.
                    </div>
                  </InspectorSection>
                </>
              ) : (
                <>
                  <InspectorSection title={selectedMapNode?.data.nodeType === 'user' ? 'User Node' : 'Agent Configuration'}>
                    {selectedMapNode?.data.nodeType === 'user' ? (
                      <>
                        <InspectorKV label="Name" value={String(selectedMapNode.data.displayName || 'User node')} />
                        <InspectorKV label="Node type" value="user" />
                        <InspectorKV label="User id" value={String(selectedMapNode.data.refId || '-')} />
                      </>
                    ) : (
                      <>
                        <InspectorKV label="Name" value={selectedAgent?.agent.name || 'No agent selected'} />
                        <InspectorKV label="Instances" value={`${selectedAgent?.quantity || 0}`} />
                        <InspectorKV label="Version" value={selectedAgent?.agent.version || '-'} />
                        <InspectorKV label="Visibility" value={selectedAgent?.agent.visibility || '-'} />
                        <InspectorKV label="Tools" value={selectedAgent?.agent.tools.join(', ') || '-'} />
                      </>
                    )}
                    {selectedMapNode && (
                      <>
                        <InspectorKV label="Map status" value={String(selectedMapNode.data.status || '-')} />
                        <InspectorKV label="Recent node messages" value={String(selectedMapNode.data.messageCount || 0)} />
                        <InspectorKV label="Recent node events" value={String(selectedMapNode.data.eventCount || 0)} />
                      </>
                    )}
                  </InspectorSection>
                  <InspectorSection title="Workspace Members">
                    {workspaceMembers.length === 0 ? (
                      <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                        참여 중인 사용자가 없습니다.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {workspaceMembers.map((member) => (
                          <div key={member.node_id} className="flex items-center gap-3 rounded-[12px] bg-white/[0.04] px-3 py-2">
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-apple-blue text-[12px] font-semibold text-white">
                              {member.display_name.charAt(0)}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-[13px] font-medium text-white/76">{member.display_name}</span>
                              <span className="block text-[11px] text-white/38">{member.status} · {member.ref_id.slice(0, 8)}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </InspectorSection>
                  <InspectorSection title="Current State / Memory">
                    <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                      Memory snapshot and runtime state will appear here when persistent agent memory is connected.
                    </div>
                  </InspectorSection>
                </>
              )}
            </aside>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in font-apple">
      <Header
        title="워크스페이스"
        subtitle="공장, 도시 데이터, 운영 환경을 다중 에이전트 메시 구조로 관리합니다."
        actionLabel={canCreateWorkspace ? '새 워크스페이스 생성' : undefined}
        onAction={canCreateWorkspace ? () => setView('create') : undefined}
        secondaryActionLabel="워크스페이스 참여"
        onSecondaryAction={openJoinWorkspace}
      />
      {error && <Alert message={error} />}
      {joinOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4 backdrop-blur-sm">
          <div className="w-full max-w-4xl rounded-[18px] border border-white/10 bg-[#17181c] p-6 shadow-[0_24px_90px_rgba(0,0,0,0.48)]">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-[22px] font-semibold text-white">워크스페이스 참여</h2>
                <p className="mt-1 text-[13px] text-white/50">전체 워크스페이스 목록에서 참여할 환경을 선택하고 참여 코드를 입력하세요.</p>
              </div>
              <button className="text-[22px] text-white/45 hover:text-white" onClick={() => setJoinOpen(false)}>×</button>
            </div>
            <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-end">
              <Field label="참여 코드">
                <input className="input-field" value={joinCode} onChange={(e) => setJoinCode(e.target.value)} placeholder="1234" />
              </Field>
              <button className="btn-secondary md:mb-0.5" onClick={openJoinWorkspace} disabled={joinLoading}>
                {joinLoading ? '새로고침 중...' : '목록 새로고침'}
              </button>
            </div>
            {joinError && <Alert message={joinError} />}
            {joinLoading ? (
              <div className="py-12 text-center text-white/50">참여 가능한 워크스페이스를 불러오는 중...</div>
            ) : joinableWorkspaces.length === 0 ? (
              <div className="rounded-[14px] border border-white/10 bg-white/[0.04] p-6 text-[14px] text-white/55">참여 가능한 워크스페이스가 없습니다.</div>
            ) : (
              <div className="max-h-[56vh] overflow-y-auto">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {joinableWorkspaces.map((workspace) => (
                    <div key={workspace.workspace_id} className="rounded-[14px] border border-white/10 bg-apple-surface2 p-4">
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h3 className="truncate text-[16px] font-semibold text-white">{workspace.name || '워크스페이스'}</h3>
                          <p className="mt-1 line-clamp-2 text-[13px] text-white/55">{workspace.description || '환경 설명 없음'}</p>
                        </div>
                        <span className="shrink-0 rounded-full bg-white/10 px-2 py-1 text-[11px] text-white/55">{workspace.access_status}</span>
                      </div>
                      <div className="mb-4 grid grid-cols-3 gap-2 text-[11px] text-white/45">
                        <span className="rounded-[9px] bg-white/[0.04] px-2 py-1.5">에이전트 {workspace.agent_count}</span>
                        <span className="rounded-[9px] bg-white/[0.04] px-2 py-1.5">사용자 {workspace.user_count}</span>
                        <span className="rounded-[9px] bg-white/[0.04] px-2 py-1.5">활동 {workspace.recent_activity_count}</span>
                      </div>
                      <button
                        className="btn-primary w-full disabled:opacity-45"
                        disabled={workspace.user_can_access || joiningId === workspace.workspace_id}
                        onClick={() => void joinWorkspace(workspace)}
                      >
                        {workspace.user_can_access ? '이미 참여됨' : joiningId === workspace.workspace_id ? '참여 중...' : '참여'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {loading ? (
        <div className="py-20 text-center text-white/50">불러오는 중...</div>
      ) : workspaces.length === 0 ? (
        <div className="bg-apple-surface1 rounded-[18px] p-8 border border-white/5">
          <h2 className="text-[24px] font-semibold text-white mb-2">현재 할당된 환경이 없습니다</h2>
          <p className="text-[14px] text-white/50">워크스페이스 참여를 통해 접근 권한을 얻으면 목록에 표시됩니다.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 mb-8">
          {workspaces.map((workspace) => (
            <button key={workspace.workspace_id} onClick={() => openDetail(workspace.workspace_id)} className="text-left bg-apple-surface1 rounded-[18px] p-6 border border-white/5 hover:border-apple-blue/40 transition-all">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h2 className="text-[21px] font-semibold text-white">{workspace.name}</h2>
                  <p className="text-[13px] text-white/50 mt-1 line-clamp-2">{workspace.description || '환경 설명 없음'}</p>
                </div>
                <span className="text-[11px] text-apple-blue bg-apple-blue/10 px-2 py-1 rounded-full">{workspace.access_status}</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-[12px] text-white/55">
                <span className="rounded-[10px] bg-white/[0.04] px-3 py-2">에이전트 {workspace.agent_count}</span>
                <span className="rounded-[10px] bg-white/[0.04] px-3 py-2">사용자 {workspace.user_count}</span>
                <span className="rounded-[10px] bg-white/[0.04] px-3 py-2">최근 활동 {workspace.recent_activity_count}</span>
              </div>
            </button>
          ))}
        </div>
      )}
      {canGrantAccess && accessRequests.length > 0 && (
        <section className="mt-6 bg-apple-surface1 rounded-[18px] p-6 border border-white/5">
          <h2 className="text-[17px] font-semibold text-white mb-3">권한 승인 대기</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {accessRequests.map((request) => (
              <div key={request.request_id} className="bg-apple-surface2 rounded-[12px] p-4 border border-white/10">
                <p className="text-[12px] text-white/45 break-all">{request.workspace_id}</p>
                <p className="text-[13px] text-white/70 my-2">{request.reason || '사유 없음'}</p>
                <div className="flex gap-3">
                  <button className="text-[13px] text-[#34c759]" onClick={() => decideRequest(request.request_id, 'approve')}>승인</button>
                  <button className="text-[13px] text-[#ff3b30]" onClick={() => decideRequest(request.request_id, 'reject')}>반려</button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Header({
  title,
  subtitle,
  actionLabel,
  onAction,
  secondaryActionLabel,
  onSecondaryAction,
}: {
  title: string;
  subtitle: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
}) {
  return (
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8 pb-6 border-b border-white/10">
      <div>
        <h1 className="text-[40px] font-semibold text-white tracking-[-0.28px] leading-[1.07] mb-2">{title}</h1>
        <p className="text-[17px] text-white/60 tracking-[-0.374px] leading-[1.47]">{subtitle}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {secondaryActionLabel && onSecondaryAction && <button className="btn-secondary" onClick={onSecondaryAction}>{secondaryActionLabel}</button>}
        {actionLabel && onAction && <button className="btn-primary" onClick={onAction}>{actionLabel}</button>}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12px] text-white/60 uppercase mb-1.5">{label}</span>
      {children}
    </label>
  );
}

function Alert({ message }: { message: string }) {
  return <div className="mb-4 bg-[#ff3b30]/15 text-[#ff3b30] border border-[#ff3b30]/30 rounded-[10px] px-4 py-3 text-[14px]">{message}</div>;
}

function SidebarGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-white/30">{title}</p>
      {children}
    </section>
  );
}

function GoalTreeItem({
  goal,
  goals,
  selectedGoalId,
  onSelect,
  depth = 0,
}: {
  goal: Goal;
  goals: Goal[];
  selectedGoalId: string | null;
  onSelect: (goal: Goal) => void;
  depth?: number;
}) {
  const children = goals.filter((item) => item.parent_goal_id === goal.goal_id);
  const stateTone =
    goal.state === 'completed'
      ? 'bg-[#34c759]'
      : goal.state === 'blocked' || goal.state === 'failed'
        ? 'bg-[#ff453a]'
        : goal.state === 'running'
          ? 'bg-[#ffd60a]'
          : 'bg-white/30';

  return (
    <div>
      <button
        className={`mb-1 flex w-full items-center gap-2 rounded-[12px] py-2 pr-3 text-left transition ${selectedGoalId === goal.goal_id ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07]'}`}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
        onClick={() => onSelect(goal)}
      >
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${stateTone}`} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{goal.name}</span>
          <span className="block text-[11px] text-white/38">{goal.state} · {goal.progress}% · msg {goal.recent_message_count}</span>
        </span>
      </button>
      {children.map((child) => (
        <GoalTreeItem
          key={child.goal_id}
          goal={child}
          goals={goals}
          selectedGoalId={selectedGoalId}
          onSelect={onSelect}
          depth={depth + 1}
        />
      ))}
    </div>
  );
}

function InspectorSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5 rounded-[16px] border border-white/8 bg-white/[0.035] p-4">
      <h3 className="mb-3 text-[13px] font-semibold text-white/78">{title}</h3>
      {children}
    </section>
  );
}

function InspectorKV({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-3">
      <p className="text-[11px] uppercase tracking-[0.12em] text-white/30">{label}</p>
      <p className="mt-1 break-words text-[13px] leading-5 text-white/68">{value}</p>
    </div>
  );
}
