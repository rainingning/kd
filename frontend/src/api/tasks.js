import http, { extractErrorMessage } from './http'
import { ElMessage } from 'element-plus'

export const taskApi = {
  submit: ({ programKey, params = {}, stdinChoice = null, dcrParameterSha256 = null, meshFile, parameterFile = null }) => {
    const form = new FormData()
    form.append('program_key', programKey)
    form.append('params', JSON.stringify(params))
    if (stdinChoice !== null) form.append('stdin_choice', String(stdinChoice))
    if (dcrParameterSha256) form.append('dcr_parameter_sha256', dcrParameterSha256)
    form.append('file', meshFile)
    if (parameterFile) form.append('parameter_file', parameterFile)
    return http.post('/tasks', form)
  },
  list: ({ status, page, pageSize, programKey } = {}) => {
    const q = { page, page_size: pageSize }
    if (status) q.status = status
    if (programKey) q.program_key = programKey
    return http.get('/tasks', { params: q })
  },
  detail: (id) => http.get(`/tasks/${id}`),
  cancel: (id) => http.post(`/tasks/${id}/cancel`),
}

function parseFilename(disposition) {
  if (!disposition) return null
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star) return decodeURIComponent(star[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  if (plain) return plain[1]
  return null
}

export async function downloadTaskFile(taskId, kind, fallbackName) {
  try {
    const resp = await http.get(`/tasks/${taskId}/files/${kind}`, {
      responseType: 'blob',
      silent: true,
    })
    const url = URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = url
    a.download = parseFilename(resp.headers?.['content-disposition']) || fallbackName || `${kind}.txt`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    let msg = '下载失败'
    if (error?.response?.data instanceof Blob) {
      try {
        const text = await error.response.data.text()
        msg = extractErrorMessage({ response: { data: JSON.parse(text) } }, msg)
      } catch {
        msg = error?.response?.status === 404 ? '文件不存在或已被清理' : '下载失败'
      }
    } else {
      msg = extractErrorMessage(error, msg)
    }
    ElMessage.error(msg)
  }
}
