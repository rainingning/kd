import http from './http'

function base(programKey, sourceType) {
  return `/program-params/${encodeURIComponent(programKey)}/${encodeURIComponent(sourceType)}`
}

export const programParamsApi = {
  current(programKey, sourceType) {
    return http.get(`${base(programKey, sourceType)}/current`)
  },

  defaults(programKey, sourceType) {
    return http.get(`${base(programKey, sourceType)}/default`)
  },

  parse(programKey, sourceType, file) {
    const form = new FormData()
    form.append('file', file)
    return http.post(`${base(programKey, sourceType)}/parse`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  save(programKey, sourceType, document, expectedSha256, sourceTaskId = null) {
    const body = { document, expected_sha256: expectedSha256 }
    if (sourceTaskId !== null && sourceTaskId !== undefined && sourceTaskId !== '') {
      body.source_task_id = sourceTaskId
    }
    return http.put(`${base(programKey, sourceType)}/current`, body, { silent: true })
  },

  versions(programKey, sourceType, params = {}) {
    return http.get(`${base(programKey, sourceType)}/versions`, { params })
  },

  version(programKey, sourceType, taskId) {
    return http.get(`${base(programKey, sourceType)}/versions/${encodeURIComponent(taskId)}`)
  },

  downloadCurrent(programKey, sourceType) {
    return http.get(`${base(programKey, sourceType)}/current/file`, {
      responseType: 'blob',
      headers: { Accept: 'application/octet-stream' },
    })
  },
}
