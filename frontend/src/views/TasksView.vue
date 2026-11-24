<template>
  <ResourceView ref="taskView" :config="config">
    <template #panel>
      <div class="task-summary">
        <div class="stat-grid">
          <div class="stat-tile">
            <span class="stat-tile-icon brand"><AppIcon name="timer" :size="18" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">当前页任务</span>
              <span class="stat-tile-value">{{ formatCount(taskStats.total) }}<small>项</small></span>
              <span class="stat-tile-meta">来自任务表格当前已加载行</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon green"><AppIcon name="check-circle" :size="18" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">已启用任务</span>
              <span class="stat-tile-value">{{ formatCount(taskStats.enabled) }}<small>项</small></span>
              <span class="stat-tile-meta">{{ formatCount(taskStats.disabled) }} 项已暂停</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon red"><AppIcon name="alert" :size="18" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">上次执行异常</span>
              <span class="stat-tile-value">{{ formatCount(taskStats.failed) }}<small>项</small></span>
              <span class="stat-tile-meta">仅统计当前已加载行的 failed / error 状态</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon orange"><AppIcon name="activity" :size="18" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">运行 / 等待</span>
              <span class="stat-tile-value">{{ formatCount(taskStats.active) }}<small>项</small></span>
              <span class="stat-tile-meta">仅统计当前已加载行的 running / pending 状态</span>
            </div>
          </div>
        </div>
        <p class="summary-scope">
          <AppIcon name="info" :size="12" />
          <span>摘要随任务表格当前页数据同步更新；翻页或筛选后会重新计算，不代表全库总量。</span>
        </p>
      </div>
    </template>
  </ResourceView>

  <el-dialog
    v-model="recordsDialog"
    width="min(1040px, calc(100vw - 28px))"
    class="task-history-dialog"
    destroy-on-close
  >
    <template #header>
      <div class="history-heading">
        <span class="history-mark"><AppIcon name="history" :size="18" /></span>
        <div>
          <h2>任务执行历史</h2>
          <p>查看手动与定时触发的真实执行记录、耗时和错误详情。</p>
        </div>
      </div>
    </template>

    <div class="history-toolbar">
      <div class="history-kpis">
        <span>本页 <b>{{ formatCount(records.length) }}</b> 条</span>
        <span class="ok">成功 <b>{{ formatCount(recordSuccessCount) }}</b></span>
        <span :class="{ bad: recordFailedCount > 0 }">异常 <b>{{ formatCount(recordFailedCount) }}</b></span>
      </div>
      <el-button text :loading="recordsLoading" @click="loadRecords">
        <AppIcon name="refresh" :size="13" class="btn-icon" />刷新记录
      </el-button>
    </div>

    <el-alert
      v-if="recordsError"
      class="history-error"
      type="error"
      :closable="false"
      show-icon
      title="执行历史加载失败"
    >
      <template #default>
        <span>{{ recordsError }}</span>
        <el-button link type="danger" @click="loadRecords">重试</el-button>
      </template>
    </el-alert>

    <div v-loading="recordsLoading" class="history-body">
      <div v-if="records.length" class="history-table-wrap">
        <el-table :data="records" row-key="id" stripe class="history-table">
          <el-table-column label="开始时间" width="170">
            <template #default="{ row }">{{ formatDate(row.started_at) }}</template>
          </el-table-column>
          <el-table-column label="任务名称" min-width="180">
            <template #default="{ row }">
              <span class="history-task" :title="row.task_name || '—'">{{ row.task_name || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="触发方式" width="112">
            <template #default="{ row }">
              <span class="trigger-badge">
                <AppIcon :name="row.trigger === 'manual' ? 'play' : 'clock'" :size="11" />
                {{ triggerLabel(row.trigger) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="108">
            <template #default="{ row }">
              <el-tag
                :type="statusMeta(row.status).type"
                effect="light"
                class="history-status"
                :class="statusMeta(row.status).tone"
              >
                <AppIcon :name="statusMeta(row.status).icon" :size="11" />
                {{ statusMeta(row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="118">
            <template #default="{ row }">
              <span class="duration-value" :title="row.duration_ms !== null && row.duration_ms !== undefined ? `${row.duration_ms} ms` : undefined">
                {{ formatDuration(row.duration_ms) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="错误详情" min-width="230" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.error" class="history-error-text" :title="row.error">{{ row.error }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-else class="history-empty">
        <AppIcon name="history" :size="28" />
        <b>暂无执行记录</b>
        <span>任务被手动运行或定时触发后，结果会在这里展示。</span>
        <el-button size="small" type="primary" plain :loading="recordsLoading" @click="loadRecords">
          <AppIcon name="refresh" :size="12" class="btn-icon" />刷新记录
        </el-button>
      </div>
    </div>

    <div class="pagination-wrap history-pagination">
      <span>共 {{ formatCount(recordsTotal) }} 条记录 · 第 {{ recordsPage }} 页</span>
      <el-pagination
        v-model:current-page="recordsPage"
        :page-size="20"
        :total="recordsTotal"
        layout="prev, pager, next"
        @current-change="loadRecords"
      />
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Clock } from '@element-plus/icons-vue'
import AppIcon from '../components/AppIcon.vue'
import ResourceView from '../components/ResourceView.vue'
import { api } from '../api'

interface TaskRecord {
  id: number
  task_name?: string | null
  trigger: string
  status: string
  started_at: string
  duration_ms?: number | null
  error?: string | null
}

const taskView = ref<any>()
const recordsDialog = ref(false)
const records = ref<TaskRecord[]>([])
const recordsLoading = ref(false)
const recordsPage = ref(1)
const recordsTotal = ref(0)
const recordsError = ref('')

const taskRows = computed<any[]>(() => {
  const exposed = taskView.value as { rows?: unknown } | undefined
  if (!exposed || !Array.isArray(exposed.rows)) return []
  return exposed.rows
})

const taskStats = computed(() => {
  const rows = taskRows.value
  const failedStatuses = new Set(['failed', 'error', 'timeout'])
  const activeStatuses = new Set(['running', 'pending', 'waiting', 'queued'])
  const enabled = rows.filter(row => Boolean(row.enabled)).length
  return {
    total: rows.length,
    enabled,
    disabled: Math.max(0, rows.length - enabled),
    failed: rows.filter(row => failedStatuses.has(String(row.last_status || '').toLowerCase())).length,
    active: rows.filter(row => activeStatuses.has(String(row.last_status || '').toLowerCase())).length,
  }
})

const recordSuccessCount = computed(() => records.value.filter(record => record.status === 'success').length)
const recordFailedCount = computed(() => records.value.filter(record => ['failed', 'error', 'timeout'].includes(record.status)).length)

function errorText(error: any) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : '请求失败，请检查后端连接后重试'
}

function formatCount(value: number) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

function formatDuration(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const milliseconds = Math.max(0, Number(value))
  if (milliseconds < 1000) return `${Math.round(milliseconds)} 毫秒`
  if (milliseconds < 60_000) {
    const seconds = milliseconds / 1000
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`
  }
  const totalSeconds = Math.round(milliseconds / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes < 60) return `${minutes} 分 ${seconds} 秒`
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分`
}

function triggerLabel(trigger: string) {
  return ({
    manual: '手动执行',
    schedule: '定时触发',
    queue: '队列执行',
    retry: '失败重试',
  } as Record<string, string>)[trigger] || trigger || '未知触发'
}

function statusMeta(status: string) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'success') {
    return { label: '成功', type: 'success' as const, icon: 'check-circle', tone: 'success' }
  }
  if (normalized === 'running') {
    return { label: '运行中', type: 'warning' as const, icon: 'loader', tone: 'running' }
  }
  if (['failed', 'error', 'timeout'].includes(normalized)) {
    return { label: '失败', type: 'danger' as const, icon: 'alert', tone: 'failed' }
  }
  if (['pending', 'queued', 'waiting'].includes(normalized)) {
    return { label: '等待中', type: 'warning' as const, icon: 'clock', tone: 'pending' }
  }
  return { label: status || '未知', type: 'info' as const, icon: 'info', tone: 'neutral' }
}

async function loadRecords() {
  recordsLoading.value = true
  recordsError.value = ''
  try {
    const { data } = await api.get('/tasks/records', {
      params: { page: recordsPage.value, page_size: 20 },
    })
    records.value = data.items || []
    recordsTotal.value = data.total || 0
  } catch (error) {
    recordsError.value = errorText(error)
    records.value = []
    recordsTotal.value = 0
  } finally {
    recordsLoading.value = false
  }
}

function openHistory() {
  recordsDialog.value = true
  loadRecords()
}

onMounted(loadRecords)

const config = {
  kicker: 'AUTOMATION',
  title: '自动化任务',
  description: '持久化定时任务、运行记录、失败重试与立即执行',
  endpoint: '/tasks',
  itemName: '任务',
  nameKey: 'name',
  keyword: '搜索任务',
  createLabel: '创建任务',
  rawCreateLabel: '创建',
  extraCreateLabel: '执行历史',
  extraCreateIcon: Clock,
  onExtraCreate: openHistory,
  columns: [
    { key: 'name', label: '任务名称', width: 190 },
    {
      key: 'task_type',
      label: '任务类型',
      width: 135,
      options: [
        { value: 'github_check', label: '单仓库检查' },
        { value: 'github_check_all', label: '全部仓库检查' },
        { value: 'group_announcement', label: '定时群公告' },
        { value: 'group_message', label: '定时群消息' },
        { value: 'online_check', label: '在线状态检查' },
        { value: 'ai_summary', label: 'AI 总结' },
        { value: 'health_check', label: '系统健康检查' },
        { value: 'backup', label: '数据库备份' },
        { value: 'push_retry', label: '失败推送重试' },
      ],
    },
    {
      key: 'schedule_kind',
      label: '调度模式',
      width: 100,
      options: [
        { value: 'interval', label: '间隔' },
        { value: 'cron', label: 'Cron' },
      ],
    },
    { key: 'interval_seconds', label: '执行间隔(秒)', width: 110 },
    { key: 'enabled', label: '状态', type: 'bool', width: 80 },
    {
      key: 'last_status',
      label: '上次结果',
      type: 'status',
      width: 96,
      options: [
        { value: 'success', label: '成功' },
        { value: 'running', label: '运行中' },
        { value: 'failed', label: '失败' },
        { value: 'error', label: '失败' },
      ],
    },
    { key: 'next_run_at', label: '下次执行', type: 'date', width: 165 },
    { key: 'total_runs', label: '执行次数', width: 85 },
  ],
  createFields: [
    { key: 'name', label: '任务名称', required: true },
    {
      key: 'task_type',
      label: '任务类型',
      type: 'select',
      required: true,
      options: [
        { value: 'github_check', label: '检查指定仓库' },
        { value: 'github_check_all', label: '检查所有仓库' },
        { value: 'group_announcement', label: '定时群公告' },
        { value: 'group_message', label: '定时群消息' },
        { value: 'online_check', label: '机器人在线检查' },
        { value: 'ai_summary', label: 'AI 总结' },
        { value: 'health_check', label: '系统健康检查' },
        { value: 'backup', label: '数据库备份' },
        { value: 'push_retry', label: '失败推送重试' },
      ],
    },
    {
      key: 'schedule_kind',
      label: '调度方式',
      type: 'select',
      default: 'interval',
      options: [
        { value: 'interval', label: '固定间隔' },
        { value: 'cron', label: 'Cron 表达式' },
      ],
    },
    { key: 'interval_seconds', label: '间隔秒数（至少 30 秒）', type: 'number', default: 3600, min: 30 },
    { key: 'cron_expr', label: 'Cron 表达式', placeholder: '例如 0 9 * * *' },
    { key: 'payload', label: '任务参数 JSON', type: 'json', default: {}, rows: 5, placeholder: '例如 {"repository_id": 1}' },
    { key: 'enabled', label: '启用任务', type: 'switch', default: true },
    { key: 'max_retries', label: '最大重试次数', type: 'number', default: 2, min: 0, max: 5 },
    { key: 'timeout_seconds', label: '超时时间（秒）', type: 'number', default: 300, min: 10, max: 3600 },
  ],
  editFields: [
    { key: 'name', label: '任务名称' },
    {
      key: 'schedule_kind',
      label: '调度方式',
      type: 'select',
      options: [
        { value: 'interval', label: '固定间隔' },
        { value: 'cron', label: 'Cron 表达式' },
      ],
    },
    { key: 'interval_seconds', label: '间隔秒数', type: 'number', min: 30 },
    { key: 'cron_expr', label: 'Cron 表达式' },
    { key: 'payload', label: '任务参数 JSON', type: 'json', rows: 5 },
    { key: 'enabled', label: '启用任务', type: 'switch' },
    { key: 'max_retries', label: '最大重试次数', type: 'number', min: 0, max: 5 },
    { key: 'timeout_seconds', label: '超时时间（秒）', type: 'number', min: 10, max: 3600 },
  ],
  actions: [
    {
      label: '立即运行',
      suffix: 'run',
      method: 'POST',
      type: 'success',
      success: (data: any) => data.message || '任务执行完成',
    },
    {
      labelFor: (row: any) => row.enabled ? '暂停' : '启用',
      path: (row: any) => `/tasks/${row.id}/toggle`,
      method: 'POST',
      type: 'warning',
    },
  ],
  deletePath: '/tasks',
}
</script>

<style scoped>
.btn-icon {
  margin-right: 5px;
}
.task-summary {
  margin-bottom: 2px;
}
.summary-scope {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin: -4px 0 14px;
  padding: 0 2px;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.55;
}
.summary-scope .app-icon {
  margin-top: 1px;
  flex: none;
}
.history-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}
.history-mark {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.history-heading > div {
  min-width: 0;
}
.history-heading h2 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 15px;
  font-weight: 620;
}
.history-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.5;
}
.history-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line-soft);
}
.history-kpis {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.history-kpis span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 23px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-4);
  font-size: 9px;
}
.history-kpis b {
  color: var(--text-2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.history-kpis span.ok {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}
.history-kpis span.ok b {
  color: var(--success);
}
.history-kpis span.bad {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}
.history-kpis span.bad b {
  color: var(--danger);
}
.history-error {
  margin-bottom: 10px;
}
.history-error :deep(.el-alert__content) {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.history-body {
  min-height: 220px;
}
.history-table-wrap {
  max-height: min(56vh, 560px);
  overflow: auto;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
}
.history-table {
  min-width: 900px;
}
.history-task,
.history-error-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-task {
  color: var(--text-2);
}
.history-error-text {
  color: var(--danger);
  font-size: 10px;
}
.trigger-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 22px;
  padding: 0 7px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 8.5px;
  white-space: nowrap;
}
.history-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.history-status :deep(.el-tag__content) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.history-status.running .app-icon {
  animation: spin 1s linear infinite;
}
.duration-value {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.history-empty {
  display: flex;
  min-height: 260px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 24px;
  color: var(--text-4);
  text-align: center;
}
.history-empty .app-icon {
  color: var(--text-4);
}
.history-empty b {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}
.history-empty span {
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.6;
}
.history-pagination {
  border-top: 1px solid var(--line-soft);
  padding: 11px 0 0;
  margin-top: 10px;
  background: transparent;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 700px) {
  .history-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
  .history-kpis {
    width: 100%;
  }
  .history-kpis span {
    flex: 1;
    justify-content: center;
  }
  .history-pagination {
    align-items: flex-start;
    flex-direction: column;
  }
  .history-pagination :deep(.el-pagination) {
    flex-wrap: wrap;
    row-gap: 6px;
  }
  .history-table-wrap {
    max-height: 52vh;
  }
}
</style>
