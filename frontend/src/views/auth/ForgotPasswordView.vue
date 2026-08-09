<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <h2 class="auth-title">忘记密码</h2>
      <template v-if="!sent">
        <p class="tip">输入注册邮箱，我们将发送重置密码链接。</p>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
          <el-form-item label="邮箱" prop="email">
            <el-input v-model="form.email" placeholder="请输入注册邮箱" @keyup.enter="onSubmit" />
          </el-form-item>
          <el-button type="primary" class="auth-btn" :loading="loading" @click="onSubmit">
            发送重置邮件
          </el-button>
        </el-form>
      </template>
      <el-result
        v-else
        icon="success"
        title="邮件已发送"
        sub-title="如果该邮箱已注册，重置密码邮件已发送，请查收（1 小时内有效）"
      >
        <template #extra>
          <el-button type="primary" @click="$router.push('/login')">返回登录</el-button>
        </template>
      </el-result>
      <div class="auth-links">
        <router-link to="/login">返回登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { authApi } from '../../api/auth'

const formRef = ref()
const loading = ref(false)
const sent = ref(false)
const form = reactive({ email: '' })

const rules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
}

async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await authApi.forgotPassword(form.email)
    sent.value = true
  } finally {
    loading.value = false
  }
}
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
  width: 400px;
}

.auth-title {
  margin: 0 0 20px;
  text-align: center;
}

.tip {
  color: #909399;
  font-size: 14px;
  margin-top: 0;
}

.auth-btn {
  width: 100%;
}

.auth-links {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  font-size: 14px;
}
</style>
