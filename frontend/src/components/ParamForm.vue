<template>
  <div class="param-form">
    <el-skeleton v-if="loading" :rows="4" animated />
    <el-alert v-else-if="loadError" type="error" :title="loadError" :closable="false" />

    <!-- 只读模式：参数快照键值表 -->
    <el-table v-else-if="readonly" :data="readonlyRows" border size="small">
      <el-table-column prop="label" label="参数" width="260" />
      <el-table-column prop="value" label="值" />
    </el-table>

    <!-- 编辑模式：按 schema 动态渲染 -->
    <el-form v-else label-position="top" @submit.prevent>
      <el-form-item v-for="field in fields" :key="field.name" :required="!!field.required">
        <template #label>
          <span>{{ labelOf(field) }}</span>
          <el-tooltip
            v-if="field.description && field.description !== field.name"
            :content="`参数名：${field.name}`"
            placement="top"
          >
            <el-icon class="name-tip"><InfoFilled /></el-icon>
          </el-tooltip>
        </template>

        <el-input-number
          v-if="field.type === 'int'"
          :model-value="modelValue[field.name]"
          :min="field.min"
          :max="field.max"
          :precision="0"
          :step="1"
          controls-position="right"
          class="num-input"
          @update:model-value="(v) => setValue(field.name, v)"
        />
        <el-input-number
          v-else-if="field.type === 'float'"
          :model-value="modelValue[field.name]"
          :min="field.min"
          :max="field.max"
          :step="stepOf(field)"
          controls-position="right"
          class="num-input"
          @update:model-value="(v) => setValue(field.name, v)"
        />
        <el-switch
          v-else-if="field.type === 'bool'"
          :model-value="Boolean(modelValue[field.name])"
          @update:model-value="(v) => setValue(field.name, v)"
        />
        <el-select
          v-else-if="field.type === 'enum'"
          :model-value="modelValue[field.name]"
          placeholder="请选择"
          clearable
          class="num-input"
          @update:model-value="(v) => setValue(field.name, v)"
        >
          <el-option
            v-for="opt in field.options || []"
            :key="opt"
            :label="String(opt)"
            :value="opt"
          />
        </el-select>
        <el-input
          v-else
          :model-value="modelValue[field.name]"
          placeholder="请输入"
          @update:model-value="(v) => setValue(field.name, v)"
        />

        <div v-if="errors[field.name]" class="field-error">{{ errors[field.name] }}</div>
        <div v-else-if="hintOf(field)" class="field-hint">{{ hintOf(field) }}</div>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { getParamSchema } from '../api/params'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  readonly: { type: Boolean, default: false },
  programKey: { type: String, default: 'dcr_3d' },
})
const emit = defineEmits(['update:modelValue'])

const loading = ref(true)
const loadError = ref('')
const fields = ref([])
const errors = reactive({})

onMounted(async () => {
  try {
    const schema = await getParamSchema(props.programKey)
    fields.value = schema.fields || []
    if (!props.readonly) fillDefaults()
  } catch {
    loadError.value = '参数 Schema 加载失败，请刷新重试'
  } finally {
    loading.value = false
  }
})

// 用 schema 默认值补齐未设置的键（不清空已有值，如模板/复制预填的值）
function fillDefaults() {
  const merged = { ...props.modelValue }
  let changed = false
  for (const f of fields.value) {
    if (merged[f.name] === undefined && f.default !== undefined) {
      merged[f.name] = f.default
      changed = true
    }
  }
  if (changed) emit('update:modelValue', merged)
}

function setValue(name, value) {
  errors[name] = ''
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}

function labelOf(field) {
  return field.description || field.name
}

function stepOf(field) {
  if (field.min !== undefined && field.min > 0) return field.min
  return 0.01
}

function hintOf(field) {
  const parts = []
  if ((field.type === 'int' || field.type === 'float') && (field.min !== undefined || field.max !== undefined)) {
    const lo = field.min !== undefined ? field.min : '-∞'
    const hi = field.max !== undefined ? field.max : '+∞'
    parts.push(`取值范围：${lo} ~ ${hi}`)
  }
  return parts.join('；')
}

// 前端校验：必填 / 整数 / 范围 / 枚举，返回是否全部通过
function validate() {
  let ok = true
  for (const f of fields.value) {
    const label = labelOf(f)
    const v = props.modelValue[f.name]
    const empty = v === undefined || v === null || v === ''
    if (empty) {
      if (f.required) {
        errors[f.name] = f.type === 'enum' ? `请选择${label}` : `请填写${label}`
        ok = false
      }
      continue
    }
    if (f.type === 'int' && !Number.isInteger(v)) {
      errors[f.name] = `${label}：应为整数`
      ok = false
      continue
    }
    if ((f.type === 'int' || f.type === 'float') && typeof v === 'number') {
      if (f.min !== undefined && v < f.min) {
        errors[f.name] = `${label}：不能小于 ${f.min}`
        ok = false
        continue
      }
      if (f.max !== undefined && v > f.max) {
        errors[f.name] = `${label}：不能大于 ${f.max}`
        ok = false
        continue
      }
    }
    if (f.type === 'enum' && f.options && !f.options.includes(v)) {
      errors[f.name] = `${label}：应为 ${f.options.join(' / ')} 之一`
      ok = false
      continue
    }
    errors[f.name] = ''
  }
  return ok
}

// 只读模式行：优先按 schema 顺序展示，快照里多出的键排在后面
const readonlyRows = computed(() => {
  const params = props.modelValue || {}
  const rows = []
  const seen = new Set()
  for (const f of fields.value) {
    if (f.name in params) {
      seen.add(f.name)
      rows.push({ label: `${labelOf(f)}（${f.name}）`, value: displayValue(params[f.name]) })
    }
  }
  for (const [k, v] of Object.entries(params)) {
    if (!seen.has(k)) rows.push({ label: k, value: displayValue(v) })
  }
  return rows
})

function displayValue(v) {
  if (v === true) return '是'
  if (v === false) return '否'
  if (v === null || v === undefined) return '—'
  return String(v)
}

defineExpose({ validate, fields })
</script>

<style scoped>
.num-input {
  width: 260px;
}

.name-tip {
  margin-left: 4px;
  color: #909399;
  vertical-align: -2px;
  cursor: help;
}

.field-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.4;
  margin-top: 4px;
}
</style>
