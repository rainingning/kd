<template>
  <el-tag :type="meta.type" disable-transitions>{{ meta.label }}</el-tag>
</template>

<script setup>
import { computed } from 'vue'
import { TASK_STATUS } from '../utils/format'

const props = defineProps({
  status: { type: String, required: true },
})

const meta = computed(() => TASK_STATUS[props.status] || { label: props.status, type: 'info' })
</script>
