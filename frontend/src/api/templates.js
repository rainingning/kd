import http from './http'

export const templateApi = {
  list: () => http.get('/templates'),
  create: (name, params) => http.post('/templates', { name, params }),
  update: (id, data) => http.put(`/templates/${id}`, data),
  remove: (id) => http.delete(`/templates/${id}`),
}
