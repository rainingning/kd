<template>
  <div v-loading="loading">
    <el-alert
      :type="template?.status === 'ready' ? 'info' : 'error'"
      :title="template?.status === 'ready'
        ? '三个程序的同步与任务执行共用用户工作区锁；运行或归档中的用户将自动延期同步。'
        : '至少一个程序模板不可用，请先修复模板文件和 SHA-256。'"
      :closable="false"
      class="panel-alert"
    />

    <el-table :data="programRows" border>
      <el-table-column prop="name" label="科学计算程序" min-width="210" />
      <el-table-column prop="executable" label="可执行文件" min-width="230" />
      <el-table-column label="模板状态" width="110">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ready' ? 'success' : 'danger'">
            {{ row.status === 'ready' ? '校验通过' : '不可用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="150" />
      <el-table-column label="同步用户" width="110">
        <template #default="{ row }">{{ row.synced ?? 0 }} / {{ row.total ?? 0 }}</template>
      </el-table-column>
      <el-table-column prop="deferred" label="延期" width="80" />
      <el-table-column prop="failed" label="失败" width="80" />
      <el-table-column prop="error" label="说明" min-width="240" show-overflow-tooltip />
      <el-table-column label="exe SHA-256" min-width="280" show-overflow-tooltip>
        <template #default="{ row }"><code>{{ row.exe_sha256 || '—' }}</code></template>
      </el-table-column>
    </el-table>

    <div class="actions">
      <el-button :icon="Refresh" @click="load">刷新状态</el-button>
      <el-button type="primary" :disabled="template?.status !== 'ready'" :loading="syncing" @click="syncAll">
        批量同步全部用户和程序
      </el-button>
    </div>

    <el-table v-if="lastResult?.items" :data="lastResult.items" border size="small" class="result-table">
      <el-table-column prop="user_id" label="用户 ID" width="100" />
      <el-table-column prop="status" label="结果" width="110" />
      <el-table-column prop="error" label="说明" min-width="260" />
    </el-table>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi } from '../../api/admin'

const loading = ref(false)
const syncing = ref(false)
const template = ref(null)
const syncStatus = ref(null)
const lastResult = ref(null)

const programRows = computed(() => {
  const statusByKey = Object.fromEntries((syncStatus.value?.programs || []).map((item) => [item.program_key, item]))
  return (template.value?.programs || []).map((item) => ({
    ...statusByKey[item.program_key],
    ...item,
    executable: item.exe,
  }))
})

onMounted(load)
async function load() {
  loading.value = true
  try {
    const [tpl, status] = await Promise.all([adminApi.programTemplate(), adminApi.programSyncStatus()])
    template.value = tpl
    syncStatus.value = status
  } finally { loading.value = false }
}

async function syncAll() {
  try {
    await ElMessageBox.confirm(
      '确定把三个程序模板同步到全部用户吗？运行中的用户会自动延期。',
      '批量同步程序',
      { confirmButtonText: '开始同步', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  syncing.value = true
  try {
    lastResult.value = await adminApi.syncAllPrograms()
    ElMessage.success(`同步完成：成功 ${lastResult.value.synced}，延期 ${lastResult.value.deferred}，失败 ${lastResult.value.failed}`)
    await load()
  } finally { syncing.value = false }
}
</script>

<style scoped>
.panel-alert { margin-bottom: 16px; }
.actions { display: flex; gap: 10px; margin-top: 20px; }
.result-table { margin-top: 20px; }
code { overflow-wrap: anywhere; }
</style>
