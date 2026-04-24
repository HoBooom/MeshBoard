import client from './client';

export interface Notice {
  notice_id: string;
  title: string;
  body: string | null;
  target_role: string;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
}

export const noticesApi = {
  getNotices: async () => {
    const response = await client.get<Notice[]>('/notices/');
    return response.data;
  },
};
