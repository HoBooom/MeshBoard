/**
 * MeshBoard — Dashboard Layout
 *
 * 사이드바 + 상단 바 + 메인 콘텐츠 레이아웃.
 * 역할별 네비게이션 메뉴를 동적으로 생성합니다.
 */

import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
  roles?: string[];
}

const navItems: NavItem[] = [
  {
    label: '홈',
    path: '/dashboard',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
  },
  {
    label: '워크스페이스',
    path: '/dashboard/workspaces',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
  {
    label: '크리에이터',
    path: '/dashboard/creator',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
      </svg>
    ),
    roles: ['agent_owner', 'agent_engineer', 'trust_ops', 'release_manager'],
  },
  {
    label: '신뢰 관리',
    path: '/dashboard/trust',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    ),
    roles: ['governance', 'trust_ops', 'agent_owner', 'agent_engineer'],
  },
  {
    label: '운영 관리',
    path: '/dashboard/operator',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    roles: ['trust_ops', 'release_manager', 'agent_owner', 'agent_engineer'],
  },
];

// 역할 한글 매핑
const roleLabels: Record<string, string> = {
  agent_owner: '에이전트 소유자',
  agent_engineer: '에이전트 엔지니어',
  trust_ops: '신뢰 운영',
  governance: '거버넌스',
  evaluator: '평가자',
  ethics_liaison: '윤리 담당',
  release_manager: '릴리스 관리자',
};

export default function DashboardLayout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.localStorage.getItem('meshboard.sidebarCollapsed') === 'true';
  });

  useEffect(() => {
    window.localStorage.setItem('meshboard.sidebarCollapsed', String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  // 사용자 역할에 맞는 네비게이션 필터링
  const filteredNavItems = navItems.filter((item) => {
    if (!item.roles) return true;
    return user?.roles.some((role) => item.roles!.includes(role));
  });

  return (
    <div className="min-h-screen bg-apple-dark flex font-apple text-white">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarCollapsed ? 'w-20' : 'w-72'
        } bg-[#141414]/80 backdrop-blur-[20px] border-r border-white/5 flex flex-col transition-[width] duration-300 ease-out fixed h-full z-30`}
        aria-label="대시보드 사이드바"
      >
        {/* Logo */}
        <div className={`${sidebarCollapsed ? 'px-4' : 'px-6'} h-[88px] border-b border-white/5 flex items-center gap-3 transition-all duration-300`}>
          <div className="w-10 h-10 rounded-[12px] bg-apple-surface1 flex items-center justify-center flex-shrink-0">
            <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
            </svg>
          </div>
          {!sidebarCollapsed && (
            <div className="animate-fade-in">
              <h1 className="text-[17px] font-semibold text-white tracking-[-0.374px]">MeshBoard</h1>
              <p className="text-[12px] text-white/50 tracking-[-0.12px]">Agent Mesh Platform</p>
            </div>
          )}
          <button
            type="button"
            onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
            className={`ml-auto w-8 h-8 rounded-[8px] flex items-center justify-center text-white/50 hover:text-white hover:bg-white/10 transition-colors ${
              sidebarCollapsed ? 'hidden' : ''
            }`}
            aria-label="사이드바 접기"
            aria-expanded={!sidebarCollapsed}
            aria-controls="dashboard-sidebar-nav"
            title="사이드바 접기"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        </div>

        {/* Navigation */}
        <nav id="dashboard-sidebar-nav" className="flex-1 p-4 space-y-1 overflow-y-auto">
          {filteredNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/dashboard'}
              aria-label={item.label}
              title={sidebarCollapsed ? item.label : undefined}
              className={({ isActive }) =>
                `${isActive ? 'sidebar-item-active' : 'sidebar-item'} ${
                  sidebarCollapsed ? 'h-12 justify-center px-0' : ''
                }`
              }
            >
              <span className="flex-shrink-0">{item.icon}</span>
              {!sidebarCollapsed && <span className="text-sm whitespace-nowrap">{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Collapse Toggle */}
        <button
          type="button"
          onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
          className={`h-14 border-t border-white/5 text-white/50 hover:text-white hover:bg-white/5 transition-colors flex items-center ${
            sidebarCollapsed ? 'justify-center' : 'justify-start gap-3 px-4'
          }`}
          id="sidebar-toggle"
          aria-label={sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'}
          aria-expanded={!sidebarCollapsed}
          aria-controls="dashboard-sidebar-nav"
          title={sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'}
        >
          <svg
            className={`w-5 h-5 transition-transform duration-300 ${sidebarCollapsed ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
          {!sidebarCollapsed && <span className="text-[13px] tracking-[-0.13px]">사이드바 접기</span>}
        </button>

        {/* User Info */}
        {user && (
          <div className="p-4 border-t border-white/5">
            <div className={`flex items-center ${sidebarCollapsed ? 'justify-center' : 'gap-3'}`}>
              <div className="w-9 h-9 rounded-full bg-apple-surface2 flex items-center justify-center flex-shrink-0">
                <span className="text-white text-[14px] font-semibold">
                  {user.name.charAt(0)}
                </span>
              </div>
              {!sidebarCollapsed && (
                <div className="flex-1 min-w-0 animate-fade-in">
                  <p className="text-[14px] font-medium text-white truncate tracking-[-0.224px]">{user.name}</p>
                  <p className="text-[12px] text-white/50 truncate tracking-[-0.12px]">
                    {user.roles.map((r) => roleLabels[r] || r).join(', ')}
                  </p>
                </div>
              )}
            </div>
            {!sidebarCollapsed && (
              <button
                onClick={handleLogout}
                className="mt-3 w-full text-[12px] text-white/50 hover:text-[#ff3b30] transition-colors py-2 rounded-[8px] hover:bg-[#ff3b30]/10 tracking-[-0.12px]"
                id="logout-btn"
              >
                로그아웃
              </button>
            )}
          </div>
        )}
      </aside>

      {/* Main Content */}
      <main className={`flex-1 min-w-0 ${sidebarCollapsed ? 'ml-20' : 'ml-72'} transition-[margin-left] duration-300 ease-out`}>
        {/* Top Bar - Apple Navigation Glass */}
        <header className="h-[48px] bg-black/80 backdrop-blur-[20px] backdrop-saturate-[180%] flex items-center px-8 sticky top-0 z-20">
          <div className="flex-1" />
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-[12px] text-white/80 font-medium tracking-[-0.12px]">{user?.name}</p>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <div className="p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
