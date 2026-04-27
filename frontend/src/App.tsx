/**
 * MeshBoard — App Router
 *
 * 로그인 → 역할 기반 대시보드 라우팅.
 */

import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import MarketplacePage from './pages/MarketplacePage';
import CreatorPage from './pages/CreatorPage';
import DashboardLayout from './layouts/DashboardLayout';
import ProtectedRoute from './components/ProtectedRoute';

export default function App() {
  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/login" element={<LoginPage />} />

      {/* Protected Routes */}
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        {/* 향후 추가 라우트 */}
        <Route path="marketplace" element={<MarketplacePage />} />
        <Route path="creator" element={<CreatorPage />} />
        <Route path="trust" element={<PlaceholderPage title="신뢰 워크벤치" />} />
        <Route path="operator" element={<PlaceholderPage title="운영 관리" />} />
      </Route>

      {/* Redirect root to dashboard */}
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

/**
 * 향후 구현될 페이지를 위한 플레이스홀더.
 */
function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="flex items-center justify-center h-[60vh] font-apple">
      <div className="bg-apple-surface1 p-12 text-center rounded-[16px] shadow-[0_5px_30px_rgba(0,0,0,0.22)] animate-fade-in border border-white/5">
        <div className="w-16 h-16 mx-auto mb-6 rounded-[12px] bg-apple-surface2 flex items-center justify-center">
          <svg className="w-8 h-8 text-apple-blue" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
          </svg>
        </div>
        <h2 className="text-[21px] font-semibold text-white tracking-[0.231px] mb-2">{title}</h2>
        <p className="text-[14px] text-white/50 tracking-[-0.224px]">이 기능은 다음 Phase에서 구현될 예정입니다.</p>
      </div>
    </div>
  );
}
