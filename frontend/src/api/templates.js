import http from './http'

export const templateApi = {
  list: (programKey = 'dcr_3d') => http.get('/templates', { params: { program_key: programKey } }),
  create: (name, params, programKey = 'dcr_3d') => http.post('/templates', {
    name,
    params,
    program_key: programKey,
  }),
  update: (id, data) => http.put(`/templates/${id}`, data),
  remove: (id) => http.delete(`/templates/${id}`),
}
