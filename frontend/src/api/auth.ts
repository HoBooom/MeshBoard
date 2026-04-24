/**
 * MeshBoard — Auth API Functions
 */

import client from './client';

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  name: string;
  email: string;
  login_id: string;
  password: string;
  roles: string[];
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserResponse {
  user_id: string;
  name: string;
  email: string;
  login_id: string;
  state: string;
  roles: string[];
  created_at: string;
  last_login: string | null;
}

export const authApi = {
  /** 로그인 → JWT 토큰 발급 */
  login: (data: LoginRequest) =>
    client.post<TokenResponse>('/auth/login', data),

  /** 사용자 등록 */
  register: (data: RegisterRequest) =>
    client.post<UserResponse>('/auth/register', data),

  /** 현재 사용자 정보 조회 */
  getMe: () =>
    client.get<UserResponse>('/auth/me'),

  /** 토큰 갱신 */
  refresh: (refreshToken: string) =>
    client.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken }),
};
