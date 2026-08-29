<template>
  <div>
    <el-alert
      type="warning"
      title="归档失败时用户固定工作区会保持现场，下一任务不会覆盖。请修复磁盘、权限等原因后重试。"
      :closable="false"
      class="panel-alert"
    />
    <AdminPanelControls label="归档异常刷新">
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </AdminPanelControls>
    <div class="admin-archive-table-wrap">
    <el-table v-loading="loading" :data="items" border>
      <el-table-column prop="id" label="任务 ID" width="100" />
      <el-table-column prop="user_id" label="用户 ID" width="100" />
      <el-table-column prop="terminal_status" label="目标终态" width="110" />
      <el-table-column prop="archive_version" label="归档版本" min-width="220" />
      <el-table-column prop="archive_retry_count" label="重试次数" width="100" />
      <el-table-column label="下次自动重试" width="180">
        <template #default="{ row }">{{ formatTime(row.archive_retry_at) }}</template>
      </el-table-column>
      <el-table-column prop="archive_error" label="失败原因" min-width="260" show-overflow-tooltip />
      <el-table-column label="提交时间" width="180">
        <template #default="{ row }">{{ formatTime(row.queued_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" :loading="retrying === row.id" @click="retry(row)">
            重试归档
          </el-button>
        </template>
      </el-table-column>
      <template #empty>当前没有归档失败任务</template>
    </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi } from '../../api/admin'
import { formatTime } from '../../utils/format'
import AdminPanelControls from './AdminPanelControls.vue'

const items = ref([])
const loading = ref(false)
const retrying = ref(null)

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await adminApi.archiveFailures()
  } finally {
    loading.value = false
  }
}

async function retry(row) {
  retrying.value = row.id
  try {
    const result = await adminApi.retryArchive(row.id)
    if (result.archive_status === 'COMPLETED') {
      ElMessage.success(`任务 #${row.id} 归档成功`)
    } else {
      ElMessage.warning(`任务 #${row.id} 仍未完成归档：${result.archive_error || result.status}`)
    }
    await load()
  } finally {
    retrying.value = null
  }
}
</script>

<style scoped>
.panel-alert {
  margin-bottom: 16px;
}

.admin-archive-table-wrap {
  position: relative;
  z-index: auto;
  clear: both;
  width: 100%;
  min-width: 0;
}
</style>
