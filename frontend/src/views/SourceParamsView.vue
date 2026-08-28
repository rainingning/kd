<template>
  <div class="params-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="title-row">
        <div>
          <h2>BE / FDEM 源参数 <el-tag v-if="dirty" type="warning" size="small">未保存</el-tag></h2>
          <div class="meta">{{ contextLabel }} · {{ filename || expectedFilename }}<span v-if="sourceLabel"> · 来源：{{ sourceLabel }}</span><span v-if="updatedAt"> · {{ formatDate(updatedAt) }}</span><span v-if="baseSha"> · SHA {{ baseSha.slice(0, 12) }}</span></div>
        </div>
        <div class="selectors">
          <el-select :model-value="programKey" aria-label="计算程序" @change="changeContext($event, sourceType)">
            <el-option v-for="item in programs" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-radio-group :model-value="sourceType" @change="changeContext(programKey, $event)">
            <el-radio-button value="grounded_wire">Grounded wire</el-radio-button>
            <el-radio-button value="loop">Loop</el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <div class="actions">
        <el-upload ref="uploadRef" :auto-upload="false" :show-file-list="false" accept=".dat" :on-change="onUpload"><el-button :loading="parsing">导入 .dat</el-button></el-upload>
        <el-button :loading="loadingDefault" @click="loadDefault">载入默认</el-button>
        <el-button :disabled="!baseSha" @click="downloadCurrent">下载当前</el-button>
        <el-button type="primary" :loading="saving" :disabled="!dirty || loading" @click="save">保存当前</el-button>
      </div>
      <el-alert v-for="(warning, index) in warnings" :key="index" type="warning" :title="String(warning)" :closable="false" class="notice" />
      <el-alert v-if="conflictMessage" type="error" :title="conflictMessage" :closable="false" show-icon class="notice" />
    </el-card>

    <div class="page-grid">
      <main v-loading="loading" class="editor">
        <SourceParamForm ref="formRef" v-model="document" :program-key="programKey" :source-type="sourceType" :errors="serverErrors" />
      </main>
      <aside>
        <el-card shadow="never">
          <template #header><div class="history-head"><span>历史任务版本</span><el-button link :loading="versionsLoading" @click="loadVersions">刷新</el-button></div></template>
          <el-table :data="versions" size="small" max-height="560" highlight-current-row @row-click="loadVersion">
            <el-table-column label="任务" min-width="70"><template #default="{ row }">#{{ taskId(row) }}</template></el-table-column>
            <el-table-column label="归档时间" min-width="112"><template #default="{ row }">{{ formatDate(row.archived_at || row.updated_at || row.created_at) }}</template></el-table-column>
            <el-table-column label="格式" width="72"><template #default="{ row }"><el-tag :type="row.loadable === false ? 'info' : 'success'" size="small">{{ row.loadable === false ? '旧格式' : '可载入' }}</el-tag></template></el-table-column>
            <template #empty>暂无归档版本</template>
          </el-table>
          <el-pagination v-if="versionsTotal > pageSize" v-model:current-page="page" small layout="prev, pager, next" :total="versionsTotal" :page-size="pageSize" @current-change="loadVersions" />
          <div class="history-tip">点击可载入版本进行编辑；保存只更新当前工作区，不修改历史归档。</div>
        </el-card>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import SourceParamForm from '../components/SourceParamForm.vue'
import { programParamsApi } from '../api/programParams'

const programs = [
  { value: 'be_fetd', label: 'BE_FETD' },
  { value: 'fdem3d_frequency_domain', label: 'FDEM3D Frequency Domain' },
]
const sourceTypes = ['grounded_wire', 'loop']
const route = useRoute()
const router = useRouter()
const document = ref({})
const baseSha = ref('')
const updatedAt = ref('')
const filename = ref('')
const origin = ref('current')
const sourceTaskId = ref(null)
const warnings = ref([])
const serverErrors = ref([])
const dirty = ref(false)
const conflictMessage = ref('')
const loading = ref(false)
const parsing = ref(false)
const loadingDefault = ref(false)
const saving = ref(false)
const versionsLoading = ref(false)
const versions = ref([])
const versionsTotal = ref(0)
const page = ref(1)
const pageSize = 20
const formRef = ref()
const uploadRef = ref()
let accepting = false

const programKey = computed(() => programs.some(item => item.value === route.params.programKey) ? route.params.programKey : 'be_fetd')
const sourceType = computed(() => sourceTypes.includes(route.params.sourceType) ? route.params.sourceType : 'grounded_wire')
const contextLabel = computed(() => `${programs.find(item => item.value === programKey.value)?.label} / ${sourceType.value === 'loop' ? 'Loop 回线源' : 'Grounded wire 接地导线源'}`)
const expectedFilename = computed(() => sourceType.value === 'loop' ? 'LoopSource.dat' : 'GroundedWireSource.dat')
const sourceLabel = computed(() => sourceTaskId.value ? `归档任务 #${sourceTaskId.value}` : ({ current: '当前工作区', default: '系统默认', upload: '上传文件' })[origin.value] || '')

watch(document, () => { if (!accepting) { dirty.value = true; conflictMessage.value = ''; serverErrors.value = [] } }, { deep: true })

function clone(value) { return JSON.parse(JSON.stringify(value || {})) }
function accept(payload, kind, taskIdValue = null) {
  accepting = true
  document.value = clone(payload.document)
  if (kind === 'current') baseSha.value = payload.sha256 || baseSha.value
  else if (payload.current_sha256) baseSha.value = payload.current_sha256
  updatedAt.value = payload.updated_at || payload.archived_at || ''
  filename.value = payload.filename || expectedFilename.value
  warnings.value = payload.warnings || []
  serverErrors.value = []
  origin.value = kind
  sourceTaskId.value = taskIdValue
  conflictMessage.value = ''
  dirty.value = kind !== 'current'
  queueMicrotask(() => { accepting = false })
}

async function loadCurrent() {
  loading.value = true
  baseSha.value = ''
  filename.value = ''
  updatedAt.value = ''
  sourceTaskId.value = null
  try { accept(await programParamsApi.current(programKey.value, sourceType.value), 'current'); await maybeLoadTaskFromQuery() }
  catch { document.value = {}; dirty.value = false }
  finally { loading.value = false }
}
async function loadDefault() {
  if (!(await confirmReplace())) return
  loadingDefault.value = true
  try { accept(await programParamsApi.defaults(programKey.value, sourceType.value), 'default') }
  finally { loadingDefault.value = false }
}
async function onUpload(uploadFile) {
  const file = uploadFile.raw
  uploadRef.value?.clearFiles()
  if (!file || !(await confirmReplace())) return
  if (!file.name.toLowerCase().endsWith('.dat')) { ElMessage.warning('请选择 .dat 参数文件'); return }
  parsing.value = true
  try { accept(await programParamsApi.parse(programKey.value, sourceType.value, file), 'upload'); ElMessage.success('参数已载入表单，确认后请点击保存') }
  finally { parsing.value = false }
}
async function save() {
  serverErrors.value = []
  if (!formRef.value?.validate()) { ElMessage.warning('请先修正表单中的参数错误'); return }
  saving.value = true
  try {
    const payload = await programParamsApi.save(programKey.value, sourceType.value, document.value, baseSha.value, sourceTaskId.value)
    accept(payload, 'current')
    ElMessage.success(`${expectedFilename.value} 已保存到当前工作区`)
    await loadVersions()
  } catch (error) {
    const detail = error?.response?.data?.detail
    const code = detail?.code
    if (code === 'stale_revision') conflictMessage.value = '当前参数已被其他页面更新。你的编辑仍保留；请另行备份或刷新当前版本后重新编辑。'
    else if (code === 'workspace_busy') conflictMessage.value = '程序工作区正在运行、归档或同步，暂不能保存。你的编辑已保留，请稍后重试。'
    else {
      const fields = detail?.errors || detail?.field_errors || (typeof detail === 'object' && !detail.code ? detail : [])
      serverErrors.value = fields
      ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '保存失败，请检查参数')
    }
  } finally { saving.value = false }
}
async function downloadCurrent() {
  const response = await programParamsApi.downloadCurrent(programKey.value, sourceType.value)
  const blob = response.data instanceof Blob ? response.data : new Blob([response.data])
  const disposition = response.headers?.['content-disposition'] || ''
  const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i)
  const name = match ? decodeURIComponent(match[1].replace(/\"/g, '')) : expectedFilename.value
  const url = URL.createObjectURL(blob); const anchor = window.document.createElement('a'); anchor.href = url; anchor.download = name; anchor.click(); URL.revokeObjectURL(url)
}
async function loadVersions() {
  versionsLoading.value = true
  try {
    const payload = await programParamsApi.versions(programKey.value, sourceType.value, { page: page.value, page_size: pageSize })
    versions.value = payload.items || payload.versions || (Array.isArray(payload) ? payload : [])
    versionsTotal.value = payload.total ?? versions.value.length
  } finally { versionsLoading.value = false }
}
function taskId(row) { return row.task_id ?? row.id }
async function loadVersion(row) {
  if (row.loadable === false) { ElMessage.info('该历史任务使用旧参数格式，只能下载，不能载入表单'); return }
  if (!(await confirmReplace())) return
  try { const id = taskId(row); accept(await programParamsApi.version(programKey.value, sourceType.value, id), 'archive', id); ElMessage.success(`已载入任务 #${id}，历史归档不会被修改`) }
  catch { /* 全局拦截器显示错误 */ }
}
async function maybeLoadTaskFromQuery() {
  const id = route.query.task_id
  if (!id) return
  try { accept(await programParamsApi.version(programKey.value, sourceType.value, id), 'archive', id) }
  catch { /* 保留当前版本 */ }
}
async function confirmReplace() {
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('当前参数尚未保存，继续将丢失这些编辑。', '未保存提醒', { confirmButtonText: '放弃编辑', cancelButtonText: '继续编辑', type: 'warning' }); return true }
  catch { return false }
}
function changeContext(nextProgram, nextSource) {
  if (nextProgram === programKey.value && nextSource === sourceType.value) return
  router.push({ name: 'source-params', params: { programKey: nextProgram, sourceType: nextSource } })
}
function formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false }) }
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }

onBeforeRouteUpdate(async (to) => {
  if (to.params.programKey === route.params.programKey && to.params.sourceType === route.params.sourceType) return true
  if (!(await confirmReplace())) return false
  return true
})
onBeforeRouteLeave(async () => dirty.value ? confirmReplace() : true)
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); loadCurrent(); loadVersions() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
watch(() => [route.params.programKey, route.params.sourceType], () => { page.value = 1; loadCurrent(); loadVersions() })
</script>

<style scoped>
.params-page { max-width:1480px; margin:0 auto; padding:20px; }.toolbar-card { margin-bottom:18px; }.title-row,.actions,.selectors,.history-head { display:flex; justify-content:space-between; align-items:center; gap:12px; }.title-row h2 { margin:0 0 6px; font-size:22px; }.meta,.history-tip { color:#909399; font-size:12px; }.selectors { flex-wrap:wrap; justify-content:flex-end; }.selectors :deep(.el-select) { width:250px; }.actions { margin-top:16px; flex-wrap:wrap; justify-content:flex-end; }.notice { margin-top:12px; }.page-grid { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:18px; align-items:start; }.editor { min-height:320px; }.history-head { font-weight:600; }.history-tip { margin-top:12px; line-height:1.55; }.el-pagination { margin-top:14px; justify-content:center; }
@media (max-width:980px) { .page-grid { grid-template-columns:1fr; }.title-row { flex-direction:column; align-items:flex-start; }.selectors { justify-content:flex-start; } }
@media (max-width:640px) { .params-page { padding:10px; }.selectors,.actions { width:100%; justify-content:flex-start; }.selectors :deep(.el-select) { width:100%; } }
</style>
