<template>
  <div class="page-container">
    <el-card class="page-card">
      <template #header>
        <div class="card-header">
          <span class="title">提交任务</span>
          <div class="header-actions">
            <el-select
              v-model="selectedTemplateId"
              placeholder="从模板载入参数"
              clearable
              style="width: 220px"
              @change="onTemplateChange"
            >
              <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
            </el-select>
            <el-button @click="saveDialogVisible = true">另存为模板</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="copiedFrom"
        type="info"
        :title="`已载入任务 #${copiedFrom} 的参数，可修改后重新提交`"
        :closable="false"
        class="copy-alert"
      />

      <el-form label-position="top">
        <el-form-item label="输入数据文件" required>
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
            :on-exceed="onFileExceed"
            drag
          >
            <el-icon :size="40" class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择文件</em></div>
            <template #tip>
              <div class="el-upload__tip">
                单个输入文件，大小上限由系统配置决定；运行时将固定保存为
                <code>mesh/mesh.mphtxt</code>，历史下载仍保留原始文件名。
              </div>
            </template>
          </el-upload>
          <div v-if="fileError" class="field-error">{{ fileError }}</div>
        </el-form-item>
      </el-form>

      <el-divider content-position="left">算法参数</el-divider>
      <ParamForm ref="paramFormRef" v-model="params" />

      <div class="submit-row">
        <el-button type="primary" size="large" :loading="submitting" @click="onSubmit">
          提交任务
        </el-button>
      </div>
    </el-card>

    <el-dialog v-model="saveDialogVisible" title="另存为参数模板" width="420px">
      <el-form label-position="top">
        <el-form-item label="模板名称" required :error="saveNameError">
          <el-input v-model="saveName" placeholder="请输入模板名称" maxlength="128" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSaveTemplate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import ParamForm from '../components/ParamForm.vue'
import { taskApi } from '../api/tasks'
import { templateApi } from '../api/templates'

const route = useRoute()
const router = useRouter()

const paramFormRef = ref()
const uploadRef = ref()
const params = ref({})
const templates = ref([])
const selectedTemplateId = ref(null)
const file = ref(null)
const fileError = ref('')
const submitting = ref(false)
const copiedFrom = ref(null)

const saveDialogVisible = ref(false)
const saveName = ref('')
const saveNameError = ref('')
const saving = ref(false)

onMounted(async () => {
  loadTemplates()
  // 「复制参数重新提交」：?from=<taskId> 预填参数
  const from = route.query.from
  if (from) {
    try {
      const task = await taskApi.detail(from)
      params.value = { ...task.params }
      copiedFrom.value = task.id
    } catch {
      // 拦截器已提示
    }
  }
})

async function loadTemplates() {
  try {
    templates.value = await templateApi.list()
  } catch {
    // 拦截器已提示
  }
}

function onTemplateChange(id) {
  if (!id) return
  const tpl = templates.value.find((t) => t.id === id)
  if (tpl) {
    params.value = { ...tpl.params }
    ElMessage.success(`已载入模板「${tpl.name}」`)
  }
  selectedTemplateId.value = null
}

function onFileChange(uploadFile) {
  file.value = uploadFile.raw
  fileError.value = ''
}

function onFileRemove() {
  file.value = null
}

function onFileExceed(files) {
  uploadRef.value.clearFiles()
  uploadRef.value.handleStart(files[0])
  file.value = files[0]
  fileError.value = ''
}

async function onSaveTemplate() {
  saveNameError.value = ''
  if (!saveName.value.trim()) {
    saveNameError.value = '请输入模板名称'
    return
  }
  if (!paramFormRef.value.validate()) {
    saveDialogVisible.value = false
    ElMessage.warning('参数校验未通过，请先修正表单中的错误')
    return
  }
  saving.value = true
  try {
    await templateApi.create(saveName.value.trim(), cleanParams())
    ElMessage.success('模板已保存')
    saveDialogVisible.value = false
    saveName.value = ''
    loadTemplates()
  } finally {
    saving.value = false
  }
}

// 去掉未填写的可选参数，交给后端补默认值
function cleanParams() {
  const out = {}
  for (const [k, v] of Object.entries(params.value)) {
    if (v !== undefined && v !== null && v !== '') out[k] = v
  }
  return out
}

async function onSubmit() {
  if (!paramFormRef.value.validate()) {
    ElMessage.warning('参数校验未通过，请检查表单')
    return
  }
  if (!file.value) {
    fileError.value = '请选择输入数据文件'
    return
  }
  submitting.value = true
  try {
    const task = await taskApi.submit(cleanParams(), file.value)
    ElMessage.success(`任务 #${task.id} 提交成功，已进入队列`)
    router.push(`/tasks/${task.id}`)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.header-actions {
  display: flex;
  gap: 12px;
}

.copy-alert {
  margin-bottom: 16px;
}

.upload-icon {
  color: #909399;
  margin-top: 8px;
}

.submit-row {
  margin-top: 24px;
  text-align: center;
}
</style>
