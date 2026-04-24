/**
 * MeshBoard — ProtectedRoute Component
 *
 * 인증되지 않은 사용자 → 로그인 페이지 리다이렉트
 * 권한 없는 역할 → 403 페이지
 */

import { useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRoles?: string[];
}

export default function ProtectedRoute({ children, requiredRoles }: ProtectedRouteProps) {
  const { isAuthenticated, user, isLoading, fetchUser } = useAuthStore();
  const location = useLocation();

  useEffect(() => {
    if (isAuthenticated && !user) {
      fetchUser();
    }
  }, [isAuthenticated, user, fetchUser]);

  // 로딩 중
  if (isLoading) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-primary-500/30 border-t-primary-500 rounded-full animate-spin" />
          <p className="text-surface-400 text-sm">로딩 중...</p>
        </div>
      </div>
    );
  }

  // 미인증 → 로그인
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // 역할 검증
  if (requiredRoles && user) {
    const hasRole = requiredRoles.some((role) => user.roles.includes(role));
    if (!hasRole) {
      return (
        <div className="min-h-screen bg-surface-950 flex items-center justify-center mesh-bg">
          <div className="glass-card p-12 text-center max-w-md animate-fade-in">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-red-500/20 flex items-center justify-center">
              <svg className="w-8 h-8 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-white mb-2">접근 권한 없음</h2>
            <p className="text-surface-400 mb-6">
              이 페이지에 접근하려면 다음 역할 중 하나가 필요합니다:
              <span className="block mt-2 text-primary-400 font-medium">
                {requiredRoles.join(', ')}
              </span>
            </p>
            <button
              onClick={() => window.history.back()}
              className="btn-secondary"
            >
              뒤로 가기
            </button>
          </div>
        </div>
      );
    }
  }

  return <>{children}</>;
}
