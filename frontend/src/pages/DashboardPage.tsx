/**
 * MeshBoard — Dashboard Home Page
 *
 * 홈 대시보드: 도시 전력 관리 시스템 운영 공지 + 사내 공지 피드,
 * 실시간 운영/신뢰 지표, 시스템 상태를 한눈에 제공합니다.
 */

import { useEffect, useState } from 'react';
import { useAuthStore } from '../stores/authStore';
import { noticesApi, Notice, NoticeCategory, NoticePriority } from '../api/notices';
import { operationsApi, OperationsOverview, HealthComponent } from '../api/operations';
import { trustApi, TrustOverview } from '../api/trust';

const roleLabels: Record<string, string> = {
  agent_owner: '에이전트 소유자',
  agent_engineer: '에이전트 엔지니어',
  trust_ops: '신뢰 운영',
  governance: '거버넌스',
  evaluator: '평가자',
  ethics_liaison: '윤리 담당',
  release_manager: '릴리스 관리자',
};

const roleBadgeColors: Record<string, string> = {
  agent_owner: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  agent_engineer: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  trust_ops: 'bg-green-500/20 text-green-400 border-green-500/30',
  governance: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  evaluator: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  ethics_liaison: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  release_manager: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
};

const categoryMeta: Record<NoticeCategory, { label: string; cls: string }> = {
  city: { label: '도시운영', cls: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
  system: { label: '시스템', cls: 'bg-slate-400/15 text-slate-300 border-slate-400/25' },
  governance: { label: '거버넌스', cls: 'bg-purple-500/15 text-purple-300 border-purple-500/30' },
  release: { label: '릴리스', cls: 'bg-teal-500/15 text-teal-300 border-teal-500/30' },
  security: { label: '보안', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  general: { label: '일반', cls: 'bg-white/10 text-white/60 border-white/15' },
};

const priorityMeta: Record<NoticePriority, { label: string; dot: string } | null> = {
  critical: { label: '긴급', dot: 'bg-[#ff453a]' },
  high: { label: '중요', dot: 'bg-amber-400' },
  normal: null,
};

function PinIcon() {
  return (
    <svg className="w-3.5 h-3.5 text-apple-link" fill="currentColor" viewBox="0 0 24 24">
      <path d="M16 9V4h1a1 1 0 100-2H7a1 1 0 000 2h1v5a3 3 0 01-3 3v1h5.5v6l1 1 1-1v-6H19v-1a3 3 0 01-3-3z" />
    </svg>
  );
}

export default function DashboardPage() {
  const { user, fetchUser } = useAuthStore();
  const [notices, setNotices] = useState<Notice[]>([]);
  const [ops, setOps] = useState<OperationsOverview | null>(null);
  const [trust, setTrust] = useState<TrustOverview | null>(null);
  const [health, setHealth] = useState<HealthComponent[]>([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!user) {
      fetchUser();
      return;
    }
    noticesApi.getNotices().then(setNotices).catch(console.error);
    operationsApi.getOverview().then(setOps).catch(console.error);
    operationsApi.getHealth().then(setHealth).catch(console.error);
    trustApi.getOverview().then(setTrust).catch(console.error);
  }, [user, fetchUser]);

  const visibleNotices = expanded ? notices : notices.slice(0, 4);

  const statsCards = [
    {
      label: '등록된 에이전트',
      value: ops ? String(ops.total_agents) : '—',
      change: ops ? `운영 중 ${ops.status_breakdown.ACTIVE} · 초안 ${ops.status_breakdown.DRAFT}` : '집계 중',
    },
    {
      label: '인증 완료 에이전트',
      value: trust ? String(trust.certified_agents) : '—',
      change: trust ? `심사 대기 ${trust.pending_certifications}건` : '집계 중',
    },
    {
      label: '24시간 실행',
      value: ops ? String(ops.interactions_24h) : '—',
      change: ops ? `실행 성공률 ${ops.success_rate}%` : '집계 중',
    },
    {
      label: '활성 정책',
      value: trust ? String(trust.active_policies) : '—',
      change: trust ? `초안 ${trust.draft_policies}건` : '집계 중',
    },
  ];

  const healthDot: Record<string, string> = {
    online: 'bg-[#34c759]',
    degraded: 'bg-amber-400',
    offline: 'bg-[#ff3b30]',
  };

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Welcome Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between font-apple pb-8 border-b border-surface-800">
        <div>
          <h1 className="text-[40px] md:text-[56px] font-semibold text-white tracking-[-0.28px] leading-[1.07] mb-2">
            안녕하세요, {user?.name ?? '...'}님.
          </h1>
          <p className="text-[21px] font-normal text-white/80 tracking-[0.231px] leading-[1.19]">
            MeshBoard 대시보드에 오신 것을 환영합니다.
          </p>
        </div>
        <div className="flex items-center gap-2 mt-4 md:mt-0">
          {user?.roles.map((role) => (
            <span
              key={role}
              className={`px-3 py-1 text-xs font-medium rounded-full border ${
                roleBadgeColors[role] || 'bg-surface-700 text-surface-300 border-surface-600'
              }`}
            >
              {roleLabels[role] || role}
            </span>
          ))}
        </div>
      </div>

      {/* Notices Section */}
      {notices.length > 0 && (
        <div className="font-apple">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[24px] font-semibold text-white tracking-[0.231px] flex items-center gap-2">
              공지사항
              <span className="text-[14px] font-normal text-white/40">{notices.length}건</span>
            </h2>
          </div>
          <div className="space-y-3">
            {visibleNotices.map((notice) => {
              const cat = categoryMeta[notice.category] ?? categoryMeta.general;
              const prio = priorityMeta[notice.priority];
              return (
                <div
                  key={notice.notice_id}
                  className={`bg-apple-surface1 rounded-[12px] p-5 text-white shadow-[0_5px_30px_rgba(0,0,0,0.22)] border-l-2 ${
                    notice.priority === 'critical'
                      ? 'border-[#ff453a]'
                      : notice.priority === 'high'
                      ? 'border-amber-400'
                      : 'border-transparent'
                  }`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap mb-1.5">
                        {notice.pinned && <PinIcon />}
                        <span className={`px-2 py-0.5 text-[11px] font-medium rounded-md border ${cat.cls}`}>
                          {cat.label}
                        </span>
                        {prio && (
                          <span className="flex items-center gap-1 text-[11px] font-medium text-white/70">
                            <span className={`w-1.5 h-1.5 rounded-full ${prio.dot}`} />
                            {prio.label}
                          </span>
                        )}
                      </div>
                      <h3 className="text-[17px] font-semibold tracking-[-0.2px] leading-[1.3]">
                        {notice.title}
                      </h3>
                      {notice.body && (
                        <p className="text-[14px] font-normal text-white/60 tracking-[-0.2px] leading-[1.55] mt-2">
                          {notice.body}
                        </p>
                      )}
                    </div>
                    <span className="text-[12px] font-medium text-white/40 tracking-[-0.12px] whitespace-nowrap flex-shrink-0">
                      {new Date(notice.created_at).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          {notices.length > 4 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-4 text-[14px] text-apple-link hover:underline tracking-[-0.224px]"
            >
              {expanded ? '접기' : `공지 ${notices.length - 4}건 더 보기`}
            </button>
          )}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
        {statsCards.map((card) => (
          <div key={card.label} className="glass-card p-6">
            <p className="text-[28px] font-semibold text-white mb-1 tracking-[0.196px] leading-[1.14]">{card.value}</p>
            <p className="text-[14px] text-white/50 tracking-[-0.224px]">{card.label}</p>
            <p className="text-[12px] text-white/30 mt-2 tracking-[-0.12px]">{card.change}</p>
          </div>
        ))}
      </div>

      {/* System Status + User Info */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
        <div className="glass-card p-6">
          <h3 className="text-[21px] font-semibold text-white mb-4 flex items-center gap-2 tracking-[0.231px]">
            <div className="w-2 h-2 rounded-[50%] bg-[#34c759] animate-pulse" />
            시스템 상태
          </h3>
          <div className="space-y-3">
            {(health.length > 0
              ? health
              : [{ name: 'API 서버', status: 'online', detail: 'FastAPI v0.1.0' }]
            ).map((service) => (
              <div key={service.name} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-[50%] ${healthDot[service.status] ?? 'bg-white/20'}`} />
                  <span className="text-[14px] font-medium text-white/80 tracking-[-0.224px]">{service.name}</span>
                </div>
                <span className="text-[12px] text-white/50 tracking-[-0.12px]">{service.detail}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card p-6">
          <h3 className="text-[21px] font-semibold text-white tracking-[0.231px] mb-4">내 정보</h3>
          {user && (
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-[12px] bg-apple-surface2 flex items-center justify-center">
                  <span className="text-[28px] font-semibold text-white tracking-[0.196px] leading-[1.14]">{user.name.charAt(0)}</span>
                </div>
                <div>
                  <p className="text-[21px] font-semibold text-white tracking-[0.231px] leading-[1.19]">{user.name}</p>
                  <p className="text-[14px] text-white/50 tracking-[-0.224px] mt-1">{user.email}</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4 pt-4 border-t border-white/5">
                <div>
                  <p className="text-[12px] text-white/50 tracking-[-0.12px]">로그인 ID</p>
                  <p className="text-[14px] font-medium text-white/80 tracking-[-0.224px] mt-1">{user.login_id}</p>
                </div>
                <div>
                  <p className="text-[12px] text-white/50 tracking-[-0.12px]">계정 상태</p>
                  <p className="text-[14px] font-medium text-[#34c759] tracking-[-0.224px] mt-1">{user.state}</p>
                </div>
                <div>
                  <p className="text-[12px] text-white/50 tracking-[-0.12px]">가입일</p>
                  <p className="text-[14px] font-medium text-white/80 tracking-[-0.224px] mt-1">
                    {new Date(user.created_at).toLocaleDateString('ko-KR')}
                  </p>
                </div>
                <div>
                  <p className="text-[12px] text-white/50 tracking-[-0.12px]">마지막 로그인</p>
                  <p className="text-[14px] font-medium text-white/80 tracking-[-0.224px] mt-1">
                    {user.last_login ? new Date(user.last_login).toLocaleString('ko-KR') : '—'}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
