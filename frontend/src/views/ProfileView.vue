<template>
  <div class="page-container">
    <el-card class="page-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="账户信息" name="account">
          <div class="account-pane" v-if="auth.user">
            <el-descriptions :column="1" border class="info-desc">
              <el-descriptions-item label="用户名">{{ auth.user.username }}</el-descriptions-item>
              <el-descriptions-item label="邮箱">{{ auth.user.email }}</el-descriptions-item>
              <el-descriptions-item label="角色">
                {{ auth.user.role === 'admin' ? '系统管理员' : '普通用户' }}
              </el-descriptions-item>
              <el-descriptions-item label="注册时间">
                {{ formatTime(auth.user.created_at) }}
              </el-descriptions-item>
              <el-descriptions-item label="最后登录">
                {{ formatTime(auth.user.last_login_at) }}
              </el-descriptions-item>
            </el-descriptions>

            <el-divider content-position="left">修改用户名</el-divider>
            <el-form label-width="100px" class="account-form" @submit.prevent>
              <el-form-item label="新用户名" :error="usernameError">
                <el-input v-model="newUsername" placeholder="3-64 位字母、数字或下划线" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="savingUsername" @click="onUpdateUsername">
                  保存
                </el-button>
              </el-form-item>
            </el-form>

            <el-divider content-position="left">修改密码</el-divider>
            <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="100px" class="account-form" @submit.prevent>
              <el-form-item label="原密码" prop="oldPassword">
                <el-input v-model="pwdForm.oldPassword" type="password" show-password />
              </el-form-item>
              <el-form-item label="新密码" prop="newPassword">
                <el-input v-model="pwdForm.newPassword" type="password" show-password placeholder="至少 8 位" />
              </el-form-item>
              <el-form-item label="确认新密码" prop="confirm">
                <el-input v-model="pwdForm.confirm" type="password" show-password />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="savingPassword" @click="onChangePassword">
                  修改密码
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane name="notifications">
          <template #label>
            通知
            <el-badge v-if="notify.unreadCount" :value="notify.unreadCount" :max="99" class="tab-badge" />
          </template>
          <div class="toolbar">
            <el-checkbox v-model="unreadOnly" @change="onFilterChange">只看未读</el-checkbox>
            <el-button size="small" @click="loadNotifications()">刷新</el-button>
            <el-button
              size="small"
              type="primary"
              plain
              :disabled="notify.unreadCount === 0"
              @click="onMarkAllRead"
            >
              全部标为已读
            </el-button>
          </div>
          <div v-loading="notifLoading">
            <template v-if="notifications.length">
              <div
                v-for="n in notifications"
                :key="n.id"
                class="notification-item"
                :class="{ unread: !n.read }"
                @click="onClickNotification(n)"
              >
                <div class="msg">
                  <el-tag
                    :type="NOTIFICATION_TYPE[n.type]?.type || 'info'"
                    size="small"
                    class="type-tag"
                  >
                    {{ NOTIFICATION_TYPE[n.type]?.label || n.type }}
                  </el-tag>
                  {{ n.message }}
                </div>
                <div class="time">{{ formatTime(n.created_at) }}</div>
              </div>
            </template>
            <el-empty v-else description="暂无通知" />
          </div>
          <div class="pager">
            <el-pagination
              v-model:current-page="notifPage"
              :page-size="notifPageSize"
              :total="notifTotal"
              layout="total, prev, pager, next"
              @current-change="loadNotifications()"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notification'
import { notificationApi } from '../api/notifications'
import { userApi } from '../api/auth'
import { NOTIFICATION_TYPE, formatTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const notify = useNotificationStore()

const activeTab = ref(route.query.tab === 'notifications' ? 'notifications' : 'account')
watch(activeTab, (tab) => {
  router.replace({ query: tab === 'notifications' ? { tab: 'notifications' } : {} })
})

// ---- 账户信息 ----
const newUsername = ref('')
const usernameError = ref('')
const savingUsername = ref(false)

const pwdFormRef = ref()
const savingPassword = ref(false)
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirm: '' })
const pwdRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 72, message: '密码长度为 8-72 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value !== pwdForm.newPassword) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

onMounted(async () => {
  await auth.ensureUser()
  newUsername.value = auth.user?.username || ''
  if (activeTab.value === 'notifications') loadNotifications()
})

watch(activeTab, (tab) => {
  if (tab === 'notifications') loadNotifications()
})

async function onUpdateUsername() {
  usernameError.value = ''
  if (!/^[A-Za-z0-9_]{3,64}$/.test(newUsername.value)) {
    usernameError.value = '用户名为 3-64 位字母、数字或下划线'
    return
  }
  savingUsername.value = true
  try {
    const user = await userApi.updateMe(newUsername.value)
    auth.user = user
    ElMessage.success('用户名已更新')
  } finally {
    savingUsername.value = false
  }
}

async function onChangePassword() {
  await pwdFormRef.value.validate()
  savingPassword.value = true
  try {
    await userApi.changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    ElMessage.success('密码修改成功')
    pwdForm.oldPassword = ''
    pwdForm.newPassword = ''
    pwdForm.confirm = ''
    pwdFormRef.value.clearValidate()
  } finally {
    savingPassword.value = false
  }
}

// ---- 通知 ----
const notifications = ref([])
const notifTotal = ref(0)
const notifPage = ref(1)
const notifPageSize = 20
const notifLoading = ref(false)
const unreadOnly = ref(false)

async function loadNotifications() {
  notifLoading.value = true
  try {
    const data = await notificationApi.list({
      unreadOnly: unreadOnly.value,
      page: notifPage.value,
      pageSize: notifPageSize,
    })
    notifications.value = data.items
    notifTotal.value = data.total
    notify.unreadCount = data.unread_count
  } catch {
    // 拦截器已提示
  } finally {
    notifLoading.value = false
  }
}

function onFilterChange() {
  notifPage.value = 1
  loadNotifications()
}

async function onClickNotification(n) {
  if (!n.read) {
    try {
      await notificationApi.markRead([n.id])
      n.read = true
      notify.refreshUnread()
    } catch {
      // 拦截器已提示
    }
  }
  if (n.task_id) {
    router.push(`/tasks/${n.task_id}`)
  }
}

async function onMarkAllRead() {
  await notificationApi.markRead(null)
  ElMessage.success('已全部标记为已读')
  loadNotifications()
}
</script>

<style scoped>
.account-pane {
  max-width: 640px;
}

.info-desc {
  margin-bottom: 8px;
}

.account-form {
  max-width: 480px;
}

.tab-badge {
  margin-left: 6px;
  vertical-align: 2px;
}

.type-tag {
  margin-right: 8px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
