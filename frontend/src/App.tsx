/**
 * MeshBoard — App Router
 *
 * 로그인 → 역할 기반 대시보드 라우팅.
 */

import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from './layouts/DashboardLayout';
import ProtectedRoute from './components/ProtectedRoute';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const CreatorPage = lazy(() => import('./pages/CreatorPage'));
const WorkspacePage = lazy(() => import('./pages/WorkspacePage'));
const TrustPage = lazy(() => import('./pages/TrustPage'));
const OperationsPage = lazy(() => import('./pages/OperationsPage'));
const SandboxPage = lazy(() => import('./pages/SandboxPage'));
const MarketplacePage = lazy(() => import('./pages/MarketplacePage'));

function RouteFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f5f5f7] text-sm text-black/55">
      MeshBoard를 불러오는 중입니다…
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
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
          <Route path="workspaces" element={<WorkspacePage />} />
          <Route path="marketplace" element={<MarketplacePage />} />
          <Route path="creator" element={<CreatorPage />} />
          <Route path="sandbox" element={<SandboxPage />} />
          <Route path="trust" element={<TrustPage />} />
          <Route path="operator" element={<OperationsPage />} />
        </Route>

        {/* Redirect root to dashboard */}
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Suspense>
  );
}
