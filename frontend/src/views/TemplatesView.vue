<template>
  <div class="page-container">
    <el-card class="page-card">
      <template #header>
        <div class="card-header">
          <span class="title">参数模板</span>
          <el-button type="primary" @click="openCreate">新建模板</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="items" border>
        <el-table-column prop="name" label="模板名称" min-width="200" />
        <el-table-column label="更新时间" width="200">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="200">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无模板，点击右上角「新建模板」创建</template>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑模板' : '新建模板'"
      width="640px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="模板名称" required :error="nameError">
          <el-input v-model="formName" placeholder="请输入模板名称" maxlength="128" />
        </el-form-item>
      </el-form>
      <ParamForm ref="paramFormRef" v-model="formParams" />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ParamForm from '../components/ParamForm.vue'
import { templateApi } from '../api/templates'
import { formatTime } from '../utils/format'

const items = ref([])
const loading = ref(false)

const dialogVisible = ref(false)
const editing = ref(null)
const formName = ref('')
const nameError = ref('')
const formParams = ref({})
const paramFormRef = ref()
const saving = ref(false)

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await templateApi.list()
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  formName.value = ''
  nameError.value = ''
  formParams.value = {}
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = row
  formName.value = row.name
  nameError.value = ''
  formParams.value = { ...row.params }
  dialogVisible.value = true
}

function cleanParams() {
  const out = {}
  for (const [k, v] of Object.entries(formParams.value)) {
    if (v !== undefined && v !== null && v !== '') out[k] = v
  }
  return out
}

async function onSave() {
  nameError.value = ''
  if (!formName.value.trim()) {
    nameError.value = '请输入模板名称'
    return
  }
  if (!paramFormRef.value.validate()) {
    ElMessage.warning('参数校验未通过，请检查表单')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await templateApi.update(editing.value.id, {
        name: formName.value.trim(),
        params: cleanParams(),
      })
      ElMessage.success('模板已更新')
    } else {
      await templateApi.create(formName.value.trim(), cleanParams())
      ElMessage.success('模板已创建')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除模板「${row.name}」吗？删除后不可恢复。`, '删除模板', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await templateApi.remove(row.id)
  ElMessage.success('模板已删除')
  load()
}
</script>
