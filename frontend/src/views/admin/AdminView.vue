<template>
  <div class="page-container">
    <el-card class="page-card">
      <template #header>
        <div class="card-header">
          <span class="title">管理后台</span>
        </div>
      </template>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="仪表盘" name="dashboard" lazy>
          <DashboardPanel v-if="activeTab === 'dashboard'" />
        </el-tab-pane>
        <el-tab-pane label="任务监控" name="tasks" lazy>
          <TasksPanel v-if="activeTab === 'tasks'" />
        </el-tab-pane>
        <el-tab-pane label="用户管理" name="users" lazy>
          <UsersPanel v-if="activeTab === 'users'" />
        </el-tab-pane>
        <el-tab-pane label="程序与工作区" name="program" lazy>
          <ProgramPanel v-if="activeTab === 'program'" />
        </el-tab-pane>
        <el-tab-pane label="归档异常" name="archives" lazy>
          <ArchiveFailuresPanel v-if="activeTab === 'archives'" />
        </el-tab-pane>
        <el-tab-pane label="系统配置" name="config" lazy>
          <ConfigPanel v-if="activeTab === 'config'" />
        </el-tab-pane>
        <el-tab-pane label="审计日志" name="audit" lazy>
          <AuditLogsPanel v-if="activeTab === 'audit'" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import DashboardPanel from './DashboardPanel.vue'
import TasksPanel from './TasksPanel.vue'
import UsersPanel from './UsersPanel.vue'
import ProgramPanel from './ProgramPanel.vue'
import ArchiveFailuresPanel from './ArchiveFailuresPanel.vue'
import ConfigPanel from './ConfigPanel.vue'
import AuditLogsPanel from './AuditLogsPanel.vue'

const activeTab = ref('dashboard')
</script>
