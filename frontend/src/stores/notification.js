import { defineStore } from 'pinia'
import { notificationApi } from '../api/notifications'

export const useNotificationStore = defineStore('notification', {
  state: () => ({
    unreadCount: 0,
  }),
  actions: {
    // 只取未读数：page_size=1 的最小请求
    async refreshUnread() {
      try {
        const data = await notificationApi.list({ page: 1, pageSize: 1 })
        this.unreadCount = data.unread_count
      } catch {
        // 静默失败（拦截器已提示），不打断页面
      }
    },
  },
})
