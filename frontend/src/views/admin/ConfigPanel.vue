<template>
  <div v-loading="loading" class="config-pane">
    <el-alert type="info" :closable="false" class="tip-alert">
      仅提交修改过的配置项；所有配置必须为正数。
    </el-alert>
    <el-form label-width="220px" class="config-form" @submit.prevent>
      <el-form-item v-for="item in CONFIG_ITEMS" :key="item.key" :label="item.label">
        <el-input-number v-model="form[item.key]" :min="item.min" :precision="0" controls-position="right" style="width: 200px" />
        <span class="unit">{{ item.unit }}</span>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" :disabled="!hasChanges" @click="onSave">
          保存修改
        </el-button>
        <el-button :disabled="!hasChanges" @click="resetForm">还原</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../../api/admin'

const CONFIG_ITEMS = [
  { key: 'max_concurrent_tasks', label: '全局最大并发任务数', unit: '个', min: 1 },
  { key: 'max_running_per_user', label: '每用户最大运行任务数', unit: '个', min: 1 },
  { key: 'max_queued_per_user', label: '每用户最大排队任务数', unit: '个', min: 1 },
  { key: 'task_timeout_minutes', label: '任务超时时间', unit: '分钟', min: 1 },
  { key: 'retention_days', label: '结果文件保留天数', unit: '天', min: 1 },
  { key: 'max_upload_mb', label: '上传文件大小上限', unit: 'MB', min: 1 },
]

const loading = ref(false)
const saving = ref(false)
const original = ref({}) // 服务端返回的字符串值
const form = reactive({}) // 表单里的数值

onMounted(load)

async function load() {
  loading.value = true
  try {
    const data = await adminApi.getConfig()
    original.value = data.config
    resetForm()
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function resetForm() {
  for (const item of CONFIG_ITEMS) {
    form[item.key] = Number(original.value[item.key]) || item.min
  }
}

const hasChanges = computed(() =>
  CONFIG_ITEMS.some((item) => String(form[item.key]) !== original.value[item.key]),
)

async function onSave() {
  const changed = {}
  for (const item of CONFIG_ITEMS) {
    const v = form[item.key]
    if (v === undefined || v === null || !Number.isFinite(v) || v <= 0) {
      ElMessage.warning(`${item.label}：必须为正数`)
      return
    }
    if (String(v) !== original.value[item.key]) changed[item.key] = String(v)
  }
  saving.value = true
  try {
    const data = await adminApi.updateConfig(changed)
    original.value = data.config
    resetForm()
    ElMessage.success('配置已保存')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.config-pane {
  max-width: 640px;
}

.tip-alert {
  margin-bottom: 16px;
}

.unit {
  margin-left: 10px;
  color: #909399;
}
</style>
