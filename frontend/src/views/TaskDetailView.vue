<template>
  <div class="page-container">
    <el-card class="page-card" v-loading="loading && !task">
      <template #header>
        <div class="card-header">
          <span class="title">任务详情 <span v-if="task">#{{ task.id }}</span></span>
          <div v-if="task" class="header-actions">
            <el-button
              v-if="isActiveStatus(task.status)"
              type="danger"
              plain
              @click="onCancel"
            >
              取消任务
            </el-button>
            <el-button type="primary" plain @click="onResubmit">复制参数重新提交</el-button>
            <el-button @click="$router.push('/tasks')">返回列表</el-button>
          </div>
        </div>
      </template>

      <template v-if="task">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="状态">
            <StatusTag :status="task.status" />
            <span v-if="task.status === 'QUEUED' && task.queue_position !== null" class="queue-pos">
              前面还有 {{ task.queue_position }} 个任务
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="输入文件">
            {{ task.input_filename || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatTime(task.queued_at) }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(task.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(task.finished_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="task.status === 'RUNNING'" label="已运行时长">
            {{ elapsedSince(task.started_at, now) }}
          </el-descriptions-item>
          <el-descriptions-item v-else label="耗时">
            {{ formatDuration(task.duration_sec) }}
          </el-descriptions-item>
          <el-descriptions-item label="退出码">
            {{ task.exit_code === null ? '—' : task.exit_code }}
          </el-descriptions-item>
          <el-descriptions-item v-if="task.error_message" label="失败原因" :span="2">
            <span class="error-text">{{ task.error_message }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">参数快照</el-divider>
        <ParamForm :model-value="task.params" readonly />

        <el-divider content-position="left">文件下载</el-divider>
        <div class="download-row">
          <el-button :icon="Download" @click="onDownload('result')">结果文件</el-button>
          <el-button :icon="Download" @click="onDownload('stderr')">错误日志</el-button>
          <el-button :icon="Download" @click="onDownload('input')">输入文件</el-button>
          <el-button :icon="Download" @click="onDownload('params')">参数文件</el-button>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import ParamForm from '../components/ParamForm.vue'
import StatusTag from '../components/StatusTag.vue'
import { downloadTaskFile, taskApi } from '../api/tasks'
import { elapsedSince, formatDuration, formatTime, isActiveStatus } from '../utils/format'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const task = ref(null)
const loading = ref(false)
const now = ref(new Date())

let pollTimer = null
let clockTimer = null

onMounted(() => {
  load()
  pollTimer = setInterval(() => {
    if (task.value && isActiveStatus(task.value.status)) load(true)
  }, 5000)
  clockTimer = setInterval(() => {
    now.value = new Date()
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (clockTimer) clearInterval(clockTimer)
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    task.value = await taskApi.detail(taskId)
    // 已到终态则停止轮询
    if (!isActiveStatus(task.value.status) && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch {
    // 拦截器已提示
  } finally {
    if (!silent) loading.value = false
  }
}

const FALLBACK_NAMES = {
  result: 'stdout.txt',
  stderr: 'stderr.txt',
  params: 'params.in',
}

function onDownload(kind) {
  const fallback = kind === 'input' ? task.value.input_filename : FALLBACK_NAMES[kind]
  downloadTaskFile(task.value.id, kind, fallback)
}

function onResubmit() {
  router.push({ path: '/submit', query: { from: task.value.id } })
}

async function onCancel() {
  try {
    await ElMessageBox.confirm(`确定取消任务 #${task.value.id} 吗？`, '取消任务', {
      confirmButtonText: '确定取消',
      cancelButtonText: '再想想',
      type: 'warning',
    })
  } catch {
    return
  }
  await taskApi.cancel(task.value.id)
  ElMessage.success('任务已取消')
  load(true)
}
</script>

<style scoped>
.header-actions {
  display: flex;
  gap: 8px;
}

.queue-pos {
  margin-left: 12px;
  color: #909399;
  font-size: 13px;
}

.error-text {
  color: var(--el-color-danger);
}

.download-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
