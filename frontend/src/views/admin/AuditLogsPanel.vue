<template>
  <div>
    <div class="toolbar">
      <el-select
        v-model="actionFilter"
        placeholder="全部操作类型"
        clearable
        style="width: 220px"
        @change="onFilterChange"
      >
        <el-option v-for="(label, action) in ACTION_LABELS" :key="action" :label="label" :value="action" />
      </el-select>
      <el-button @click="load()">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="items" border size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="管理员" width="120">
        <template #default="{ row }">{{ row.admin_username || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-tag size="small">{{ ACTION_LABELS[row.action] || row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="目标" width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.target || '—' }}</template>
      </el-table-column>
      <el-table-column label="详情" min-width="220">
        <template #default="{ row }">
          <code v-if="row.detail" class="detail-code">{{ JSON.stringify(row.detail) }}</code>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <template #empty>暂无审计日志</template>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="load()"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { adminApi } from '../../api/admin'
import { formatTime } from '../../utils/format'

const ACTION_LABELS = {
  'task.kill': '终止任务',
  'user.create': '创建用户',
  'user.update': '编辑用户',
  'user.delete': '删除用户',
  'user.reset_password': '重置用户密码',
  'user.disable': '禁用用户',
  'user.enable': '启用用户',
  'config.update': '修改系统配置',
}

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const actionFilter = ref('')
const loading = ref(false)

onMounted(load)

async function load() {
  loading.value = true
  try {
    const data = await adminApi.auditLogs({
      action: actionFilter.value,
      page: page.value,
      pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  load()
}
</script>

<style scoped>
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.detail-code {
  font-size: 12px;
  color: #606266;
  word-break: break-all;
}
</style>
