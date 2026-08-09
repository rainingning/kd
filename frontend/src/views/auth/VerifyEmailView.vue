<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <h2 class="auth-title">邮箱验证</h2>
      <div v-if="state === 'loading'" class="loading-box">
        <el-icon class="is-loading" :size="28"><Loading /></el-icon>
        <p>正在验证，请稍候...</p>
      </div>
      <el-result
        v-else-if="state === 'success'"
        icon="success"
        title="邮箱验证成功"
        sub-title="账号已激活，请登录"
      >
        <template #extra>
          <el-button type="primary" @click="$router.push('/login')">去登录</el-button>
        </template>
      </el-result>
      <el-result v-else icon="error" title="验证失败" :sub-title="errorMsg">
        <template #extra>
          <el-button type="primary" @click="$router.push('/login')">去登录</el-button>
          <el-button @click="$router.push('/register')">重新注册</el-button>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { authApi } from '../../api/auth'
import { extractErrorMessage } from '../../api/http'

const route = useRoute()
const state = ref('loading')
const errorMsg = ref('链接无效或已过期')

onMounted(async () => {
  const token = route.query.token
  if (!token) {
    state.value = 'error'
    errorMsg.value = '链接无效：缺少 token 参数'
    return
  }
  try {
    // silent：失败时不在拦截器弹消息，错误展示在结果页里
    await authApi.verify(token, { silent: true })
    state.value = 'success'
  } catch (error) {
    state.value = 'error'
    errorMsg.value = extractErrorMessage(error, '链接无效或已过期')
  }
})
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #e8f0fe 0%, #f5f7fa 100%);
}

.auth-card {
  width: 460px;
}

.auth-title {
  margin: 0 0 20px;
  text-align: center;
}

.loading-box {
  text-align: center;
  padding: 40px 0;
  color: #909399;
}
</style>
