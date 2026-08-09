import http from './http'

export const authApi = {
  register: (data) => http.post('/auth/register', data),
  verify: (token, config = {}) => http.get('/auth/verify', { params: { token }, ...config }),
  login: (data) => http.post('/auth/login', data),
  forgotPassword: (email) => http.post('/auth/forgot-password', { email }),
  resetPassword: (token, newPassword) =>
    http.post('/auth/reset-password', { token, new_password: newPassword }),
  me: () => http.get('/auth/me'),
}

export const userApi = {
  updateMe: (username) => http.put('/users/me', { username }),
  changePassword: (oldPassword, newPassword) =>
    http.put('/users/me/password', { old_password: oldPassword, new_password: newPassword }),
}
