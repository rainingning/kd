import { defineStore } from 'pinia'
import { authApi } from '../api/auth'
import { getToken, setToken } from '../api/http'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: null,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    async login(username, password) {
      const data = await authApi.login({ username, password })
      this.token = data.access_token
      setToken(data.access_token)
      await this.fetchUser()
    },
    async fetchUser() {
      this.user = await authApi.me()
      return this.user
    },
    // 有 token 但还没有用户信息时拉取（如刷新页面后）
    async ensureUser() {
      if (this.user || !this.token) return this.user
      return this.fetchUser()
    },
    logout() {
      this.token = null
      this.user = null
      setToken(null)
    },
  },
})
