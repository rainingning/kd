<template>
  <div class="dcr-page">
    <el-card class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div>
          <h2>DCR 参数工作区 <el-tag v-if="dirty" type="warning" size="small">未保存</el-tag></h2>
          <div class="meta">来源：{{ sourceLabel }}<span v-if="updatedAt"> · 更新于 {{ formatDate(updatedAt) }}</span><span v-if="baseSha"> · SHA {{ baseSha.slice(0, 12) }}</span></div>
        </div>
        <div class="actions">
          <el-upload ref="uploadRef" :auto-upload="false" :show-file-list="false" accept=".dat" :on-change="onUpload"><el-button :loading="parsing">导入 .dat</el-button></el-upload>
          <el-button :loading="loadingDefault" @click="loadDefault">载入默认</el-button>
          <el-button :disabled="!baseSha" @click="downloadCurrent">下载当前</el-button>
          <el-button type="primary" :loading="saving" :disabled="!dirty || loading" @click="save">保存</el-button>
        </div>
      </div>
      <el-alert v-for="(warning, i) in warnings" :key="i" type="warning" :title="String(warning)" :closable="false" class="warning" />
      <el-alert v-if="conflictMessage" type="error" :title="conflictMessage" :closable="false" show-icon class="warning" />
    </el-card>

    <div class="layout">
      <main v-loading="loading" class="editor"><DcrParamForm ref="formRef" v-model="document" /></main>
      <aside>
        <el-card shadow="never">
          <template #header><div class="archive-head"><span>归档版本</span><el-button link :loading="versionsLoading" @click="loadVersions">刷新</el-button></div></template>
          <el-table :data="versions" size="small" max-height="560" @row-click="loadVersion">
            <el-table-column label="任务" min-width="76"><template #default="{ row }">#{{ taskId(row) }}</template></el-table-column>
            <el-table-column label="时间" min-width="112"><template #default="{ row }">{{ formatDate(row.updated_at || row.created_at || row.archived_at) }}</template></el-table-column>
            <el-table-column label="格式" width="76"><template #default="{ row }"><el-tag :type="row.loadable ? 'success' : 'info'" size="small">{{ row.loadable ? '可载入' : '旧格式' }}</el-tag></template></el-table-column>
            <template #empty>暂无归档版本</template>
          </el-table>
          <el-pagination v-if="versionsTotal > pageSize" small layout="prev, pager, next" :total="versionsTotal" :page-size="pageSize" v-model:current-page="page" @current-change="loadVersions" />
          <div class="archive-tip">点击版本载入编辑器；保存时会记录来源任务。</div>
        </el-card>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import DcrParamForm from '../components/DcrParamForm.vue'
import { dcrParamsApi } from '../api/dcrParams'

const route = useRoute()
const document = ref({})
const baseSha = ref('')
const updatedAt = ref('')
const source = ref('current')
const sourceTaskId = ref(null)
const warnings = ref([])
const loading = ref(false)
const saving = ref(false)
const parsing = ref(false)
const loadingDefault = ref(false)
const dirty = ref(false)
const conflictMessage = ref('')
const formRef = ref()
const uploadRef = ref()
const versions = ref([])
const versionsTotal = ref(0)
const versionsLoading = ref(false)
const page = ref(1)
const pageSize = 20
let acceptingDocument = false

const sourceLabel = computed(() => sourceTaskId.value ? `归档任务 #${sourceTaskId.value}` : ({ current: '当前工作区', default: '系统默认', upload: '上传文件' })[source.value] || source.value || '—')
watch(document, () => { if (!acceptingDocument) { dirty.value = true; conflictMessage.value = '' } }, { deep: true })

onMounted(async () => {
  window.addEventListener('beforeunload', beforeUnload)
  await Promise.all([loadCurrent(), loadVersions()])
  if (route.query.task_id) await loadVersion({ task_id: route.query.task_id, loadable: true })
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
onBeforeRouteLeave(async () => { if (!dirty.value) return true; try { await ElMessageBox.confirm('参数尚未保存，确定离开吗？', '未保存更改', { type: 'warning', confirmButtonText: '离开', cancelButtonText: '继续编辑' }); return true } catch { return false } })

function clone(value) { return JSON.parse(JSON.stringify(value || {})) }
function accept(payload, kind, taskId = null, markDirty = true) {
  acceptingDocument = true
  document.value = clone(payload.document ?? payload)
  source.value = payload.source || kind
  sourceTaskId.value = taskId
  warnings.value = Array.isArray(payload.warnings) ? payload.warnings : []
  updatedAt.value = payload.updated_at || updatedAt.value
  dirty.value = markDirty
  conflictMessage.value = ''
  formRef.value?.setServerErrors(null)
  requestAnimationFrame(() => { acceptingDocument = false })
}
async function loadCurrent() { loading.value = true; try { const data = await dcrParamsApi.current(); baseSha.value = data.sha256 || ''; updatedAt.value = data.updated_at || ''; accept(data, 'current', null, false) } finally { loading.value = false } }
async function loadDefault() { if (!(await confirmOverwrite())) return; loadingDefault.value = true; try { accept(await dcrParamsApi.defaults(), 'default', null, true); ElMessage.success('已载入默认参数，保存后才会写入当前工作区') } finally { loadingDefault.value = false } }
async function onUpload(uploadFile) {
  const file = uploadFile.raw
  uploadRef.value?.clearFiles()
  if (!file || !file.name.toLowerCase().endsWith('.dat')) { ElMessage.warning('只能导入 .dat 文件'); return }
  if (!(await confirmOverwrite())) return
  parsing.value = true
  try { accept(await dcrParamsApi.parse(file), 'upload', null, true); ElMessage.success('文件解析成功，请检查后保存') } finally { parsing.value = false }
}
async function loadVersions() { versionsLoading.value = true; try { const data = await dcrParamsApi.versions({ page: page.value, page_size: pageSize }); versions.value = data.items || []; versionsTotal.value = data.total || 0 } finally { versionsLoading.value = false } }
async function loadVersion(row) { if (row.loadable === false) { ElMessage.info('该历史任务是旧占位格式，只能在任务详情下载原文件'); return } if (!(await confirmOverwrite())) return; const id = taskId(row); if (id === null) return; loading.value = true; try { accept(await dcrParamsApi.version(id), 'archive', id, true); ElMessage.success(`已载入任务 #${id} 的归档版本`) } finally { loading.value = false } }
function taskId(row) { return row.task_id ?? row.taskId ?? row.id ?? null }
async function save() {
  conflictMessage.value = ''
  if (!formRef.value?.validate()) { ElMessage.warning('请修正表单错误后再保存'); return }
  saving.value = true
  try {
    const data = await dcrParamsApi.save(document.value, baseSha.value, sourceTaskId.value)
    baseSha.value = data.sha256 || baseSha.value
    updatedAt.value = data.updated_at || new Date().toISOString()
    source.value = data.source || 'current'; sourceTaskId.value = null; warnings.value = data.warnings || []; dirty.value = false
    ElMessage.success('DCR 参数已保存')
    loadVersions()
  } catch (error) {
    const detail = error?.response?.data?.detail
    const code = typeof detail === 'object' ? detail.code : null
    if (error?.response?.status === 409 && code === 'workspace_busy') conflictMessage.value = '工作区正在被其他操作占用，请稍后重试；你的编辑内容已保留。'
    else if (error?.response?.status === 409 && code === 'stale_revision') conflictMessage.value = '当前版本已被他人更新。你的编辑内容已保留；请先下载或复制内容，再刷新页面获取最新版本。'
    else { const fieldErrors = detail?.errors || detail?.fields || (error?.response?.status === 422 ? detail : null); if (fieldErrors) { formRef.value?.setServerErrors(fieldErrors); ElMessage.error('服务器校验未通过，请检查标红字段') } else ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '保存失败，编辑内容已保留') }
  } finally { saving.value = false }
}
async function confirmOverwrite() { if (!dirty.value) return true; try { await ElMessageBox.confirm('载入其他参数会覆盖当前未保存编辑，是否继续？', '覆盖编辑内容', { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' }); return true } catch { return false } }
function beforeUnload(event) { if (!dirty.value) return; event.preventDefault(); event.returnValue = '' }
async function downloadCurrent() {
  try { const response = await dcrParamsApi.downloadCurrent(); const disposition = response.headers?.['content-disposition'] || ''; const match = disposition.match(/filename\*?=(?:UTF-8''|["']?)([^"';]+)/i); const name = match ? decodeURIComponent(match[1].replace(/["']/g, '')) : 'dcr_params_current.dat'; const url = URL.createObjectURL(response.data); const link = window.document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url) } catch { /* interceptor handles */ }
}
function formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString() }
</script>

<style scoped>
.dcr-page { max-width: 1480px; margin: 0 auto; padding: 20px; }.toolbar-card { margin-bottom: 18px; }.toolbar,.actions,.archive-head { display:flex; justify-content:space-between; align-items:center; gap:12px; }.toolbar h2 { margin:0 0 6px; font-size:22px; }.meta,.archive-tip { color:#909399; font-size:12px; }.actions { flex-wrap:wrap; justify-content:flex-end; }.warning { margin-top:12px; }.layout { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:18px; align-items:start; }.editor { min-height:300px; }.archive-head { font-weight:600; }.archive-tip { margin-top:12px; line-height:1.5; }.el-pagination { margin-top:14px; justify-content:center; }
@media (max-width: 980px) { .layout { grid-template-columns:1fr; }.toolbar { align-items:flex-start; flex-direction:column; }.actions { justify-content:flex-start; } }
@media (max-width: 640px) { .dcr-page { padding:10px; }.actions { width:100%; }.actions :deep(.el-button) { margin-left:0; } }
</style>
