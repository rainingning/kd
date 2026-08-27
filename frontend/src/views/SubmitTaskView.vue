<template>
  <div class="page-container">
    <el-card class="page-card">
      <template #header>
        <div class="card-header">
          <span class="title">提交任务</span>
          <div v-if="isDcr" class="header-actions">
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
        :title="`已载入任务 #${copiedFrom} 的程序和参数选择；出于安全原因，请重新上传输入文件`"
        :closable="false"
        class="copy-alert"
      />

      <el-form label-position="top">
        <el-form-item label="科学计算程序" required>
          <el-select v-model="programKey" class="program-select" @change="onProgramChange">
            <el-option v-for="program in programs" :key="program.key" :label="program.name" :value="program.key" />
          </el-select>
        </el-form-item>

        <template v-if="!isDcr">
          <el-form-item label="参数文件选择" required :error="choiceError">
            <el-radio-group v-model="stdinChoice" @change="onChoiceChange">
              <el-radio v-for="choice in sourceChoices" :key="choice.value" :value="choice.value">
                {{ choice.value }} — {{ choice.filename }}（{{ choice.label }}）
              </el-radio>
            </el-radio-group>
            <div class="field-hint">平台会通过 stdin 写入所选数字并附加回车，不向程序传递命令行参数。</div>
          </el-form-item>

          <el-form-item :label="parameterUploadLabel" required>
            <el-upload
              ref="parameterUploadRef"
              :auto-upload="false"
              :limit="1"
              accept=".dat"
              :on-change="onParameterFileChange"
              :on-remove="onParameterFileRemove"
              :on-exceed="onParameterFileExceed"
            >
              <el-button :disabled="!stdinChoice">选择 .dat 参数文件</el-button>
              <template #tip>
                <div class="el-upload__tip">上传文件将按所选项保存为固定文件名；另一个参数文件使用程序模板默认值。</div>
              </template>
            </el-upload>
            <div v-if="parameterFileError" class="field-error">{{ parameterFileError }}</div>
          </el-form-item>
        </template>

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
                运行时固定保存为 <code>mesh/mesh.mphtxt</code>，历史记录保留原始文件名。
              </div>
            </template>
          </el-upload>
          <div v-if="fileError" class="field-error">{{ fileError }}</div>
        </el-form-item>
      </el-form>

      <template v-if="isDcr">
        <el-divider content-position="left">算法参数</el-divider>
        <ParamForm ref="paramFormRef" v-model="params" program-key="dcr_3d" />
      </template>

      <div class="submit-row">
        <el-button type="primary" size="large" :loading="submitting" @click="onSubmit">提交任务</el-button>
      </div>
    </el-card>

    <el-dialog v-model="saveDialogVisible" title="另存为 DCR_3D 参数模板" width="420px">
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
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import ParamForm from '../components/ParamForm.vue'
import { taskApi } from '../api/tasks'
import { templateApi } from '../api/templates'
import { getPrograms } from '../api/params'

const route = useRoute()
const router = useRouter()
const paramFormRef = ref()
const uploadRef = ref()
const parameterUploadRef = ref()
const params = ref({})
const programs = ref([])
const programKey = ref('dcr_3d')
const stdinChoice = ref(null)
const templates = ref([])
const selectedTemplateId = ref(null)
const file = ref(null)
const parameterFile = ref(null)
const fileError = ref('')
const parameterFileError = ref('')
const choiceError = ref('')
const submitting = ref(false)
const copiedFrom = ref(null)
const saveDialogVisible = ref(false)
const saveName = ref('')
const saveNameError = ref('')
const saving = ref(false)

const selectedProgram = computed(() => programs.value.find((item) => item.key === programKey.value))
const isDcr = computed(() => programKey.value === 'dcr_3d')
const sourceChoices = computed(() => selectedProgram.value?.source_choices || [])
const selectedChoice = computed(() => sourceChoices.value.find((item) => item.value === stdinChoice.value))
const parameterUploadLabel = computed(() => selectedChoice.value
  ? `上传 ${selectedChoice.value.filename}`
  : '上传所选参数文件')

onMounted(async () => {
  try {
    const catalog = await getPrograms()
    programs.value = catalog.items || []
    await loadTemplates()
    const from = route.query.from
    if (from) {
      const task = await taskApi.detail(from)
      programKey.value = task.program_key || 'dcr_3d'
      stdinChoice.value = task.stdin_choice
      params.value = { ...task.params }
      copiedFrom.value = task.id
    }
  } catch {
    // 全局拦截器已提示
  }
})

async function loadTemplates() {
  templates.value = await templateApi.list('dcr_3d')
}

function onProgramChange() {
  stdinChoice.value = null
  params.value = {}
  selectedTemplateId.value = null
  clearParameterFile()
}

function onChoiceChange() {
  choiceError.value = ''
  clearParameterFile()
}

function clearParameterFile() {
  parameterUploadRef.value?.clearFiles()
  parameterFile.value = null
  parameterFileError.value = ''
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

function onFileChange(uploadFile) { file.value = uploadFile.raw; fileError.value = '' }
function onFileRemove() { file.value = null }
function onFileExceed(files) {
  uploadRef.value.clearFiles(); uploadRef.value.handleStart(files[0]); file.value = files[0]; fileError.value = ''
}
function onParameterFileChange(uploadFile) { parameterFile.value = uploadFile.raw; parameterFileError.value = '' }
function onParameterFileRemove() { parameterFile.value = null }
function onParameterFileExceed(files) {
  parameterUploadRef.value.clearFiles(); parameterUploadRef.value.handleStart(files[0]); parameterFile.value = files[0]; parameterFileError.value = ''
}

async function onSaveTemplate() {
  saveNameError.value = ''
  if (!saveName.value.trim()) { saveNameError.value = '请输入模板名称'; return }
  if (!paramFormRef.value?.validate()) { ElMessage.warning('参数校验未通过'); return }
  saving.value = true
  try {
    await templateApi.create(saveName.value.trim(), cleanParams(), 'dcr_3d')
    ElMessage.success('模板已保存')
    saveDialogVisible.value = false
    saveName.value = ''
    await loadTemplates()
  } finally { saving.value = false }
}

function cleanParams() {
  return Object.fromEntries(Object.entries(params.value).filter(([, value]) => value !== undefined && value !== null && value !== ''))
}

async function onSubmit() {
  let valid = true
  if (isDcr.value) {
    valid = Boolean(paramFormRef.value?.validate())
  } else {
    if (!stdinChoice.value) { choiceError.value = '请选择参数文件 1 或 2'; valid = false }
    if (!parameterFile.value) { parameterFileError.value = '请上传所选 .dat 参数文件'; valid = false }
    else if (!parameterFile.value.name.toLowerCase().endsWith('.dat')) {
      parameterFileError.value = '参数文件必须是 .dat 文件'; valid = false
    }
  }
  if (!file.value) { fileError.value = '请选择输入数据文件'; valid = false }
  if (!valid) { ElMessage.warning('请补全并检查提交信息'); return }

  submitting.value = true
  try {
    const task = await taskApi.submit({
      programKey: programKey.value,
      params: isDcr.value ? cleanParams() : {},
      stdinChoice: isDcr.value ? null : stdinChoice.value,
      meshFile: file.value,
      parameterFile: isDcr.value ? null : parameterFile.value,
    })
    ElMessage.success(`任务 #${task.id} 提交成功，已进入队列`)
    router.push(`/tasks/${task.id}`)
  } finally { submitting.value = false }
}
</script>

<style scoped>
.header-actions { display: flex; gap: 12px; }
.copy-alert { margin-bottom: 16px; }
.program-select { width: 360px; }
.upload-icon { color: #909399; margin-top: 8px; }
.field-hint { width: 100%; margin-top: 8px; color: #909399; font-size: 12px; }
.submit-row { margin-top: 24px; text-align: center; }
</style>
