// 时间与状态展示工具：后端返回 UTC ISO 时间，统一转浏览器本地时区显示

export function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

// 耗时展示：duration_sec（秒，可能为 null）
export function formatDuration(sec) {
  if (sec === null || sec === undefined) return '—'
  return humanizeSeconds(sec)
}

// 从某 UTC 时间起到 now 的已用时长（运行中/排队中任务用）
export function elapsedSince(iso, now = new Date()) {
  if (!iso) return '—'
  const start = new Date(iso)
  if (Number.isNaN(start.getTime())) return '—'
  const sec = Math.max(0, (now.getTime() - start.getTime()) / 1000)
  return humanizeSeconds(sec)
}

function humanizeSeconds(sec) {
  if (sec < 60) return `${sec.toFixed(1)} 秒`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  if (m < 60) return `${m} 分 ${s} 秒`
  const h = Math.floor(m / 60)
  return `${h} 小时 ${m % 60} 分`
}

export const TASK_STATUS = {
  QUEUED: { label: '排队中', type: 'warning' },
  PREPARING: { label: '准备工作区', type: 'warning' },
  RUNNING: { label: '运行中', type: 'primary' },
  ARCHIVING: { label: '正在归档', type: 'warning' },
  ARCHIVE_FAILED: { label: '归档失败', type: 'danger' },
  COMPLETED: { label: '已完成', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
  CANCELED: { label: '已取消', type: 'info' },
}

// 需要继续轮询的非终态；ARCHIVE_FAILED 会由后端自动重试。
export function isActiveStatus(status) {
  return ['QUEUED', 'PREPARING', 'RUNNING', 'ARCHIVING', 'ARCHIVE_FAILED'].includes(status)
}

export function isCancelableStatus(status) {
  return ['QUEUED', 'PREPARING', 'RUNNING'].includes(status)
}

export const NOTIFICATION_TYPE = {
  completed: { label: '完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  killed: { label: '终止', type: 'warning' },
}
