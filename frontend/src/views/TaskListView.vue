<template>
  <div class="page-container">
    <el-card class="page-card task-list-card">
      <template #header>
        <div class="card-header">
          <span class="title">任务列表</span>
        </div>
      </template>

      <section class="task-list-controls" aria-label="任务列表过滤和刷新">
        <el-select
          v-model="statusFilter"
          class="task-list-status-filter"
          placeholder="全部状态"
          clearable
          @change="onFilterChange"
        >
          <el-option v-for="(meta, s) in TASK_STATUS" :key="s" :label="meta.label" :value="s" />
        </el-select>
        <el-button class="task-list-refresh-button" :icon="Refresh" @click="load()">刷新</el-button>
        <span class="task-list-refresh-tip">每 5 秒自动刷新</span>
      </section>

      <div class="task-list-table-wrap">
        <el-table v-loading="loading" :data="items" border @row-click="onRowClick" row-class-name="task-row">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="程序" min-width="190">
          <template #default="{ row }">{{ programLabel(row.program_key) }}</template>
        </el-table-column>
        <el-table-column label="参数选择" width="120">
          <template #default="{ row }">{{ row.stdin_choice ? `${row.stdin_choice} — ${row.source_type}` : '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <StatusTag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column prop="input_filename" label="输入文件" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.input_filename || '—' }}</template>
        </el-table-column>
        <el-table-column label="提交时间" width="180">
          <template #default="{ row }">{{ formatTime(row.queued_at) }}</template>
        </el-table-column>
        <el-table-column label="开始时间" width="180">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="120">
          <template #default="{ row }">{{ formatDuration(row.duration_sec) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click.stop="goDetail(row)">详情</el-button>
            <el-button
              v-if="isCancelableStatus(row.status)"
              size="small"
              type="danger"
              plain
              @click.stop="onCancel(row)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
          <template #empty>暂无任务</template>
        </el-table>
      </div>

      <div class="task-list-pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load()"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import StatusTag from '../components/StatusTag.vue'
import { taskApi } from '../api/tasks'
import { TASK_STATUS, formatDuration, formatTime, isCancelableStatus } from '../utils/format'

const router = useRouter()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref('')
const loading = ref(false)

function programLabel(key) {
  return {
    dcr_3d: 'DCR_3D',
    be_fetd: 'BE_FETD',
    fdem3d_frequency_domain: 'FDEM3D_Frequency_Domain',
  }[key] || key || '—'
}

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
    const data = await taskApi.list({
      status: statusFilter.value || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    items.value = data.items
    total.value = data.total
    // 过滤/取消后当前页可能变空，回退一页
    if (data.items.length === 0 && page.value > 1) {
      page.value -= 1
      return load(true)
    }
  } catch {
    // 拦截器已提示
  } finally {
    if (!silent) loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  load()
}

function onSizeChange() {
  page.value = 1
  load()
}

function onRowClick(row) {
  goDetail(row)
}

function goDetail(row) {
  router.push(`/tasks/${row.id}`)
}

async function onCancel(row) {
  try {
    await ElMessageBox.confirm(`确定取消任务 #${row.id} 吗？`, '取消任务', {
      confirmButtonText: '确定取消',
      cancelButtonText: '再想想',
      type: 'warning',
    })
  } catch {
    return
  }
  await taskApi.cancel(row.id)
  ElMessage.success('任务已取消')
  load(true)
}
</script>

<style scoped>
.task-list-card :deep(.el-card__body) {
  position: static;
  display: block;
  color: #303133;
  background: #fff;
}

.task-list-controls {
  position: static;
  z-index: auto;
  display: flex;
  width: 100%;
  margin: 0 0 16px;
  padding: 12px 14px;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  color: #303133;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  box-shadow: none;
  transform: none;
}

.task-list-status-filter {
  width: 160px;
  flex: 0 0 160px;
}

.task-list-refresh-button {
  position: static;
  margin-left: 0;
}

.task-list-refresh-tip {
  color: #606266;
  background: transparent;
  font-size: 13px;
  line-height: 32px;
  white-space: nowrap;
}

.task-list-table-wrap {
  position: relative;
  z-index: auto;
  clear: both;
  width: 100%;
  min-width: 0;
  margin-top: 0;
}

.task-list-pager {
  display: flex;
  min-width: 0;
  margin-top: 16px;
  justify-content: flex-end;
  overflow-x: auto;
}

:deep(.task-row) {
  cursor: pointer;
}

@media (max-width: 640px) {
  .task-list-controls {
    padding: 10px;
    gap: 8px;
  }

  .task-list-status-filter {
    width: min(100%, 220px);
    flex-basis: min(100%, 220px);
  }

  .task-list-refresh-tip {
    flex: 1 1 auto;
  }

  .task-list-pager {
    justify-content: flex-start;
  }
}
</style>
