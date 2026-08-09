<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <h2 class="auth-title">重置密码</h2>
      <el-alert
        v-if="!token"
        type="error"
        title="链接无效：缺少 token 参数"
        :closable="false"
        class="alert"
      />
      <template v-else-if="!done">
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
          <el-form-item label="新密码" prop="password">
            <el-input v-model="form.password" type="password" show-password placeholder="至少 8 位" />
          </el-form-item>
          <el-form-item label="确认新密码" prop="confirm">
            <el-input
              v-model="form.confirm"
              type="password"
              show-password
              placeholder="再次输入新密码"
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <el-button type="primary" class="auth-btn" :loading="loading" @click="onSubmit">
            重置密码
          </el-button>
        </el-form>
      </template>
      <el-result v-else icon="success" title="密码重置成功" sub-title="请使用新密码登录">
        <template #extra>
          <el-button type="primary" @click="$router.push('/login')">去登录</el-button>
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
import { useRoute } from 'vue-router'
import { authApi } from '../../api/auth'

const route = useRoute()
const token = route.query.token || ''

const formRef = ref()
const loading = ref(false)
const done = ref(false)
const form = reactive({ password: '', confirm: '' })

const rules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 72, message: '密码长度为 8-72 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
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
    await authApi.resetPassword(token, form.password)
    done.value = true
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

.alert {
  margin-bottom: 16px;
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
