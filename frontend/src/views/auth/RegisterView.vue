<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <h2 class="auth-title">注册</h2>
      <template v-if="!registered">
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="3-64 位字母、数字或下划线" />
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input v-model="form.email" placeholder="用于接收验证邮件" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" type="password" show-password placeholder="至少 8 位" />
          </el-form-item>
          <el-form-item label="确认密码" prop="confirm">
            <el-input
              v-model="form.confirm"
              type="password"
              show-password
              placeholder="再次输入密码"
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <el-button type="primary" class="auth-btn" :loading="loading" @click="onSubmit">
            注册
          </el-button>
        </el-form>
        <div class="auth-links">
          <router-link to="/login">已有账号？去登录</router-link>
        </div>
      </template>
      <el-result
        v-else
        icon="success"
        title="注册成功"
        sub-title="验证邮件已发送，请查收并完成邮箱验证后登录"
      >
        <template #extra>
          <el-button type="primary" @click="$router.push('/login')">去登录</el-button>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi } from '../../api/auth'

const formRef = ref()
const loading = ref(false)
const registered = ref(false)
const form = reactive({ username: '', email: '', password: '', confirm: '' })

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9_]{3,64}$/,
      message: '用户名为 3-64 位字母、数字或下划线',
      trigger: 'blur',
    },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 72, message: '密码长度为 8-72 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value !== form.password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    const data = await authApi.register({
      username: form.username,
      email: form.email,
      password: form.password,
    })
    registered.value = true
    ElMessage.success(data?.detail || '注册成功，验证邮件已发送，请查收')
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
