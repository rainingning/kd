import http from './http'

export const adminApi = {
  dashboard: () => http.get('/admin/dashboard'),
  runningTasks: () => http.get('/admin/tasks/running'),
  queuedTasks: () => http.get('/admin/tasks/queued'),
  killTask: (id) => http.post(`/admin/tasks/${id}/kill`),
  users: ({ keyword, page, pageSize } = {}) =>
    http.get('/admin/users', {
      params: { keyword: keyword || undefined, page, page_size: pageSize },
    }),
  createUser: (data) => http.post('/admin/users', data),
  updateUser: (id, data) => http.put(`/admin/users/${id}`, data),
  deleteUser: (id) => http.delete(`/admin/users/${id}`),
  resetUserPassword: (id) => http.post(`/admin/users/${id}/reset-password`),
  disableUser: (id) => http.post(`/admin/users/${id}/disable`),
  enableUser: (id) => http.post(`/admin/users/${id}/enable`),
  programTemplate: () => http.get('/admin/program-template'),
  programSyncStatus: () => http.get('/admin/program-sync/status'),
  syncAllPrograms: () => http.post('/admin/program-sync'),
  syncUserProgram: (id) => http.post(`/admin/users/${id}/program-sync`),
  checkUserWorkspace: (id) => http.post(`/admin/users/${id}/workspace-check`),
  archiveFailures: () => http.get('/admin/tasks/archive-failures'),
  retryArchive: (id) => http.post(`/admin/tasks/${id}/archive-retry`),
  getConfig: () => http.get('/admin/config'),
  updateConfig: (config) => http.put('/admin/config', { config }),
  auditLogs: ({ action, page, pageSize } = {}) =>
    http.get('/admin/audit-logs', {
      params: { action: action || undefined, page, page_size: pageSize },
    }),
}
