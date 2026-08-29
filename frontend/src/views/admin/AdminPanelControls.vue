<template>
  <section class="admin-panel-controls" :aria-label="label">
    <slot />
  </section>
</template>

<script setup>
defineProps({
  label: {
    type: String,
    default: '管理面板操作',
  },
})
</script>

<style scoped>
.admin-panel-controls {
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

.admin-panel-controls :deep(.el-button) {
  position: static;
  margin-left: 0;
}

.admin-panel-controls :deep(.el-checkbox__label) {
  color: #303133;
}

@media (max-width: 640px) {
  .admin-panel-controls {
    padding: 10px;
    gap: 8px;
  }
}
</style>
