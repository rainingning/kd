<template>
  <div class="page-container">
    <el-card class="page-card">
      <template #header>
        <div class="card-header">
          <span class="title">任务列表</span>
        </div>
      </template>

      <div class="toolbar">
        <el-select
          v-model="statusFilter"
          placeholder="全部状态"
          clearable
          style="width: 160px"
          @change="onFilterChange"
        >
          <el-option v-for="(meta, s) in TASK_STATUS" :key="s" :label="meta.label" :value="s" />
        </el-select>
        <el-button :icon="Refresh" @click="load()">刷新</el-button>
        <span class="text-muted tip">每 5 秒自动刷新</span>
      </div>

      <el-table v-loading="loading" :data="items" border @row-click="onRowClick" row-class-name="task-row">
        <el-table-column prop="id" label="ID" width="80" />
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

      <div class="pager">
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
.tip {
  font-size: 13px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

:deep(.task-row) {
  cursor: pointer;
}
</style>
