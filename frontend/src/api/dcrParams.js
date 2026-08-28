import http from './http'

export const dcrParamsApi = {
  current() {
    return http.get('/dcr-params/current')
  },

  defaults() {
    return http.get('/dcr-params/default')
  },

  parse(file) {
    const form = new FormData()
    form.append('file', file)
    return http.post('/dcr-params/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  save(document, expectedSha256, sourceTaskId = null) {
    const body = {
      document,
      expected_sha256: expectedSha256,
    }
    if (sourceTaskId !== null && sourceTaskId !== undefined && sourceTaskId !== '') {
      body.source_task_id = sourceTaskId
    }
    return http.put('/dcr-params/current', body, { silent: true })
  },

  versions(params = {}) {
    return http.get('/dcr-params/versions', { params })
  },

  version(taskId) {
    return http.get(`/dcr-params/versions/${encodeURIComponent(taskId)}`)
  },

  downloadCurrent() {
    return http.get('/dcr-params/current/file', {
      responseType: 'blob',
      headers: { Accept: 'application/octet-stream' },
    })
  },
}
