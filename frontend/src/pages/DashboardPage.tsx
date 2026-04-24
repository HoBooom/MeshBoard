/**
 * MeshBoard — Dashboard Home Page
 *
 * 역할에 따라 다른 위젯/카드를 표시하는 홈 대시보드.
 */

import { useEffect, useState } from 'react';
import { useAuthStore } from '../stores/authStore';
import { noticesApi, Notice } from '../api/notices';

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

interface StatCard {
  label: string;
  value: string;
  change: string;
  icon: React.ReactNode;
  trend: 'up' | 'down' | 'neutral';
}

export default function DashboardPage() {
  const { user, fetchUser } = useAuthStore();
  const [notices, setNotices] = useState<Notice[]>([]);

  useEffect(() => {
    if (!user) {
      fetchUser();
    } else {
      noticesApi.getNotices().then(setNotices).catch(console.error);
    }
  }, [user, fetchUser]);

  // 역할별 통계 카드 (초기에는 Mock 데이터)
  const statsCards: StatCard[] = [
    {
      label: '등록된 에이전트',
      value: '—',
      change: 'Phase 2에서 활성화',
      trend: 'neutral',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      ),
    },
    {
      label: '활성 워크스페이스',
      value: '—',
      change: 'Phase 3에서 활성화',
      trend: 'neutral',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
    },
    {
      label: '오늘 상호작용',
      value: '—',
      change: 'Phase 3에서 활성화',
      trend: 'neutral',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      ),
    },
    {
      label: '적용 정책',
      value: '—',
      change: 'Phase 3에서 활성화',
      trend: 'neutral',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
      ),
    },
  ];

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Welcome Header - Apple Style */}
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

      {/* Notices Section - Apple Style */}
      {notices.length > 0 && (
        <div className="font-apple space-y-4 mb-12">
          {notices.map((notice) => (
            <div key={notice.notice_id} className="bg-apple-surface1 rounded-[12px] p-6 text-white shadow-[0_5px_30px_rgba(0,0,0,0.22)]">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-[21px] font-semibold tracking-[0.231px] leading-[1.19]">
                  {notice.title}
                </h3>
                <span className="text-[12px] font-medium text-white/50 tracking-[-0.12px]">
                  {new Date(notice.created_at).toLocaleDateString('ko-KR')}
                </span>
              </div>
              {notice.body && (
                <p className="text-[17px] font-normal text-white/80 tracking-[-0.374px] leading-[1.47] mt-3">
                  {notice.body}
                </p>
              )}
              <div className="mt-5">
                <a href="#" className="inline-flex items-center text-[14px] text-apple-link hover:underline tracking-[-0.224px]">
                  자세히 알아보기 <span className="ml-1 text-[10px]">❯</span>
                </a>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
        {statsCards.map((card, index) => (
          <div
            key={card.label}
            className="glass-card p-6"
            style={{ animationDelay: `${index * 100}ms` }}
          >
            <div className="flex items-start justify-between mb-4">
              <div className="w-12 h-12 rounded-[12px] bg-apple-surface2 flex items-center justify-center text-apple-blue">
                {card.icon}
              </div>
            </div>
            <p className="text-[28px] font-semibold text-white mb-1 tracking-[0.196px] leading-[1.14]">{card.value}</p>
            <p className="text-[14px] text-white/50 tracking-[-0.224px]">{card.label}</p>
            <p className="text-[12px] text-white/30 mt-2 tracking-[-0.12px]">{card.change}</p>
          </div>
        ))}
      </div>

      {/* Quick Actions based on role */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
        {/* System Status */}
        <div className="glass-card p-6">
          <h3 className="text-[21px] font-semibold text-white mb-4 flex items-center gap-2 tracking-[0.231px]">
            <div className="w-2 h-2 rounded-[50%] bg-[#34c759] animate-pulse" />
            시스템 상태
          </h3>
          <div className="space-y-3">
            {[
              { name: 'API 서버', status: 'online', detail: 'FastAPI v0.1.0' },
              { name: 'PostgreSQL', status: 'online', detail: 'pgvector/pg15' },
              { name: '메시지 브로커', status: 'pending', detail: 'Phase 3에서 구현 예정' },
              { name: 'Agent Runtime', status: 'pending', detail: 'Phase 3에서 구현 예정' },
            ].map((service) => (
              <div key={service.name} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-[50%] ${
                    service.status === 'online' ? 'bg-[#34c759]' : 'bg-white/20'
                  }`} />
                  <span className="text-[14px] font-medium text-white/80 tracking-[-0.224px]">{service.name}</span>
                </div>
                <span className="text-[12px] text-white/50 tracking-[-0.12px]">{service.detail}</span>
              </div>
            ))}
          </div>
        </div>

        {/* User Info Card */}
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

      {/* Coming Soon */}
      <div className="glass-card p-10 text-center mt-8">
        <div className="w-16 h-16 mx-auto mb-4 rounded-[12px] bg-apple-surface2 flex items-center justify-center">
          <svg className="w-8 h-8 text-apple-blue" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <h3 className="text-[21px] font-semibold text-white tracking-[0.231px] mb-2">더 많은 기능이 곧 추가됩니다</h3>
        <p className="text-[17px] font-normal text-white/50 tracking-[-0.374px] leading-[1.47] max-w-lg mx-auto">
          공지 시스템, 마켓플레이스, 에이전트 크리에이터, 토폴로지 맵 등
          다양한 기능이 Phase별로 구현될 예정입니다.
        </p>
      </div>
    </div>
  );
}
