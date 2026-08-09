import http, { extractErrorMessage } from './http'
import { ElMessage } from 'element-plus'

export const taskApi = {
  submit: (params, file) => {
    const form = new FormData()
    form.append('params', JSON.stringify(params))
    form.append('file', file)
    return http.post('/tasks', form)
  },
  list: ({ status, page, pageSize } = {}) => {
    const q = { page, page_size: pageSize }
    if (status) q.status = status
    return http.get('/tasks', { params: q })
  },
  detail: (id) => http.get(`/tasks/${id}`),
  cancel: (id) => http.post(`/tasks/${id}/cancel`),
}

// 从 Content-Disposition 解析下载文件名
function parseFilename(disposition) {
  if (!disposition) return null
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star) return decodeURIComponent(star[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  if (plain) return plain[1]
  return null
}

// 带 token 下载任务文件并触发浏览器保存；404 等情况弹中文提示
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
      // blob 响应的错误体需要先转文本再解析
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
