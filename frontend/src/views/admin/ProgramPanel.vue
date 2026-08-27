<template>
  <div v-loading="loading">
    <el-alert
      v-if="template?.status === 'error'"
      type="error"
      :title="`程序模板不可用：${template.error}`"
      :closable="false"
      class="panel-alert"
    />
    <el-alert
      v-else
      type="info"
      title="程序同步与任务执行共用用户工作区锁；运行或归档中的用户将自动延期同步。"
      :closable="false"
      class="panel-alert"
    />

    <el-descriptions v-if="template" :column="2" border>
      <el-descriptions-item label="模板状态">
        <el-tag :type="template.status === 'ready' ? 'success' : 'danger'">
          {{ template.status === 'ready' ? '校验通过' : '不可用' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="模板版本">{{ template.version || '—' }}</el-descriptions-item>
      <el-descriptions-item label="DCR_3D.exe SHA-256" :span="2">
        <code class="hash">{{ template.exe_sha256 || '—' }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="libiomp5md.dll SHA-256" :span="2">
        <code class="hash">{{ template.dll_sha256 || '—' }}</code>
      </el-descriptions-item>
    </el-descriptions>

    <div v-if="syncStatus" class="stats">
      <el-statistic title="用户总数" :value="syncStatus.total" />
      <el-statistic title="已同步" :value="syncStatus.synced" />
      <el-statistic title="待同步" :value="syncStatus.pending" />
      <el-statistic title="运行中延期" :value="syncStatus.deferred" />
      <el-statistic title="同步失败" :value="syncStatus.failed" />
      <el-statistic title="同步中" :value="syncStatus.syncing" />
    </div>

    <div class="actions">
      <el-button :icon="Refresh" @click="load">刷新状态</el-button>
      <el-button
        type="primary"
        :disabled="template?.status !== 'ready'"
        :loading="syncing"
        @click="syncAll"
      >
        批量同步全部用户
      </el-button>
    </div>

    <el-table v-if="lastResult?.items" :data="lastResult.items" border size="small" class="result-table">
      <el-table-column prop="user_id" label="用户 ID" width="100" />
      <el-table-column label="结果" width="110">
        <template #default="{ row }">
          <el-tag :type="resultType(row.status)">{{ resultLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="程序版本" width="140" />
      <el-table-column prop="error" label="说明" min-width="260" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi } from '../../api/admin'

const loading = ref(false)
const syncing = ref(false)
const template = ref(null)
const syncStatus = ref(null)
const lastResult = ref(null)

onMounted(load)

async function load() {
  loading.value = true
  try {
    const [tpl, status] = await Promise.all([
      adminApi.programTemplate(),
      adminApi.programSyncStatus(),
    ])
    template.value = tpl
    syncStatus.value = status
  } finally {
    loading.value = false
  }
}

async function syncAll() {
  try {
    await ElMessageBox.confirm(
      '确定把当前程序模板同步到全部用户吗？运行中的用户会自动延期。',
      '批量同步程序',
      { confirmButtonText: '开始同步', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  syncing.value = true
  try {
    lastResult.value = await adminApi.syncAllPrograms()
    ElMessage.success(
      `同步完成：成功 ${lastResult.value.synced}，延期 ${lastResult.value.deferred}，失败 ${lastResult.value.failed}`,
    )
    await load()
  } finally {
    syncing.value = false
  }
}

function resultLabel(status) {
  return { synced: '已同步', deferred: '已延期', failed: '失败', missing: '不存在' }[status] || status
}

function resultType(status) {
  return { synced: 'success', deferred: 'warning', failed: 'danger', missing: 'info' }[status] || 'info'
}
</script>

<style scoped>
.panel-alert {
  margin-bottom: 16px;
}

.hash {
  overflow-wrap: anywhere;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
  margin: 20px 0;
}

.actions {
  display: flex;
  gap: 10px;
}

.result-table {
  margin-top: 20px;
}
</style>
