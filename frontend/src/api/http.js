import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'

const TOKEN_KEY = 'token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 从错误响应体中提取中文错误信息；detail 可能是字符串或 {字段: 信息}（422）
export function extractErrorMessage(error, fallback = '请求失败，请稍后重试') {
  const data = error?.response?.data
  if (!data) return fallback
  const detail = data.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    return Object.values(detail).join('；') || fallback
  }
  return fallback
}

http.interceptors.response.use(
  // blob 下载需要完整响应（headers 里有 Content-Disposition 文件名）
  (response) => (response.config.responseType === 'blob' ? response : response.data),
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      // 仅当请求带了 token（即认为已登录）才视为登录失效，跳转登录页；
      // 登录/注册等匿名接口的 401 只提示错误信息
      const hadToken = Boolean(error?.config?.headers?.Authorization)
      if (hadToken) {
        setToken(null)
        ElMessage.error('登录已过期，请重新登录')
        if (router.currentRoute.value.path !== '/login') {
          router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
        }
        return Promise.reject(error)
      }
    }
    if (!error?.config?.silent) {
      ElMessage.error(extractErrorMessage(error))
    }
    return Promise.reject(error)
  },
)

export default http
