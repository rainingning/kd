<template>
  <div class="page-container">
    <el-card class="page-card">
      <template #header>
        <div class="card-header"><span class="title">提交任务</span></div>
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

          <el-card v-if="stdinChoice" shadow="never" v-loading="sourceParamsLoading" class="source-summary-card">
            <el-alert type="info" :closable="false" title="提交时后台会快照当前参数；任务排队后继续编辑不会改变本任务。" />
            <el-descriptions v-if="sourceCurrent" :column="2" border class="dcr-summary">
              <el-descriptions-item label="当前文件">{{ sourceCurrent.filename }}</el-descriptions-item>
              <el-descriptions-item label="格式">{{ sourceCurrent.schema_version }}</el-descriptions-item>
              <el-descriptions-item label="当前 SHA-256" :span="2"><code class="hash-text">{{ sourceCurrent.sha256 }}</code></el-descriptions-item>
              <el-descriptions-item label="材料数量">{{ sourceCurrent.document?.materials?.length || 0 }}</el-descriptions-item>
              <el-descriptions-item label="接收点数量">{{ sourceCurrent.document?.receivers?.length || 0 }}</el-descriptions-item>
            </el-descriptions>
            <el-button type="primary" plain class="edit-dcr" @click="editSourceParams">加载或编辑当前参数</el-button>
          </el-card>
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
        <el-divider content-position="left">DCR 参数快照</el-divider>
        <el-card shadow="never" v-loading="dcrParamsLoading">
          <el-alert
            type="info"
            :closable="false"
            title="提交时后台会把当前工作区 model_DC.dat 复制为本任务的不可变快照；以后编辑当前参数不会改变已提交任务。"
          />
          <el-descriptions v-if="dcrCurrent" :column="2" border class="dcr-summary">
            <el-descriptions-item label="当前 SHA-256" :span="2"><code class="hash-text">{{ dcrCurrent.sha256 }}</code></el-descriptions-item>
            <el-descriptions-item label="边界模式">{{ dcrCurrent.document?.boundary_mode === 1 ? 'Robin' : '零 Dirichlet' }}</el-descriptions-item>
            <el-descriptions-item label="输出 VTK">{{ dcrCurrent.document?.write_vtk ? '是' : '否' }}</el-descriptions-item>
            <el-descriptions-item label="材料数量">{{ dcrCurrent.document?.materials?.length || 0 }}</el-descriptions-item>
            <el-descriptions-item label="供电源数量">{{ dcrCurrent.document?.sources?.length || 0 }}</el-descriptions-item>
          </el-descriptions>
          <el-button type="primary" plain class="edit-dcr" @click="$router.push('/dcr-params')">加载或编辑 model_DC.dat</el-button>
        </el-card>
      </template>

      <div class="submit-row">
        <el-button type="primary" size="large" :loading="submitting" @click="onSubmit">提交任务</el-button>
      </div>
    </el-card>

  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { taskApi } from '../api/tasks'
import { dcrParamsApi } from '../api/dcrParams'
import { programParamsApi } from '../api/programParams'
import { getPrograms } from '../api/params'

const route = useRoute()
const router = useRouter()
const uploadRef = ref()
const programs = ref([])
const programKey = ref('dcr_3d')
const stdinChoice = ref(null)
const dcrCurrent = ref(null)
const dcrParamsLoading = ref(false)
const sourceCurrent = ref(null)
const sourceParamsLoading = ref(false)
const file = ref(null)
const fileError = ref('')
const choiceError = ref('')
const submitting = ref(false)
const copiedFrom = ref(null)

const selectedProgram = computed(() => programs.value.find((item) => item.key === programKey.value))
const isDcr = computed(() => programKey.value === 'dcr_3d')
const sourceChoices = computed(() => selectedProgram.value?.source_choices || [])
const selectedChoice = computed(() => sourceChoices.value.find((item) => item.value === stdinChoice.value))

onMounted(async () => {
  try {
    const catalog = await getPrograms()
    programs.value = catalog.items || []
    const from = route.query.from
    if (from) {
      const task = await taskApi.detail(from)
      programKey.value = task.program_key || 'dcr_3d'
      stdinChoice.value = task.stdin_choice
      copiedFrom.value = task.id
    }
    if (programKey.value === 'dcr_3d') await loadDcrCurrent()
    else if (stdinChoice.value) await loadSourceCurrent()
  } catch {
    // 全局拦截器已提示
  }
})

async function loadDcrCurrent() {
  dcrParamsLoading.value = true
  try { dcrCurrent.value = await dcrParamsApi.current() } finally { dcrParamsLoading.value = false }
}

async function loadSourceCurrent() {
  if (!selectedChoice.value) { sourceCurrent.value = null; return }
  sourceParamsLoading.value = true
  try {
    sourceCurrent.value = await programParamsApi.current(programKey.value, selectedChoice.value.source_type)
  } finally { sourceParamsLoading.value = false }
}

function editSourceParams() {
  if (!selectedChoice.value) return
  router.push({ name: 'source-params', params: { programKey: programKey.value, sourceType: selectedChoice.value.source_type } })
}

function onProgramChange() {
  stdinChoice.value = null
  sourceCurrent.value = null
  if (isDcr.value) loadDcrCurrent()
}

function onChoiceChange() {
  choiceError.value = ''
  sourceCurrent.value = null
  loadSourceCurrent()
}


function onFileChange(uploadFile) { file.value = uploadFile.raw; fileError.value = '' }
function onFileRemove() { file.value = null }
function onFileExceed(files) {
  uploadRef.value.clearFiles(); uploadRef.value.handleStart(files[0]); file.value = files[0]; fileError.value = ''
}
async function onSubmit() {
  let valid = true
  if (isDcr.value) {
    if (!dcrCurrent.value?.sha256) { ElMessage.warning('当前 DCR 参数尚未加载，请先进入 DCR 参数页面检查并保存'); valid = false }
  } else {
    if (!stdinChoice.value) { choiceError.value = '请选择参数文件 1 或 2'; valid = false }
    else if (!sourceCurrent.value?.sha256) { ElMessage.warning('当前参数尚未加载，请先进入参数页面检查并保存'); valid = false }
  }
  if (!file.value) { fileError.value = '请选择输入数据文件'; valid = false }
  if (!valid) { ElMessage.warning('请补全并检查提交信息'); return }

  submitting.value = true
  try {
    const task = await taskApi.submit({
      programKey: programKey.value,
      params: {},
      stdinChoice: isDcr.value ? null : stdinChoice.value,
      dcrParameterSha256: isDcr.value ? dcrCurrent.value.sha256 : null,
      parameterSha256: isDcr.value ? null : sourceCurrent.value.sha256,
      meshFile: file.value,
      parameterFile: null,
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
.dcr-summary { margin-top: 16px; }
.edit-dcr { margin-top: 16px; }
.hash-text { word-break: break-all; }
.submit-row { margin-top: 24px; text-align: center; }
</style>
