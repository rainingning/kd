import http from './http'

export const notificationApi = {
  list: ({ unreadOnly, page, pageSize } = {}) =>
    http.get('/notifications', {
      params: {
        unread_only: unreadOnly || false,
        page,
        page_size: pageSize,
      },
    }),
  // ids 为 null 表示全部标记已读
  markRead: (ids = null) => http.post('/notifications/read', { ids }),
}
