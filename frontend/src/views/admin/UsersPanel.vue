<template>
  <div>
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="按用户名或邮箱搜索"
        clearable
        style="width: 240px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-button @click="onSearch">搜索</el-button>
      <el-button type="primary" @click="openCreate">创建用户</el-button>
    </div>

    <el-table v-loading="loading" :data="items" border size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
      <el-table-column label="角色" width="110">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'primary'" size="small">
            {{ row.role === 'admin' ? '管理员' : '普通用户' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="注册时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="最后登录" width="170">
        <template #default="{ row }">{{ formatTime(row.last_login_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="row.status === 'active'"
            size="small"
            type="warning"
            plain
            @click="onDisable(row)"
          >
            禁用
          </el-button>
          <el-button v-else size="small" type="success" plain @click="onEnable(row)">
            启用
          </el-button>
          <el-button size="small" plain @click="onResetPassword(row)">重置密码</el-button>
          <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无用户</template>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @current-change="load()"
        @size-change="onSearch"
      />
    </div>

    <!-- 创建 / 编辑用户 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑用户' : '创建用户'"
      width="460px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="90px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="3-64 位字母、数字或下划线" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item v-if="!editing" label="初始密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 临时密码展示（只显示一次） -->
    <el-dialog v-model="tempPwdVisible" title="重置密码成功" width="420px">
      <el-alert type="warning" :closable="false" class="temp-alert">
        临时密码只显示这一次，请立即复制并转交用户。
      </el-alert>
      <div class="temp-pwd-box">
        <code class="temp-pwd">{{ tempPassword }}</code>
        <el-button size="small" type="primary" @click="copyTempPassword">复制</el-button>
      </div>
      <template #footer>
        <el-button type="primary" @click="tempPwdVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '../../api/admin'
import { formatTime } from '../../utils/format'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)

const dialogVisible = ref(false)
const editing = ref(null)
const formRef = ref()
const saving = ref(false)
const form = reactive({ username: '', email: '', password: '', role: 'user' })

const formRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_]{3,64}$/, message: '用户名为 3-64 位字母、数字或下划线', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 8, max: 72, message: '密码长度为 8-72 位', trigger: 'blur' },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

const tempPwdVisible = ref(false)
const tempPassword = ref('')

onMounted(load)

async function load() {
  loading.value = true
  try {
    const data = await adminApi.users({
      keyword: keyword.value,
      page: page.value,
      pageSize: pageSize.value,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  load()
}

function statusLabel(s) {
  return { active: '正常', pending: '待验证', disabled: '已禁用' }[s] || s
}

function statusType(s) {
  return { active: 'success', pending: 'warning', disabled: 'info' }[s] || 'info'
}

function openCreate() {
  editing.value = null
  Object.assign(form, { username: '', email: '', password: '', role: 'user' })
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = row
  Object.assign(form, { username: row.username, email: row.email, password: '', role: row.role })
  dialogVisible.value = true
}

async function onSave() {
  await formRef.value.validate()
  saving.value = true
  try {
    if (editing.value) {
      await adminApi.updateUser(editing.value.id, {
        username: form.username,
        email: form.email,
        role: form.role,
      })
      ElMessage.success('用户已更新')
    } else {
      await adminApi.createUser({
        username: form.username,
        email: form.email,
        password: form.password,
        role: form.role,
      })
      ElMessage.success('用户已创建（已直接激活）')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function onDisable(row) {
  try {
    await ElMessageBox.confirm(
      `确定禁用用户「${row.username}」吗？其排队中的任务将被取消。`,
      '禁用用户',
      { confirmButtonText: '禁用', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await adminApi.disableUser(row.id)
  ElMessage.success('已禁用')
  load()
}

async function onEnable(row) {
  await adminApi.enableUser(row.id)
  ElMessage.success('已启用')
  load()
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除用户「${row.username}」吗？其任务、通知与模板数据将一并删除，不可恢复。`,
      '删除用户',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'error' },
    )
  } catch {
    return
  }
  await adminApi.deleteUser(row.id)
  ElMessage.success('已删除')
  load()
}

async function onResetPassword(row) {
  try {
    await ElMessageBox.confirm(
      `确定重置用户「${row.username}」的密码吗？将生成临时密码。`,
      '重置密码',
      { confirmButtonText: '重置', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  const data = await adminApi.resetUserPassword(row.id)
  tempPassword.value = data.temporary_password
  tempPwdVisible.value = true
}

async function copyTempPassword() {
  try {
    await navigator.clipboard.writeText(tempPassword.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}
</script>

<style scoped>
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.temp-alert {
  margin-bottom: 16px;
}

.temp-pwd-box {
  display: flex;
  align-items: center;
  gap: 12px;
}

.temp-pwd {
  flex: 1;
  font-size: 18px;
  padding: 10px 14px;
  background: #f5f7fa;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  user-select: all;
}
</style>
