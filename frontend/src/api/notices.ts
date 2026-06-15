import client from './client';

export type NoticeCategory =
  | 'general'
  | 'system'
  | 'city'
  | 'governance'
  | 'release'
  | 'security';

export type NoticePriority = 'normal' | 'high' | 'critical';

export interface Notice {
  notice_id: string;
  title: string;
  body: string | null;
  target_role: string;
  is_active: boolean;
  category: NoticeCategory;
  priority: NoticePriority;
  pinned: boolean;
  created_at: string;
  expires_at: string | null;
}

export const noticesApi = {
  getNotices: async () => {
    const response = await client.get<Notice[]>('/notices/');
    return response.data;
  },
};
