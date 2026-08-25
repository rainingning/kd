<template>
  <div class="page-container">
    <el-card class="page-card" v-loading="loading && !task">
      <template #header>
        <div class="card-header">
          <span class="title">任务详情 <span v-if="task">#{{ task.id }}</span></span>
          <div v-if="task" class="header-actions">
            <el-button
              v-if="isCancelableStatus(task.status)"
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
          <el-descriptions-item label="归档状态">
            {{ archiveStatusLabel(task.archive_status) }}
          </el-descriptions-item>
          <el-descriptions-item label="归档版本">
            {{ task.archive_version || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="程序版本">
            {{ task.program_version || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="结果规模">
            {{ resultSummary(task) }}
          </el-descriptions-item>
          <el-descriptions-item v-if="task.error_message" label="任务说明" :span="2">
            <span :class="{ 'error-text': task.status === 'FAILED' }">{{ task.error_message }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="task.archive_error" label="归档错误" :span="2">
            <span class="error-text">{{ task.archive_error }}</span>
            <span v-if="task.archive_retry_count" class="retry-text">
              （已重试 {{ task.archive_retry_count }} 次，下次：{{ formatTime(task.archive_retry_at) }}）
            </span>
          </el-descriptions-item>
          <el-descriptions-item v-if="task.exe_sha256" label="DCR_3D.exe SHA-256" :span="2">
            <code class="hash-text">{{ task.exe_sha256 }}</code>
          </el-descriptions-item>
          <el-descriptions-item v-if="task.dll_sha256" label="libiomp5md.dll SHA-256" :span="2">
            <code class="hash-text">{{ task.dll_sha256 }}</code>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="task.status === 'ARCHIVE_FAILED'"
          type="error"
          title="结果归档失败。平台会自动重试；在归档成功前，该用户的下一任务不会覆盖当前工作区。"
          :closable="false"
          class="archive-alert"
        />

        <el-divider content-position="left">参数快照</el-divider>
        <ParamForm :model-value="task.params" readonly />

        <el-divider content-position="left">文件下载</el-divider>
        <div class="download-row">
          <el-button :icon="Download" :disabled="!archiveReady" @click="onDownload('result')">
            结果目录 ZIP
          </el-button>
          <el-button :icon="Download" :disabled="!archiveReady" @click="onDownload('stdout')">
            标准输出日志
          </el-button>
          <el-button :icon="Download" :disabled="!archiveReady" @click="onDownload('stderr')">
            错误日志
          </el-button>
          <el-button :icon="Download" :disabled="!archiveReady" @click="onDownload('input')">
            输入文件
          </el-button>
          <el-button :icon="Download" :disabled="!archiveReady" @click="onDownload('params')">
            参数文件
          </el-button>
          <span v-if="!archiveReady" class="text-muted">归档完成后可下载</span>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import ParamForm from '../components/ParamForm.vue'
import StatusTag from '../components/StatusTag.vue'
import { downloadTaskFile, taskApi } from '../api/tasks'
import {
  elapsedSince,
  formatDuration,
  formatTime,
  isActiveStatus,
  isCancelableStatus,
} from '../utils/format'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const task = ref(null)
const loading = ref(false)
const now = ref(new Date())
const archiveReady = computed(() => task.value?.archive_status === 'COMPLETED')

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
  result: `task_${taskId}_Forward_data.zip`,
  stdout: 'stdout.txt',
  stderr: 'stderr.txt',
  params: 'model_DC.dat',
}

function archiveStatusLabel(status) {
  return {
    PENDING: '等待归档',
    ARCHIVING: '正在归档',
    COMPLETED: '归档完成',
    FAILED: '归档失败',
  }[status] || status || '—'
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function resultSummary(value) {
  if (value.result_file_count === null || value.result_file_count === undefined) return '—'
  return `${value.result_file_count} 个文件，${formatBytes(value.result_size_bytes)}`
}

function onDownload(kind) {
  const fallback = kind === 'input' ? (task.value.input_filename || 'mesh.mphtxt') : FALLBACK_NAMES[kind]
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

.hash-text {
  overflow-wrap: anywhere;
}

.retry-text {
  margin-left: 8px;
  color: #909399;
}

.archive-alert {
  margin-top: 16px;
}

.download-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
