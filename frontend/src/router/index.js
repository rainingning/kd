import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/auth/LoginView.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('../views/auth/RegisterView.vue'),
    meta: { title: '注册' },
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('../views/auth/ForgotPasswordView.vue'),
    meta: { title: '忘记密码' },
  },
  {
    path: '/reset-password',
    name: 'reset-password',
    component: () => import('../views/auth/ResetPasswordView.vue'),
    meta: { title: '重置密码' },
  },
  {
    path: '/verify',
    name: 'verify',
    component: () => import('../views/auth/VerifyEmailView.vue'),
    meta: { title: '邮箱验证' },
  },
  {
    path: '/',
    component: () => import('../layout/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/submit' },
      {
        path: 'submit',
        name: 'submit',
        component: () => import('../views/SubmitTaskView.vue'),
        meta: { title: '提交任务', requiresAuth: true },
      },
      {
        path: 'dcr-params',
        name: 'dcr-params',
        component: () => import('../views/DcrParamsView.vue'),
        meta: { title: 'DCR 参数', requiresAuth: true },
      },
      {
        path: 'program-params',
        redirect: '/program-params/be_fetd/grounded_wire',
      },
      {
        path: 'program-params/:programKey/:sourceType',
        name: 'source-params',
        component: () => import('../views/SourceParamsView.vue'),
        meta: { title: 'BE/FDEM 参数', requiresAuth: true },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('../views/TaskListView.vue'),
        meta: { title: '任务列表', requiresAuth: true },
      },
      {
        path: 'tasks/:id',
        name: 'task-detail',
        component: () => import('../views/TaskDetailView.vue'),
        meta: { title: '任务详情', requiresAuth: true },
      },
      {
        path: 'templates',
        name: 'templates',
        component: () => import('../views/TemplatesView.vue'),
        meta: { title: '参数模板', requiresAuth: true },
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('../views/ProfileView.vue'),
        meta: { title: '用户中心', requiresAuth: true },
      },
      {
        path: 'admin',
        name: 'admin',
        component: () => import('../views/admin/AdminView.vue'),
        meta: { title: '管理后台', requiresAuth: true, requiresAdmin: true },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.title) {
    document.title = `${to.meta.title} - Fortran 科学计算平台`
  }
  if (!to.meta.requiresAuth) {
    // 已登录用户访问登录页时直接进入主页
    if (to.path === '/login' && auth.isLoggedIn) return { path: '/' }
    return true
  }
  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  try {
    await auth.ensureUser()
  } catch {
    // 拉取用户信息失败（如 token 失效），拦截器已处理跳转
    return false
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    ElMessage.warning('需要管理员权限')
    return { path: '/' }
  }
  return true
})

export default router
