<template>
  <el-container class="layout">
    <el-header class="layout-header">
      <div class="header-inner">
        <div class="brand" @click="$router.push('/')">Fortran 科学计算平台</div>
        <el-menu
          :default-active="activeMenu"
          mode="horizontal"
          router
          :ellipsis="false"
          class="nav-menu"
        >
          <el-menu-item index="/submit">提交任务</el-menu-item>
          <el-menu-item index="/tasks">任务列表</el-menu-item>
          <el-menu-item index="/templates">参数模板</el-menu-item>
          <el-menu-item index="/profile">用户中心</el-menu-item>
          <el-menu-item v-if="auth.isAdmin" index="/admin">管理后台</el-menu-item>
        </el-menu>
        <div class="header-right">
          <el-badge
            :value="notify.unreadCount"
            :hidden="notify.unreadCount === 0"
            :max="99"
            class="bell-badge"
          >
            <el-button text circle @click="goNotifications">
              <el-icon :size="20"><Bell /></el-icon>
            </el-button>
          </el-badge>
          <el-dropdown @command="onUserCommand">
            <span class="user-name">
              {{ auth.user?.username || '...' }}
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">用户中心</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </el-header>
    <el-main class="layout-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Bell, ArrowDown } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notification'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const notify = useNotificationStore()

const activeMenu = computed(() => {
  if (route.path.startsWith('/tasks')) return '/tasks'
  return route.path
})

let timer = null
onMounted(() => {
  notify.refreshUnread()
  timer = setInterval(() => notify.refreshUnread(), 15000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

function goNotifications() {
  router.push({ path: '/profile', query: { tab: 'notifications' } })
}

async function onUserCommand(cmd) {
  if (cmd === 'profile') {
    router.push('/profile')
  } else if (cmd === 'logout') {
    try {
      await ElMessageBox.confirm('确定退出登录吗？', '退出登录', {
        confirmButtonText: '退出',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  min-height: 100%;
}

.layout-header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0;
  height: 60px;
}

.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 20px;
}

.brand {
  font-size: 17px;
  font-weight: 700;
  color: var(--el-color-primary);
  white-space: nowrap;
  cursor: pointer;
}

.nav-menu {
  flex: 1;
  border-bottom: none;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.bell-badge :deep(.el-badge__content) {
  z-index: 2;
}

.user-name {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #303133;
}

.layout-main {
  padding: 0;
}
</style>
