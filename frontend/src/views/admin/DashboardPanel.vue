<template>
  <div v-loading="loading && !data">
    <template v-if="data">
      <div class="stat-cards">
        <el-card class="stat-card" shadow="hover">
          <div class="text-muted">总用户数</div>
          <div class="stat-value">{{ data.total_users }}</div>
        </el-card>
        <el-card class="stat-card" shadow="hover">
          <div class="text-muted">活跃用户（运行中任务）</div>
          <div class="stat-value">{{ data.active_users }}</div>
        </el-card>
        <el-card class="stat-card" shadow="hover">
          <div class="text-muted">运行中任务</div>
          <div class="stat-value running">{{ data.running_tasks }}</div>
        </el-card>
        <el-card class="stat-card" shadow="hover">
          <div class="text-muted">排队任务</div>
          <div class="stat-value queued">{{ data.queued_tasks }}</div>
        </el-card>
      </div>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span class="title">资源使用率</span>
            <span class="text-muted tip">每 5 秒自动刷新</span>
          </div>
        </template>
        <div class="progress-row">
          <span class="progress-label">CPU</span>
          <el-progress
            :percentage="round(data.cpu_percent)"
            :status="statusOf(data.cpu_percent)"
            :stroke-width="16"
          />
        </div>
        <div class="progress-row">
          <span class="progress-label">内存</span>
          <el-progress
            :percentage="round(data.memory_percent)"
            :status="statusOf(data.memory_percent)"
            :stroke-width="16"
          />
        </div>
        <div class="progress-row">
          <span class="progress-label">磁盘</span>
          <el-progress
            :percentage="round(data.disk_percent)"
            :status="statusOf(data.disk_percent)"
            :stroke-width="16"
          />
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { adminApi } from '../../api/admin'

const data = ref(null)
const loading = ref(false)

let timer = null
onMounted(() => {
  load()
  timer = setInterval(() => load(true), 5000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    data.value = await adminApi.dashboard()
  } catch {
    // 拦截器已提示
  } finally {
    if (!silent) loading.value = false
  }
}

function round(v) {
  return Math.min(100, Math.max(0, Math.round(v)))
}

function statusOf(v) {
  if (v >= 90) return 'exception'
  if (v >= 70) return 'warning'
  return 'success'
}
</script>

<style scoped>
.stat-value.running {
  color: var(--el-color-primary);
}

.stat-value.queued {
  color: var(--el-color-warning);
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}

.progress-row:last-child {
  margin-bottom: 0;
}

.progress-label {
  width: 40px;
  color: #606266;
}

.progress-row :deep(.el-progress) {
  flex: 1;
}

.tip {
  font-size: 13px;
}
</style>
