<template>
  <div v-loading="loading && !loaded">
    <div class="toolbar">
      <el-button size="small" @click="load()">刷新</el-button>
      <span class="text-muted tip">每 5 秒自动刷新</span>
    </div>

    <el-divider content-position="left">活动任务（{{ running.length }}）</el-divider>
    <el-table :data="running" border size="small">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="username" label="用户" width="140" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="TASK_STATUS[row.status]?.type || 'info'" size="small">
            {{ TASK_STATUS[row.status]?.label || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="输入文件" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.input_filename || '—' }}</template>
      </el-table-column>
      <el-table-column label="开始时间" width="180">
        <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
      </el-table-column>
      <el-table-column label="已运行时长" width="130">
        <template #default="{ row }">{{ elapsedSince(row.started_at, now) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="['PREPARING', 'RUNNING'].includes(row.status)"
            size="small"
            type="danger"
            plain
            @click="onKill(row)"
          >终止</el-button>
          <span v-else class="text-muted">归档中</span>
        </template>
      </el-table-column>
      <template #empty>暂无活动任务</template>
    </el-table>

    <el-divider content-position="left">等待队列（{{ queued.length }}）</el-divider>
    <el-table :data="queued" border size="small">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="username" label="用户" width="140" />
      <el-table-column label="输入文件" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.input_filename || '—' }}</template>
      </el-table-column>
      <el-table-column label="提交时间" width="180">
        <template #default="{ row }">{{ formatTime(row.queued_at) }}</template>
      </el-table-column>
      <el-table-column label="已排队时长" width="130">
        <template #default="{ row }">{{ elapsedSince(row.queued_at, now) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="danger" plain @click="onKill(row)">终止</el-button>
        </template>
      </el-table-column>
      <template #empty>队列为空</template>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '../../api/admin'
import { elapsedSince, formatTime, TASK_STATUS } from '../../utils/format'

const running = ref([])
const queued = ref([])
const loading = ref(false)
const loaded = ref(false)
const now = ref(new Date())

let timer = null
let clockTimer = null

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 5000)
  clockTimer = setInterval(() => {
    now.value = new Date()
  }, 1000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (clockTimer) clearInterval(clockTimer)
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [r, q] = await Promise.all([adminApi.runningTasks(), adminApi.queuedTasks()])
    running.value = r
    queued.value = q
    loaded.value = true
  } catch {
    // 拦截器已提示
  } finally {
    if (!silent) loading.value = false
  }
}

async function onKill(row) {
  try {
    await ElMessageBox.confirm(
      `确定终止任务 #${row.id}（用户：${row.username}）吗？该操作不可恢复。`,
      '终止任务',
      { confirmButtonText: '终止', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await adminApi.killTask(row.id)
  ElMessage.success('已终止')
  load(true)
}
</script>

<style scoped>
.tip {
  font-size: 13px;
}
</style>
