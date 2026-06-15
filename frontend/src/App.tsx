/**
 * MeshBoard — App Router
 *
 * 로그인 → 역할 기반 대시보드 라우팅.
 */

import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import CreatorPage from './pages/CreatorPage';
import WorkspacePage from './pages/WorkspacePage';
import TrustPage from './pages/TrustPage';
import OperationsPage from './pages/OperationsPage';
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
        <Route path="workspaces" element={<WorkspacePage />} />
        <Route path="marketplace" element={<Navigate to="/dashboard/workspaces" replace />} />
        <Route path="creator" element={<CreatorPage />} />
        <Route path="trust" element={<TrustPage />} />
        <Route path="operator" element={<OperationsPage />} />
      </Route>

      {/* Redirect root to dashboard */}
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
