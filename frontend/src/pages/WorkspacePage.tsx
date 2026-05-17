import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Background,
  Connection,
  Controls,
  Edge,
  EdgeMouseHandler,
  MarkerType,
  MiniMap,
  Node,
  NodeChange,
  NodeMouseHandler,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { agentsApi, AgentCreatePayload, ToolDescriptor } from '../api/agents';
import { AgentCard, getAgents } from '../api/marketplace';
import {
  Goal,
  PublishMessageResult,
  Workspace,
  WorkspaceAccessRequest,
  WorkspaceDetail,
  WorkspaceJoinable,
  WorkspaceMessage,
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

function mentionRangeAt(text: string, caret: number): { start: number; end: number; query: string } | null {
  const beforeCaret = text.slice(0, caret);
  const start = beforeCaret.lastIndexOf('@');
  if (start < 0) return null;
  const previous = start > 0 ? text[start - 1] : '';
  if (previous && !/\s/.test(previous)) return null;
  const query = beforeCaret.slice(start + 1);
  if (/[\s@]/.test(query)) return null;
  return { start, end: caret, query };
}

function mentionToken(displayName: string): string {
  return `@${displayName.trim().replace(/\s+/g, '_')}`;
}

function mentionKey(displayName: string): string {
  return displayName.trim().replace(/\s+/g, '_').toLowerCase();
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
  const [toolCatalog, setToolCatalog] = useState<ToolDescriptor[]>([]);
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
  const [selectedCreateEdgeId, setSelectedCreateEdgeId] = useState<string | null>(null);
  const [createNodePositions, setCreateNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const [createMapNodes, setCreateMapNodes, applyCreateMapNodeChanges] = useNodesState<Node>([]);
  const [createMapEdges, setCreateMapEdges, onCreateMapEdgesChange] = useEdgesState<Edge>([]);
  const [draftAgentName, setDraftAgentName] = useState('');
  const [draftAgentPurpose, setDraftAgentPurpose] = useState('');
  const [messageText, setMessageText] = useState('');
  const [mentionRange, setMentionRange] = useState<{ start: number; end: number; query: string } | null>(null);
  const [activeMentionIndex, setActiveMentionIndex] = useState(0);
  const [optimisticMessages, setOptimisticMessages] = useState<WorkspaceMessage[]>([]);
  const [typingAgentIds, setTypingAgentIds] = useState<string[]>([]);
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
  const [mapNodes, setMapNodes, applyMapNodeChanges] = useNodesState<Node>([]);
  const [mapEdges, setMapEdges, onMapEdgesChange] = useEdgesState<Edge>([]);
  const [mapNodePositions, setMapNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const [topologySaving, setTopologySaving] = useState(false);
  const [pendingTopologyEdges, setPendingTopologyEdges] = useState<Array<{ edge_id: string; source_node_id: string; target_node_id: string; edge_type: 'subscription'; status: 'active'; created_at: string; updated_at: string }>>([]);
  const [removedTopologyEdgeIds, setRemovedTopologyEdgeIds] = useState<string[]>([]);
  const [agentToolDrafts, setAgentToolDrafts] = useState<Record<string, string[]>>({});
  const [toolSavingAgentId, setToolSavingAgentId] = useState<string | null>(null);
  const messageFeedEndRef = useRef<HTMLDivElement | null>(null);
  const messageInputRef = useRef<HTMLTextAreaElement | null>(null);

  const roles = new Set(user?.roles || []);
  const canCreateWorkspace =
    roles.has('agent_owner') ||
    roles.has('agent_engineer') ||
    roles.has('trust_ops') ||
    roles.has('release_manager');
  const canGrantAccess =
    roles.has('trust_ops') || roles.has('release_manager') || roles.has('evaluator');

  const basketItems = useMemo(() => Object.values(basket), [basket]);
  const selectedGoal = detail?.goals.find((goal) => goal.goal_id === selectedGoalId) || null;
  const topLevelGoals = detail?.goals.filter((goal) => !goal.parent_goal_id) || [];
  const workspaceMembers = detail?.nodes.filter((node) => node.node_type === 'user') || [];
  const activeMessages = useMemo(
    () => {
      const messages = [...(detail?.messages || []), ...optimisticMessages];
      return selectedGoal?.conversation_id
        ? messages.filter((message) => message.conversation_id === selectedGoal.conversation_id)
        : messages;
    },
    [detail?.messages, optimisticMessages, selectedGoal?.conversation_id]
  );
  const selectedMapNode = mapNodes.find((node) => node.id === selectedMapNodeId);
  const selectedMapEdge = mapEdges.find((edge) => edge.id === selectedMapEdgeId);
  const topologyEdges = useMemo(
    () => [
      ...(detail?.edges || []).filter((edge) => !removedTopologyEdgeIds.includes(edge.edge_id)),
      ...pendingTopologyEdges,
    ],
    [detail?.edges, pendingTopologyEdges, removedTopologyEdgeIds]
  );
  const selectedSubscribableNodes = useMemo(
    () =>
      selectedMapNodeId
        ? detail?.nodes.filter((node) => node.node_id !== selectedMapNodeId) || []
        : [],
    [detail?.nodes, selectedMapNodeId]
  );
  const mentionCandidates = useMemo(() => {
    if (!detail || !mentionRange) return [];
    const query = mentionRange.query.toLowerCase();
    return detail.nodes
      .filter((node) => {
        if (node.node_type === 'user' && node.ref_id === user?.user_id) return false;
        const name = node.display_name.toLowerCase();
        return !query || name.includes(query) || node.node_type.includes(query);
      })
      .sort((a, b) => {
        if (a.node_type !== b.node_type) return a.node_type === 'user' ? -1 : 1;
        return a.display_name.localeCompare(b.display_name);
      })
      .slice(0, 8);
  }, [detail, mentionRange, user?.user_id]);
  const typingAgents = useMemo(
    () =>
      detail?.placements
        .filter((placement) => typingAgentIds.includes(placement.agent.agent_id))
        .map((placement) => placement.agent) || [],
    [detail?.placements, typingAgentIds]
  );

  const onMapNodesChange = (changes: NodeChange<Node>[]) => {
    applyMapNodeChanges(changes);
    setMapNodePositions((positions) => {
      let changed = false;
      const nextPositions = { ...positions };
      changes.forEach((change) => {
        if (change.type === 'position' && change.position) {
          nextPositions[change.id] = change.position;
          changed = true;
        }
      });
      return changed ? nextPositions : positions;
    });
  };

  const onCreateMapNodesChange = (changes: NodeChange<Node>[]) => {
    applyCreateMapNodeChanges(changes);
    setCreateNodePositions((positions) => {
      let changed = false;
      const nextPositions = { ...positions };
      changes.forEach((change) => {
        if (change.type === 'position' && change.position) {
          nextPositions[change.id] = change.position;
          changed = true;
        }
      });
      return changed ? nextPositions : positions;
    });
  };

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

  const loadToolCatalog = async () => {
    try {
      setToolCatalog(await agentsApi.listTools());
    } catch (err) {
      console.error(err);
      setToolCatalog([]);
    }
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
    void loadToolCatalog();
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
    messageFeedEndRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' });
  }, [view, detail?.messages.length, optimisticMessages.length, typingAgentIds.length]);

  useEffect(() => {
    setActiveMentionIndex((index) => Math.min(index, Math.max(mentionCandidates.length - 1, 0)));
  }, [mentionCandidates.length]);

  useEffect(() => {
    if (view !== 'create') return;
    const userNode = user?.user_id
      ? [{
          id: `user:${user.user_id}`,
          nodeType: 'user' as const,
          refId: user.user_id,
          name: user.name || '나',
          status: 'active' as const,
        }]
      : [];
    const agentNodes = basketItems.map((item) => ({
      id: `agent:${item.agent.agent_id}`,
      nodeType: 'agent' as const,
      refId: item.agent.agent_id,
      name: item.agent.name,
      status: 'idle' as const,
      version: item.agent.version,
      quantity: item.quantity,
    }));
    const graphItems = [...userNode, ...agentNodes];
    const columns = Math.max(3, Math.ceil(Math.sqrt(Math.max(graphItems.length, 1))));
    const nodes: Node[] = graphItems.map((item, index) => {
      const defaultPosition = {
        x: (index % columns) * 260,
        y: Math.floor(index / columns) * 165,
      };
      return {
        id: item.id,
        position: createNodePositions[item.id] || defaultPosition,
        sourcePosition: Position.Top,
        targetPosition: Position.Top,
        connectable: item.nodeType === 'agent',
        data: {
          nodeType: item.nodeType,
          refId: item.refId,
          displayName: item.name,
          status: item.status,
          label: (
            <div className={`min-w-[220px] rounded-[14px] border bg-white px-4 py-3 shadow-sm ${item.nodeType === 'user' ? 'border-[#0071e3]/25' : 'border-black/10'}`}>
              <div className="mb-2 flex items-center gap-2">
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${item.nodeType === 'user' ? 'bg-[#0071e3] text-white' : 'bg-black/[0.06] text-black/60'}`}>
                  {item.nodeType === 'user' ? 'U' : 'A'}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-[#1d1d1f]">{item.name}</span>
                  <span className="block text-[11px] uppercase tracking-[0.08em] text-black/38">{item.nodeType}</span>
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px] text-black/55">
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">
                  {item.nodeType === 'agent' ? `x${item.quantity}` : 'owner'}
                </span>
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">
                  {item.nodeType === 'agent' ? `v${item.version}` : item.status}
                </span>
              </div>
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
    const edges: Edge[] = Object.entries(subscriptionTargets).flatMap(([sourceAgentId, targets]) =>
      targets.flatMap((targetKey) => {
        const source = `agent:${sourceAgentId}`;
        const target = targetKey;
        if (!nodeIds.has(source) || !nodeIds.has(target)) return [];
        return [{
          id: `create-edge:${sourceAgentId}:${targetKey}`,
          source,
          target,
          animated: true,
          label: 'subscription',
          markerEnd: { type: MarkerType.ArrowClosed, color: '#34c759' },
          data: { relation_type: 'subscription' },
          style: { stroke: '#34c759', strokeWidth: 2.2 },
          labelStyle: { fill: '#3a3a3c', fontSize: 11, fontWeight: 600 },
        } satisfies Edge];
      })
    );
    setCreateMapNodes(nodes);
    setCreateMapEdges(edges);
  }, [basketItems, createNodePositions, setCreateMapEdges, setCreateMapNodes, subscriptionTargets, user?.name, user?.user_id, view]);

  const openDetail = async (workspaceId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await workspacesApi.get(workspaceId);
      setDetail(data);
      setOptimisticMessages([]);
      setTypingAgentIds([]);
      setMapNodePositions({});
      setPendingTopologyEdges([]);
      setRemovedTopologyEdgeIds([]);
      setSelectedMapEdgeId(null);
      setSelectedMapNodeId(null);
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

  const createTopologyEdge = (sourceNodeId: string, targetNodeId: string) => {
    if (!sourceNodeId.startsWith('agent:') || sourceNodeId === targetNodeId) {
      setError('구독 관계는 agent 노드에서 다른 노드로만 만들 수 있습니다.');
      return;
    }
    const sourceAgentId = sourceNodeId.replace('agent:', '');
    setSubscriptionTargets((prev) => {
      const current = prev[sourceAgentId] || [];
      if (current.includes(targetNodeId)) return prev;
      return { ...prev, [sourceAgentId]: [...current, targetNodeId] };
    });
    setError(null);
  };

  const onCreateTopologyConnect = (connection: Connection) => {
    if (!connection.source || !connection.target) return;
    createTopologyEdge(connection.source, connection.target);
  };

  const onCreateTopologyEdgeClick: EdgeMouseHandler = (_, edge) => {
    setSelectedCreateEdgeId(edge.id);
  };

  const deleteSelectedCreateEdge = () => {
    if (!selectedCreateEdgeId) return;
    const edge = createMapEdges.find((item) => item.id === selectedCreateEdgeId);
    if (!edge || !edge.source.startsWith('agent:')) return;
    const sourceAgentId = edge.source.replace('agent:', '');
    setSubscriptionTargets((prev) => ({
      ...prev,
      [sourceAgentId]: (prev[sourceAgentId] || []).filter((targetKey) => targetKey !== edge.target),
    }));
    setSelectedCreateEdgeId(null);
  };

  const ensureAgentBasketForTopology = () => {
    if (basketItems.length > 0) return true;
    setError('토폴로지 구성을 위해 에이전트를 하나 이상 배치하세요.');
    setWizardStep(2);
    return false;
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
    setWizardStep(3);
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

  const routedAgentIdsForMessage = (text: string) => {
    if (!detail || !user?.user_id) return [];

    const mentionedTokens = Array.from(text.matchAll(/(?<!\S)@([^\s@]+)/g)).map((match) => match[1].toLowerCase());
    if (mentionedTokens.length > 0) {
      const agentIdByToken = new Map(
        detail.nodes
          .filter((node) => node.node_type === 'agent' && node.status !== 'error')
          .map((node) => [mentionKey(node.display_name), node.ref_id])
      );
      return mentionedTokens
        .map((token) => agentIdByToken.get(token))
        .filter((agentId): agentId is string => Boolean(agentId))
        .filter((agentId, index, agentIds) => agentIds.indexOf(agentId) === index);
    }

    const senderNode = detail.nodes.find(
      (node) => node.node_type === 'user' && node.ref_id === user.user_id
    );
    if (!senderNode) return [];
    const agentRefIdByNodeId = new Map(
      detail.nodes
        .filter((node) => node.node_type === 'agent')
        .map((node) => [node.node_id, node.ref_id])
    );
    return detail.edges
      .filter((edge) => edge.edge_type === 'subscription' && edge.status === 'active' && edge.target_node_id === senderNode.node_id)
      .map((edge) => agentRefIdByNodeId.get(edge.source_node_id))
      .filter((agentId): agentId is string => Boolean(agentId))
      .filter((agentId, index, agentIds) => agentIds.indexOf(agentId) === index);
  };

  const markRoutedAgentsProcessing = (text: string) => {
    if (!detail) return [];
    const routedAgentIds = routedAgentIdsForMessage(text);
    if (routedAgentIds.length === 0) return [];
    const routedAgentIdSet = new Set(routedAgentIds);
    setTypingAgentIds(routedAgentIds);
    setDetail({
      ...detail,
      nodes: detail.nodes.map((node) =>
        node.node_type === 'agent' && routedAgentIdSet.has(node.ref_id)
          ? { ...node, status: 'processing' }
          : node
      ),
    });
    return routedAgentIds;
  };

  const addOptimisticUserMessage = (text: string) => {
    if (!detail || !user?.user_id) return null;
    const messageId =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? `local-${crypto.randomUUID()}`
        : `local-${Date.now()}`;
    const optimisticMessage: WorkspaceMessage = {
      message_id: messageId,
      sender_id: user.user_id,
      sender_type: 'user',
      sender_name: user.name,
      domain: 'workspace',
      intent: selectedGoal ? 'goal_message' : 'operator_message',
      conversation_id: selectedGoal?.conversation_id || null,
      priority: 'medium',
      tags: selectedGoal ? ['workspace', 'goal'] : ['workspace'],
      body_ref: `inline:json:${JSON.stringify({ message: text })}`,
      sent_at: new Date().toISOString(),
      processed_count: 0,
      queued: true,
      receipt_count: 0,
    };
    setOptimisticMessages((messages) => [...messages, optimisticMessage]);
    return messageId;
  };

  const updateMentionRange = (text: string, caret: number) => {
    setMentionRange(mentionRangeAt(text, caret));
    setActiveMentionIndex(0);
  };

  const insertMention = (candidate: (typeof mentionCandidates)[number]) => {
    if (!mentionRange) return;
    const token = mentionToken(candidate.display_name);
    const prefix = messageText.slice(0, mentionRange.start);
    const suffix = messageText.slice(mentionRange.end);
    const nextText = `${prefix}${token} ${suffix}`;
    const nextCaret = prefix.length + token.length + 1;
    setMessageText(nextText);
    setMentionRange(null);
    window.requestAnimationFrame(() => {
      messageInputRef.current?.focus();
      messageInputRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const publishMessage = async () => {
    if (!detail) return;
    const nextMessage = messageText.trim();
    if (!nextMessage) return;
    setError(null);
    const optimisticMessageId = addOptimisticUserMessage(nextMessage);
    markRoutedAgentsProcessing(nextMessage);
    setMessageText('');
    setMentionRange(null);
    try {
      const result = await workspacesApi.publish(detail.workspace_id, {
        domain: 'workspace',
        intent: selectedGoal ? 'goal_message' : 'operator_message',
        payload: { message: nextMessage },
        tags: selectedGoal ? ['workspace', 'goal'] : ['workspace'],
        priority: 'medium',
        conversation_id: selectedGoal?.conversation_id,
      });
      setPublishResult(result);
      const nextDetail = await workspacesApi.get(detail.workspace_id);
      if (selectedGoal?.conversation_id) {
        nextDetail.messages = await workspacesApi.listMessages(detail.workspace_id, selectedGoal.conversation_id);
      }
      setOptimisticMessages((messages) => messages.filter((message) => message.message_id !== optimisticMessageId));
      setTypingAgentIds([]);
      setDetail(nextDetail);
    } catch (err) {
      console.error(err);
      setOptimisticMessages((messages) => messages.filter((message) => message.message_id !== optimisticMessageId));
      setTypingAgentIds([]);
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

  const startSubGoalForm = (parentGoal: Goal) => {
    setGoalParentId(parentGoal.goal_id);
    setGoalName('');
    setGoalDescription('');
    setGoalPriority(parentGoal.priority);
    setGoalSuccessCriteria('');
    setGoalAssignedAgents(parentGoal.assigned_agent_ids);
    setShowGoalForm(true);
  };

  const deleteGoal = async (goal: Goal) => {
    if (!detail) return;
    const childGoalIds = new Set<string>();
    const collectChildren = (parentGoalId: string) => {
      detail.goals
        .filter((item) => item.parent_goal_id === parentGoalId)
        .forEach((child) => {
          childGoalIds.add(child.goal_id);
          collectChildren(child.goal_id);
        });
    };
    collectChildren(goal.goal_id);
    const deleteLabel = goal.parent_goal_id ? 'Sub Goal' : 'Goal';
    if (!window.confirm(`${deleteLabel} "${goal.name}"을 삭제하시겠습니까? 하위 Goal도 함께 삭제됩니다.`)) return;
    await workspacesApi.deleteGoal(detail.workspace_id, goal.goal_id);
    const nextDetail = await workspacesApi.get(detail.workspace_id);
    setDetail(nextDetail);
    if (selectedGoalId === goal.goal_id || childGoalIds.has(selectedGoalId || '')) {
      setSelectedGoalId(null);
    }
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

    const agentById = new Map(detail.placements.map((placement) => [placement.agent.agent_id, placement]));
    const edgeDegreeByNodeId = new Map<string, { incoming: number; outgoing: number }>();
    topologyEdges.forEach((edge) => {
      const sourceDegree = edgeDegreeByNodeId.get(edge.source_node_id) || { incoming: 0, outgoing: 0 };
      sourceDegree.outgoing += 1;
      edgeDegreeByNodeId.set(edge.source_node_id, sourceDegree);
      const targetDegree = edgeDegreeByNodeId.get(edge.target_node_id) || { incoming: 0, outgoing: 0 };
      targetDegree.incoming += 1;
      edgeDegreeByNodeId.set(edge.target_node_id, targetDegree);
    });
    const graphItems = detail.nodes.map((node) => {
      const placement = node.node_type === 'agent' ? agentById.get(node.ref_id) : undefined;
      const messageCount = activeMessages.filter((message) => message.sender_id === node.ref_id).length;
      const degree = edgeDegreeByNodeId.get(node.node_id) || { incoming: 0, outgoing: 0 };
      return {
        id: node.node_id,
        refId: node.ref_id,
        name: node.display_name,
        role: node.node_type === 'agent'
          ? placement?.agent.roles[0] || agentType(node.display_name)
          : 'workspace member',
        type: node.node_type === 'agent' ? agentType(node.display_name) : 'user',
        status: node.status,
        messageCount,
        eventCount: messageCount + degree.incoming + degree.outgoing,
        version: placement?.agent.version || '',
        tools: placement?.agent.tools || [],
        visibility: placement?.agent.visibility || '',
        nodeType: node.node_type,
        incoming: degree.incoming,
        outgoing: degree.outgoing,
      };
    });
    const filteredGraphItems = graphItems.filter((item) =>
      mapFilter === 'all' ? true : item.status === mapFilter
    );
    const columns = Math.max(3, Math.ceil(Math.sqrt(Math.max(filteredGraphItems.length, 1))));
    const nodes: Node[] = filteredGraphItems.map((item, index) => {
      const defaultPosition = {
        x: (index % columns) * 260,
        y: Math.floor(index / columns) * 170,
      };
      const statusColor = topologyStatusTone(item.status);
      const highlighted =
        (item.nodeType === 'agent' && selectedAgentId === item.refId) ||
        selectedMapNodeId === item.id;

      return {
        id: item.id,
        position: mapNodePositions[item.id] || defaultPosition,
        sourcePosition: Position.Top,
        targetPosition: Position.Top,
        connectable: Boolean(detail.user_can_manage),
        data: {
          agentId: item.nodeType === 'agent' ? item.refId : undefined,
          refId: item.refId,
          nodeType: item.nodeType,
          displayName: item.name,
          status: item.status,
          role: item.role,
          messageCount: item.messageCount,
          eventCount: item.eventCount,
          tools: item.tools,
          version: item.version,
          visibility: item.visibility,
          incoming: item.incoming,
          outgoing: item.outgoing,
          label: (
            <div className={`relative min-w-[220px] rounded-[14px] border bg-white px-4 py-3 shadow-sm ${highlighted ? 'border-apple-blue shadow-[0_0_0_4px_rgba(0,113,227,0.14)]' : item.nodeType === 'user' ? 'border-[#0071e3]/20' : 'border-black/10'}`}>
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
                <span className="rounded-[9px] bg-black/[0.04] px-2 py-1">edge {item.incoming + item.outgoing}</span>
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
    const nodeById = new Map(detail.nodes.map((node) => [node.node_id, node]));
    const subscriptionEdges: Edge[] = topologyEdges
      .filter((edge) => nodeIds.has(edge.source_node_id) && nodeIds.has(edge.target_node_id))
      .map((edge) => {
        const active = edge.status === 'active';
        const pending = edge.edge_id.startsWith('local-edge-');
        const sourceNode = nodeById.get(edge.source_node_id);
        const targetNode = nodeById.get(edge.target_node_id);
        return {
          id: edge.edge_id,
          source: edge.source_node_id,
          target: edge.target_node_id,
          animated: active,
          label: 'subscription',
          markerEnd: { type: MarkerType.ArrowClosed, color: active ? '#0071e3' : '#8e8e93' },
          data: {
            relation_type: edge.edge_type,
            status: edge.status,
            pending,
            sourceName: sourceNode?.display_name || edge.source_node_id,
            targetName: targetNode?.display_name || edge.target_node_id,
            created_at: edge.created_at,
            updated_at: edge.updated_at,
          },
          style: {
            stroke: pending ? '#34c759' : active ? '#0071e3' : '#8e8e93',
            strokeWidth: active ? 2.2 : 1.6,
            strokeDasharray: pending || !active ? '5 5' : undefined,
          },
          labelStyle: { fill: '#3a3a3c', fontSize: 11, fontWeight: 600 },
        };
      });

    setMapNodes(nodes);
    setMapEdges(subscriptionEdges);
  }, [activeMessages, detail, mapFilter, mapNodePositions, selectedAgentId, selectedMapNodeId, setMapEdges, setMapNodes, topologyEdges]);

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

  const setTopologySubscriptionDraft = (sourceNodeId: string, targetNodeId: string, enabled: boolean) => {
    if (!detail || !detail.user_can_manage) return;
    if (sourceNodeId === targetNodeId) {
      setError('같은 노드끼리는 구독 관계를 만들 수 없습니다.');
      return;
    }
    const sourceNode = detail.nodes.find((node) => node.node_id === sourceNodeId);
    const targetNode = detail.nodes.find((node) => node.node_id === targetNodeId);
    if (!sourceNode || !targetNode) return;
    if (sourceNode.node_type !== 'agent') {
      setError('구독 관계의 source node 는 agent 여야 합니다.');
      return;
    }
    const existing = topologyEdges.find(
      (edge) => edge.source_node_id === sourceNodeId && edge.target_node_id === targetNodeId
    );

    if (enabled) {
      if (existing) {
        setRemovedTopologyEdgeIds((ids) => ids.filter((edgeId) => edgeId !== existing.edge_id));
        return;
      }
      const now = new Date().toISOString();
      setPendingTopologyEdges((edges) => [
        ...edges,
        {
          edge_id: `local-edge-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          source_node_id: sourceNodeId,
          target_node_id: targetNodeId,
          edge_type: 'subscription',
          status: 'active',
          created_at: now,
          updated_at: now,
        },
      ]);
      setError(null);
      return;
    }

    if (!existing) return;
    if (existing.edge_id.startsWith('local-edge-')) {
      setPendingTopologyEdges((edges) => edges.filter((edge) => edge.edge_id !== existing.edge_id));
    } else {
      setRemovedTopologyEdgeIds((ids) => (
        ids.includes(existing.edge_id) ? ids : [...ids, existing.edge_id]
      ));
    }
    setError(null);
  };

  const onTopologyConnect = (connection: Connection) => {
    if (!connection.source || !connection.target) return;
    setTopologySubscriptionDraft(connection.source, connection.target, true);
  };

  const deleteSelectedTopologyEdge = () => {
    if (!selectedMapEdgeId) return;
    if (selectedMapEdgeId.startsWith('local-edge-')) {
      setPendingTopologyEdges((edges) => edges.filter((edge) => edge.edge_id !== selectedMapEdgeId));
    } else {
      setRemovedTopologyEdgeIds((ids) => (
        ids.includes(selectedMapEdgeId) ? ids : [...ids, selectedMapEdgeId]
      ));
    }
    setSelectedMapEdgeId(null);
  };

  const saveTopologyChanges = async () => {
    if (!detail || (!pendingTopologyEdges.length && !removedTopologyEdgeIds.length)) return;
    setTopologySaving(true);
    setError(null);
    try {
      await Promise.all(removedTopologyEdgeIds.map((edgeId) => workspacesApi.deleteEdge(detail.workspace_id, edgeId)));
      for (const edge of pendingTopologyEdges) {
        await workspacesApi.createEdge(detail.workspace_id, {
          source_node_id: edge.source_node_id,
          target_node_id: edge.target_node_id,
          edge_type: 'subscription',
        });
      }
      const nextDetail = await workspacesApi.get(detail.workspace_id);
      setDetail(nextDetail);
      setPendingTopologyEdges([]);
      setRemovedTopologyEdgeIds([]);
      setSelectedMapEdgeId(null);
    } catch (err) {
      console.error(err);
      setError('토폴로지 변경사항 저장 중 오류가 발생했습니다.');
    } finally {
      setTopologySaving(false);
    }
  };

  const cancelTopologyChanges = () => {
    setPendingTopologyEdges([]);
    setRemovedTopologyEdgeIds([]);
    setSelectedMapEdgeId(null);
  };

  const toggleAgentToolDraft = (agentId: string, toolId: string) => {
    const currentTools =
      agentToolDrafts[agentId] ||
      detail?.placements.find((placement) => placement.agent.agent_id === agentId)?.agent.tools ||
      [];
    const nextTools = currentTools.includes(toolId)
      ? currentTools.filter((id) => id !== toolId)
      : [...currentTools, toolId];
    setAgentToolDrafts((drafts) => ({ ...drafts, [agentId]: nextTools }));
  };

  const saveAgentTools = async (agentId: string) => {
    if (!detail) return;
    const tools =
      agentToolDrafts[agentId] ||
      detail.placements.find((placement) => placement.agent.agent_id === agentId)?.agent.tools ||
      [];
    setToolSavingAgentId(agentId);
    setError(null);
    try {
      const updatedAgent = await workspacesApi.updateAgentTools(detail.workspace_id, agentId, tools);
      setDetail({
        ...detail,
        placements: detail.placements.map((placement) =>
          placement.agent.agent_id === agentId
            ? { ...placement, agent: { ...placement.agent, tools: updatedAgent.tools } }
            : placement
        ),
      });
      setAgentToolDrafts((drafts) => {
        const nextDrafts = { ...drafts };
        delete nextDrafts[agentId];
        return nextDrafts;
      });
    } catch (err) {
      console.error(err);
      setError('에이전트 도구 저장 중 오류가 발생했습니다.');
    } finally {
      setToolSavingAgentId(null);
    }
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
            {[1, 2, 3, 4].map((step) => (
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
                  if (ensureAgentBasketForTopology()) setWizardStep(3);
                }}>다음: 토폴로지 구성</button>
              </div>
            </section>
          )}
          {wizardStep === 3 && (
            <section className="space-y-4">
              <div className="rounded-[14px] border border-white/10 bg-apple-surface2 p-4">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-[17px] font-semibold text-white">Topology 구성</h3>
                    <p className="mt-1 text-[13px] text-white/45">Agent 상단 포인트에서 사용자 또는 다른 agent로 드래그해 subscription edge를 만듭니다.</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      className="rounded-[10px] bg-white/10 px-3 py-2 text-[12px] font-semibold text-[#ff9f0a] disabled:opacity-40"
                      disabled={!selectedCreateEdgeId}
                      onClick={deleteSelectedCreateEdge}
                    >
                      Delete edge
                    </button>
                    <p className="text-[12px] text-white/42">{createMapNodes.length} nodes · {createMapEdges.length} edges</p>
                  </div>
                </div>
                <div className="h-[460px] overflow-hidden rounded-[18px] border border-white/10 bg-white">
                  <ReactFlow
                    nodes={createMapNodes}
                    edges={createMapEdges}
                    onNodesChange={onCreateMapNodesChange}
                    onEdgesChange={onCreateMapEdgesChange}
                    onConnect={onCreateTopologyConnect}
                    onEdgeClick={onCreateTopologyEdgeClick}
                    fitView
                    minZoom={0.25}
                    maxZoom={1.8}
                    nodesDraggable
                    nodesConnectable
                    edgesFocusable
                  >
                    <Background color="#d1d1d6" gap={18} />
                    <Controls />
                    <MiniMap
                      nodeColor={(node) => node.data.nodeType === 'user' ? '#0071e3' : '#8e8e93'}
                      pannable
                      zoomable
                    />
                  </ReactFlow>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {basketItems.map((item) => {
                  const selectedTargets = subscriptionTargets[item.agent.agent_id] || [];
                  return (
                    <div key={`topology-summary-${item.agent.agent_id}`} className="rounded-[12px] bg-white/[0.04] p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="truncate text-[13px] font-semibold text-white">{item.agent.name}</p>
                        <span className={`text-[11px] ${selectedTargets.length > 0 ? 'text-[#34c759]' : 'text-[#ff9f0a]'}`}>{selectedTargets.length} subscriptions</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {selectedTargets.length === 0 ? (
                          <span className="text-[11px] text-white/35">구독 대상 없음</span>
                        ) : (
                          selectedTargets.map((targetKey) => {
                            const [targetType, targetRefId] = targetKey.split(':');
                            const label = targetType === 'user'
                              ? user?.name || '나'
                              : basketItems.find((target) => target.agent.agent_id === targetRefId)?.agent.name || targetRefId;
                            return (
                              <span key={targetKey} className="rounded-[8px] bg-apple-blue/15 px-2 py-1 text-[11px] text-white/72">
                                {targetType} · {label}
                              </span>
                            );
                          })
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-between">
                <button className="btn-secondary" onClick={() => setWizardStep(2)}>이전</button>
                <button className="btn-primary" onClick={() => {
                  setError(null);
                  if (validateAgentSubscriptions()) setWizardStep(4);
                }}>다음: 환경 구성</button>
              </div>
            </section>
          )}
          {wizardStep === 4 && (
            <section className="space-y-4">
              <div className="rounded-[14px] border border-dashed border-white/20 p-8 text-center bg-apple-surface2">
                <p className="text-[17px] font-semibold text-white mb-1">환경 구성</p>
                <p className="text-[14px] text-white/50">Coming Soon · 에이전트가 동작할 환경 변수, 데이터 연결, 권한 정책은 후속 단계에서 구현합니다.</p>
              </div>
              <div className="flex justify-between">
                <button className="btn-secondary" onClick={() => setWizardStep(3)}>이전</button>
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
    const workspaceNodeById = new Map(detail.nodes.map((node) => [node.node_id, node]));
    const selectedSubscribedNodes = selectedMapNodeId
      ? topologyEdges
          .filter((edge) => edge.source_node_id === selectedMapNodeId)
          .map((edge) => ({
            edge,
            node: workspaceNodeById.get(edge.target_node_id),
          }))
          .filter((item) => Boolean(item.node))
      : [];
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
                    canManage={detail.user_can_manage}
                    onCreateChild={startSubGoalForm}
                    onDelete={deleteGoal}
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
                {detail.user_can_delete && (
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
                      const isSystem = message.sender_type === 'system';
                      const isMine = message.sender_type === 'user' && message.sender_id === user?.user_id;
                      const isExpanded = expandedMessageId === message.message_id;
                      return (
                        <div key={message.message_id} className={`flex ${isMine ? 'justify-end' : 'justify-start'}`}>
                          <div className={`flex max-w-[780px] gap-3 ${isMine ? 'flex-row-reverse' : ''}`}>
                            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold ${isMine ? 'bg-apple-blue text-white' : isSystem ? 'bg-[#ff3b30] text-white' : 'bg-white text-black/70 shadow-sm'}`}>
                              {(isMine ? user?.name : message.sender_name || message.sender_type || 'A')?.charAt(0)}
                            </div>
                            <div className={`min-w-0 ${isMine ? 'items-end text-right' : 'items-start text-left'}`}>
                              <div className={`mb-1 flex items-center gap-2 ${isMine ? 'justify-end' : 'justify-start'}`}>
                                <span className={`text-[13px] font-semibold ${isSystem ? 'text-[#d70015]' : 'text-black/75'}`}>{isMine ? 'You' : message.sender_name || message.sender_type}</span>
                                <span className="text-[11px] text-black/35">{new Date(message.sent_at).toLocaleString()}</span>
                              </div>
                              <div className={`rounded-[18px] px-4 py-3 text-[14px] leading-6 shadow-sm ${isMine ? 'rounded-br-[6px] bg-apple-blue text-white' : isSystem ? 'rounded-bl-[6px] border border-[#ff3b30]/25 bg-[#fff2f2] text-[#d70015]' : 'rounded-bl-[6px] border border-black/6 bg-white text-black/78'}`}>
                                {bodyPreview(message.body_ref)}
                              </div>
                              <button
                                className={`mt-1.5 text-[11px] font-medium ${isMine ? 'text-apple-blue' : isSystem ? 'text-[#d70015]/70 hover:text-[#d70015]' : 'text-black/42 hover:text-apple-blue'}`}
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
                  {typingAgents.map((agent) => (
                    <div key={`typing-${agent.agent_id}`} className="flex justify-start">
                      <div className="flex max-w-[780px] gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-[13px] font-semibold text-black/70 shadow-sm">
                          {agent.name.charAt(0)}
                        </div>
                        <div className="min-w-0 text-left">
                          <div className="mb-1 flex items-center gap-2">
                            <span className="text-[13px] font-semibold text-black/75">{agent.name}</span>
                            <span className="text-[11px] text-black/35">typing</span>
                          </div>
                          <div className="inline-flex items-center gap-2 rounded-[18px] rounded-bl-[6px] border border-black/6 bg-white px-4 py-3 shadow-sm">
                            <span className="text-[13px] font-medium text-black/58">생각중</span>
                            <span className="flex h-4 items-end gap-1">
                              {[0, 1, 2].map((dot) => (
                                <span
                                  key={dot}
                                  className="block h-2 w-2 animate-bounce rounded-full bg-apple-blue"
                                  style={{ animationDelay: `${dot * 140}ms`, animationDuration: '860ms' }}
                                />
                              ))}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                  <div ref={messageFeedEndRef} />
                </div>
                <div className="border-t border-black/10 bg-white/90 p-3">
                  <div className="relative flex items-center gap-2 rounded-[14px] border border-black/10 bg-[#f7f8fa] p-1.5 shadow-inner">
                    {mentionRange && mentionCandidates.length > 0 && (
                      <div className="absolute bottom-[calc(100%+8px)] left-2 z-20 w-[min(360px,calc(100%-16px))] overflow-hidden rounded-[12px] border border-black/10 bg-white shadow-[0_14px_42px_rgba(0,0,0,0.16)]">
                        {mentionCandidates.map((candidate, index) => {
                          const active = index === activeMentionIndex;
                          return (
                            <button
                              key={candidate.node_id}
                              className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition ${active ? 'bg-apple-blue/10' : 'hover:bg-black/[0.04]'}`}
                              onMouseDown={(e) => {
                                e.preventDefault();
                                insertMention(candidate);
                              }}
                            >
                              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${candidate.node_type === 'user' ? 'bg-apple-blue text-white' : 'bg-black/[0.07] text-black/65'}`}>
                                {candidate.node_type === 'user' ? 'U' : 'A'}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-[13px] font-semibold text-[#1d1d1f]">{candidate.display_name}</span>
                                <span className="block text-[11px] text-black/38">{candidate.node_type} · {candidate.status}</span>
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                    <textarea
                      ref={messageInputRef}
                      className="min-h-[36px] flex-1 resize-none bg-transparent px-3 py-1.5 text-[14px] leading-5 text-black/80 outline-none placeholder:text-black/35"
                      value={messageText}
                      onChange={(e) => {
                        setMessageText(e.target.value);
                        updateMentionRange(e.target.value, e.target.selectionStart);
                      }}
                      onSelect={(e) => updateMentionRange(e.currentTarget.value, e.currentTarget.selectionStart)}
                      onKeyDown={(e) => {
                        if (mentionRange && mentionCandidates.length > 0) {
                          if (e.key === 'ArrowDown') {
                            e.preventDefault();
                            setActiveMentionIndex((index) => (index + 1) % mentionCandidates.length);
                            return;
                          }
                          if (e.key === 'ArrowUp') {
                            e.preventDefault();
                            setActiveMentionIndex((index) => (index - 1 + mentionCandidates.length) % mentionCandidates.length);
                            return;
                          }
                          if ((e.key === 'Enter' || e.key === 'Tab') && !e.nativeEvent.isComposing) {
                            e.preventDefault();
                            insertMention(mentionCandidates[activeMentionIndex]);
                            return;
                          }
                          if (e.key === 'Escape') {
                            e.preventDefault();
                            setMentionRange(null);
                            return;
                          }
                        }
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
                  <div className="flex flex-wrap items-center gap-2">
                    {detail.user_can_manage && (
                      <>
                        <button
                          className="rounded-[10px] bg-white px-3 py-1.5 text-[12px] font-semibold text-[#d70015] shadow-sm disabled:opacity-40"
                          disabled={!selectedMapEdgeId}
                          onClick={deleteSelectedTopologyEdge}
                        >
                          Delete edge
                        </button>
                        <button
                          className="rounded-[10px] bg-apple-blue px-3 py-1.5 text-[12px] font-semibold text-white shadow-sm disabled:opacity-40"
                          disabled={topologySaving || (!pendingTopologyEdges.length && !removedTopologyEdgeIds.length)}
                          onClick={() => void saveTopologyChanges()}
                        >
                          {topologySaving ? 'Saving...' : 'Save'}
                        </button>
                        {(pendingTopologyEdges.length > 0 || removedTopologyEdgeIds.length > 0) && (
                          <button
                            className="rounded-[10px] bg-white px-3 py-1.5 text-[12px] font-medium text-black/50 shadow-sm"
                            onClick={cancelTopologyChanges}
                          >
                            Cancel
                          </button>
                        )}
                      </>
                    )}
                    <p className="text-[12px] text-black/45">
                      {mapNodes.length} nodes · {mapEdges.length} edges
                      {pendingTopologyEdges.length > 0 || removedTopologyEdgeIds.length > 0
                        ? ` · +${pendingTopologyEdges.length} / -${removedTopologyEdgeIds.length}`
                        : ''}
                    </p>
                  </div>
                </div>
                <div className="h-[calc(100%-44px)] overflow-hidden rounded-[18px] border border-black/10 bg-white">
                  <ReactFlow
                    nodes={mapNodes}
                    edges={mapEdges}
                    onNodesChange={onMapNodesChange}
                    onEdgesChange={onMapEdgesChange}
                    onConnect={onTopologyConnect}
                    onNodeClick={onTopologyNodeClick}
                    onEdgeClick={onTopologyEdgeClick}
                    fitView
                    minZoom={0.25}
                    maxZoom={1.8}
                    nodesDraggable
                    nodesConnectable={detail.user_can_manage}
                    edgesFocusable
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
                        <InspectorKV label="Status" value={`${String(selectedMapEdge.data?.status || '-')}${selectedMapEdge.data?.pending ? ' · pending' : ''}`} />
                        <InspectorKV label="Source → Target" value={`${String(selectedMapEdge.data?.sourceName || selectedMapEdge.source)} → ${String(selectedMapEdge.data?.targetName || selectedMapEdge.target)}`} />
                        {detail.user_can_manage && (
                          <button
                            className="mt-2 w-full rounded-[10px] bg-[#ff453a]/15 px-3 py-2 text-[12px] font-semibold text-[#ff9f0a] hover:bg-[#ff453a]/20"
                            onClick={deleteSelectedTopologyEdge}
                          >
                            Delete selected edge
                          </button>
                        )}
                      </>
                    )}
                  </InspectorSection>
                  <InspectorSection title="Graph Relationships">
                    <div className="space-y-2">
                      {mapEdges.length === 0 ? (
                        <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                          구독 관계가 없습니다.
                        </div>
                      ) : (
                        mapEdges.slice(0, 8).map((edge) => (
                          <div key={edge.id} className="rounded-[12px] bg-white/[0.04] px-3 py-2 text-[12px] leading-5 text-white/58">
                            <span className="font-medium text-white/76">{String(edge.data?.sourceName || edge.source)}</span>
                            <span className="text-white/32"> → </span>
                            <span className="font-medium text-white/76">{String(edge.data?.targetName || edge.target)}</span>
                            <span className="ml-2 text-white/35">{String(edge.data?.status || '-')}</span>
                          </div>
                        ))
                      )}
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
                        {detail.user_can_manage && selectedAgent && (
                          <div className="mt-3 rounded-[14px] bg-white/[0.04] p-3">
                            <div className="mb-2 flex items-center justify-between gap-2">
                              <span className="text-[12px] font-semibold text-white/70">MCP Tools</span>
                              <button
                                className="rounded-[9px] bg-apple-blue px-2.5 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
                                disabled={toolSavingAgentId === selectedAgent.agent.agent_id}
                                onClick={() => void saveAgentTools(selectedAgent.agent.agent_id)}
                              >
                                {toolSavingAgentId === selectedAgent.agent.agent_id ? 'Saving' : 'Save tools'}
                              </button>
                            </div>
                            <div className="max-h-[190px] space-y-1.5 overflow-y-auto">
                              {toolCatalog.length === 0 ? (
                                <div className="rounded-[10px] bg-black/20 px-3 py-2 text-[12px] text-white/42">사용 가능한 도구가 없습니다.</div>
                              ) : (
                                toolCatalog.map((tool) => {
                                  const agentId = selectedAgent.agent.agent_id;
                                  const draftTools = agentToolDrafts[agentId] || selectedAgent.agent.tools;
                                  const checked = draftTools.includes(tool.id);
                                  return (
                                    <label key={tool.id} className={`flex cursor-pointer items-start gap-2 rounded-[10px] px-2.5 py-2 ${checked ? 'bg-apple-blue/15' : 'bg-black/16 hover:bg-white/[0.06]'}`}>
                                      <input
                                        type="checkbox"
                                        className="mt-0.5"
                                        checked={checked}
                                        onChange={() => toggleAgentToolDraft(agentId, tool.id)}
                                      />
                                      <span className="min-w-0 flex-1">
                                        <span className="block truncate text-[12px] font-medium text-white/76">{tool.name}</span>
                                        <span className="block truncate text-[11px] text-white/36">{tool.id}</span>
                                      </span>
                                    </label>
                                  );
                                })
                              )}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                    {selectedMapNode && (
                      <>
                        <InspectorKV label="Map status" value={String(selectedMapNode.data.status || '-')} />
                        <InspectorKV label="Recent node messages" value={String(selectedMapNode.data.messageCount || 0)} />
                        <InspectorKV label="Incoming subscriptions" value={String(selectedMapNode.data.incoming || 0)} />
                        <InspectorKV label="Outgoing subscriptions" value={String(selectedMapNode.data.outgoing || 0)} />
                      </>
                    )}
                  </InspectorSection>
                  {selectedMapNode && (
                    <InspectorSection title="Subscribe Node">
                      {detail.user_can_manage && selectedMapNode.data.nodeType === 'agent' ? (
                        <div className="space-y-2">
                          {selectedSubscribableNodes.map((node) => {
                            const checked = topologyEdges.some(
                              (edge) => edge.source_node_id === selectedMapNode.id && edge.target_node_id === node.node_id
                            );
                            return (
                              <label key={node.node_id} className={`flex cursor-pointer items-center gap-3 rounded-[12px] px-3 py-2 ${checked ? 'bg-apple-blue/15' : 'bg-white/[0.04] hover:bg-white/[0.07]'}`}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(event) => setTopologySubscriptionDraft(selectedMapNode.id, node.node_id, event.target.checked)}
                                />
                                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${node.node_type === 'user' ? 'bg-apple-blue text-white' : 'bg-white/10 text-white/70'}`}>
                                  {node.node_type === 'user' ? 'U' : 'A'}
                                </span>
                                <span className="min-w-0 flex-1">
                                  <span className="block truncate text-[13px] font-medium text-white/76">{node.display_name}</span>
                                  <span className="block text-[11px] text-white/38">{node.node_type} · {node.status}</span>
                                </span>
                              </label>
                            );
                          })}
                        </div>
                      ) : selectedSubscribedNodes.length === 0 ? (
                        <div className="rounded-[14px] bg-white/[0.04] p-4 text-[13px] leading-5 text-white/50">
                          현재 이 노드가 구독 중인 노드가 없습니다.
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {selectedSubscribedNodes.map(({ edge, node }) => (
                            <div key={edge.edge_id} className="flex items-center gap-3 rounded-[12px] bg-white/[0.04] px-3 py-2">
                              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${node?.node_type === 'user' ? 'bg-apple-blue text-white' : 'bg-white/10 text-white/70'}`}>
                                {node?.node_type === 'user' ? 'U' : 'A'}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-[13px] font-medium text-white/76">{node?.display_name}</span>
                                <span className="block text-[11px] text-white/38">{node?.node_type} · {edge.status}</span>
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </InspectorSection>
                  )}
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
  canManage,
  onCreateChild,
  onDelete,
  depth = 0,
}: {
  goal: Goal;
  goals: Goal[];
  selectedGoalId: string | null;
  onSelect: (goal: Goal) => void;
  canManage: boolean;
  onCreateChild: (goal: Goal) => void;
  onDelete: (goal: Goal) => void;
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
      <div
        className={`group mb-1 flex w-full items-center gap-2 rounded-[12px] py-2 pr-2 text-left transition ${selectedGoalId === goal.goal_id ? 'bg-apple-blue/20 text-white' : 'text-white/60 hover:bg-white/[0.07]'}`}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
      >
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${stateTone}`} />
        <button className="min-w-0 flex-1 text-left" onClick={() => onSelect(goal)}>
          <span className="block truncate text-[13px] font-medium">{goal.name}</span>
          <span className="block text-[11px] text-white/38">{goal.state} · {goal.progress}% · msg {goal.recent_message_count}</span>
        </button>
        {canManage && (
          <span className="flex shrink-0 items-center gap-1 opacity-70 transition group-hover:opacity-100 group-focus-within:opacity-100">
            <button
              className="rounded-[7px] bg-white/10 px-1.5 py-1 text-[11px] font-semibold text-white/60 hover:bg-apple-blue/25 hover:text-white"
              title="Sub Goal 생성"
              onClick={() => onCreateChild(goal)}
            >
              +
            </button>
            <button
              className="rounded-[7px] bg-[#ff453a]/12 px-1.5 py-1 text-[11px] font-semibold text-[#ff9f0a] hover:bg-[#ff453a]/20"
              title="Goal 삭제"
              onClick={() => onDelete(goal)}
            >
              x
            </button>
          </span>
        )}
      </div>
      {children.map((child) => (
        <GoalTreeItem
          key={child.goal_id}
          goal={child}
          goals={goals}
          selectedGoalId={selectedGoalId}
          onSelect={onSelect}
          canManage={canManage}
          onCreateChild={onCreateChild}
          onDelete={onDelete}
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
