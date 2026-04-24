/**
 * MeshBoard — Login Page
 *
 * 기업 느낌의 프리미엄 로그인 페이지.
 * 이메일/비밀번호 인증 후 역할에 맞는 대시보드로 리다이렉트.
 */

import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const { login, isLoading, error, clearError, isAuthenticated } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/dashboard';

  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch {
      // error is handled by the store
    }
  };

  return (
    <div className="min-h-screen bg-apple-dark flex font-apple text-white">
      {/* Left: Branding Panel */}
      <div className="hidden lg:flex lg:w-1/2 xl:w-3/5 flex-col justify-between p-12 relative overflow-hidden">

        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-[12px] bg-apple-surface1 flex items-center justify-center">
              <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
              </svg>
            </div>
            <span className="text-[21px] font-semibold text-white tracking-[0.231px]">MeshBoard</span>
          </div>
        </div>

        <div className="relative z-10 max-w-lg mt-24">
          <h1 className="text-[56px] font-semibold text-white leading-[1.07] tracking-[-0.28px] mb-6">
            AI 에이전트 메시를<br />
            하나의 대시보드에서<br />
            관리하세요.
          </h1>
          <p className="text-[21px] font-normal text-white/80 leading-[1.19] tracking-[0.231px]">
            수천 개의 헤드리스 AI 에이전트를 발견, 관리, 운영하는 통합 플랫폼.
            투명한 의사결정 추적과 역할 기반 거버넌스를 제공합니다.
          </p>
        </div>

        {/* Feature highlights */}
        <div className="relative z-10 flex gap-8">
          {[
            { label: '역할 기반 제어', value: 'RBAC' },
            { label: 'A2A 통신 추적', value: 'Trace' },
            { label: '실시간 모니터링', value: 'Live' },
          ].map((item) => (
            <div key={item.value} className="bg-apple-surface1 rounded-[12px] px-5 py-3 shadow-[0_5px_30px_rgba(0,0,0,0.22)]">
              <p className="text-[12px] text-white/50 tracking-[-0.12px]">{item.label}</p>
              <p className="text-[17px] font-semibold text-white tracking-[-0.374px]">{item.value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Right: Login Form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-apple-dark">
        <div className="w-full max-w-md animate-slide-up">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-3 mb-10">
            <div className="w-10 h-10 rounded-[12px] bg-apple-surface1 flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
              </svg>
            </div>
            <span className="text-[21px] font-semibold text-white tracking-[0.231px]">MeshBoard</span>
          </div>

          <div className="bg-apple-surface1 rounded-[12px] p-8 xl:p-10 shadow-[0_5px_30px_rgba(0,0,0,0.22)]">
            <div className="mb-8">
              <h2 className="text-[28px] font-semibold text-white mb-2 tracking-[0.196px] leading-[1.14]">로그인</h2>
              <p className="text-[14px] text-white/50 tracking-[-0.224px] leading-[1.43]">MeshBoard 계정으로 로그인하세요</p>
            </div>

            {/* Error message */}
            {error && (
              <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm flex items-center gap-3 animate-fade-in">
                <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="email" className="block text-[14px] font-medium text-white/80 tracking-[-0.224px] mb-2">
                  이메일
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  required
                  className="input-field"
                  autoComplete="email"
                />
              </div>

              <div>
                <label htmlFor="password" className="block text-[14px] font-medium text-white/80 tracking-[-0.224px] mb-2">
                  비밀번호
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    className="input-field pr-12"
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-surface-400 hover:text-surface-200 transition-colors"
                    id="toggle-password"
                  >
                    {showPassword ? (
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                      </svg>
                    ) : (
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="btn-primary w-full flex items-center justify-center gap-2"
                id="login-submit"
              >
                {isLoading ? (
                  <>
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    로그인 중...
                  </>
                ) : (
                  '로그인'
                )}
              </button>
            </form>

            {/* Demo accounts */}
            <div className="mt-8 pt-6 border-t border-white/10">
              <p className="text-[12px] text-white/50 tracking-[-0.12px] mb-3">데모 계정</p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: '관리자', email: 'admin@meshboard.io', pw: 'admin1234' },
                  { label: '개발자', email: 'dev@meshboard.io', pw: 'dev1234' },
                  { label: '운영자', email: 'ops@meshboard.io', pw: 'ops1234' },
                  { label: '평가자', email: 'user@meshboard.io', pw: 'user1234' },
                ].map((demo) => (
                  <button
                    key={demo.email}
                    type="button"
                    onClick={() => {
                      setEmail(demo.email);
                      setPassword(demo.pw);
                    }}
                    className="text-[12px] font-medium tracking-[-0.12px] py-[8px] px-[12px] rounded-[8px] bg-apple-surface2 text-white/80 hover:bg-white/10 hover:text-white transition-all"
                  >
                    {demo.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
