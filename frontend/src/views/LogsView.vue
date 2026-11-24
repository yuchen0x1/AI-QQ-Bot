<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">OBSERVABILITY · AUDIT TRAIL</div>
      <h1>系统日志</h1>
      <p>检索平台各模块日志，敏感字段在服务端脱敏。全局保留周期由每日清理任务执行，并同时作用于日志、消息、任务与会话等数据。</p>
    </div>
    <div class="heading-actions">
      <div v-if="retentionVisible && retentionDays !== null" class="retention-box">
        <span class="retention-caption"><AppIcon name="database" :size="13" />全局保留</span>
        <el-select
          v-model="retentionDays"
          class="retention-select"
          size="small"
          :disabled="savingRetention"
          aria-label="全局数据保留天数"
          @change="saveRetention"
        >
          <el-option :value="1" label="1 天" />
          <el-option :value="3" label="3 天" />
          <el-option :value="7" label="7 天" />
          <el-option :value="14" label="14 天" />
          <el-option :value="30" label="30 天" />
          <el-option :value="0" label="永久保留" />
        </el-select>
        <el-tooltip
          placement="bottom"
          :show-after="120"
          popper-class="retention-tooltip-popper"
          content="保留周期统一作用于日志、消息、任务记录、AI 调用与会话、登录/审计记录、GitHub 事件与推送记录，由每日清理任务自动执行；0 表示永久保留。"
        >
          <button type="button" class="retention-info" aria-label="查看全局数据保留策略说明">
            <AppIcon name="info" :size="14" />
          </button>
        </el-tooltip>
      </div>
      <el-button :loading="loading" :disabled="loading" @click="load()">
        <AppIcon name="refresh" :size="14" style="margin-right:5px" />刷新日志
      </el-button>
    </div>
  </div>

  <el-alert v-if="loadError" type="error" show-icon :closable="false" class="logs-error" title="日志加载失败">
    <template #default>
      <span>{{ loadError }}</span>
      <el-button link type="primary" @click="load()">重试</el-button>
    </template>
  </el-alert>

  <section class="surface resource-surface logs-surface" :aria-busy="loading">
    <div class="resource-toolbar logs-toolbar">
      <div class="log-filters">
        <el-input
          v-model="filters.keyword"
          class="log-search"
          clearable
          placeholder="搜索日志关键词"
          aria-label="搜索日志关键词"
          @keyup.enter="load(1)"
          @clear="load(1)"
        >
          <template #prefix><AppIcon name="search" :size="14" /></template>
        </el-input>
        <el-select
          v-model="filters.category"
          class="filter-select"
          clearable
          placeholder="日志分类"
          aria-label="按日志分类筛选"
          @change="load(1)"
        >
          <el-option v-for="category in categories" :key="category.value" :label="category.label" :value="category.value" />
        </el-select>
        <el-select
          v-model="filters.level"
          class="filter-select level-filter"
          clearable
          placeholder="级别"
          aria-label="按日志级别筛选"
          @change="load(1)"
        >
          <el-option label="INFO · 信息" value="INFO" />
          <el-option label="WARNING · 警告" value="WARNING" />
          <el-option label="ERROR · 错误" value="ERROR" />
        </el-select>
        <el-date-picker
          v-model="timeRange"
          class="date-filter"
          type="daterange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          aria-label="按日期范围筛选日志"
          @change="load(1)"
        />
        <el-button type="primary" @click="load(1)">
          <AppIcon name="filter" :size="14" style="margin-right:5px" />筛选
        </el-button>
        <el-button v-if="hasFilters" text @click="clearFilters">重置</el-button>
      </div>
      <div class="log-results" aria-live="polite">
        <span class="log-result-count">{{ resultSummary }}</span>
        <span v-if="!loading" class="log-page-indicator">第 {{ page }} / {{ pageCount }} 页</span>
      </div>
    </div>

    <el-table
      v-loading="loading"
      class="logs-table"
      :data="rows"
      row-key="id"
      stripe
      style="width: 100%"
    >
      <el-table-column type="expand" width="42">
        <template #default="{ row }">
          <div class="log-detail">
            <div class="log-detail-head">
              <div class="log-detail-heading">
                <span class="level-badge" :class="levelMeta(row.level).tone">
                  <AppIcon :name="levelMeta(row.level).icon" :size="13" />{{ levelMeta(row.level).label }}
                </span>
                <span class="detail-id mono">#{{ row.id }}</span>
                <span class="detail-category">{{ categoryLabel(row.category) }}</span>
                <time :datetime="row.created_at">{{ formatDate(row.created_at) }}</time>
              </div>
              <el-button size="small" @click="copyLog(row)">
                <AppIcon name="copy" :size="13" style="margin-right:4px" />{{ copiedKey === `log-${row.id}` ? '已复制' : '复制整条日志' }}
              </el-button>
            </div>

            <p class="log-detail-message">{{ row.message }}</p>

            <div v-if="row.context" class="context-section">
              <div class="context-head">
                <span class="context-label"><AppIcon name="code" :size="13" />上下文 JSON</span>
                <el-button link type="primary" size="small" @click="copyContext(row, `row-context-${row.id}`)">
                  <AppIcon name="copy" :size="12" style="margin-right:4px" />{{ copiedKey === `row-context-${row.id}` ? '已复制' : '复制上下文' }}
                </el-button>
              </div>
              <pre class="context-code">{{ formatContext(row.context) }}</pre>
            </div>

            <div v-if="contextStack(row.context)" class="context-section">
              <span class="context-label"><AppIcon name="terminal" :size="13" />错误堆栈</span>
              <pre class="context-code stack-code">{{ contextStack(row.context) }}</pre>
            </div>

            <div v-if="!row.context" class="detail-empty">该日志没有附加上下文。</div>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="级别" width="104">
        <template #default="{ row }">
          <span class="level-badge" :class="levelMeta(row.level).tone" :title="row.level">
            <AppIcon :name="levelMeta(row.level).icon" :size="13" />{{ levelMeta(row.level).label }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="分类" width="132">
        <template #default="{ row }"><span class="category-label">{{ categoryLabel(row.category) }}</span></template>
      </el-table-column>
      <el-table-column label="账号" width="82">
        <template #default="{ row }"><span class="account-ref mono">{{ accountLabel(row.account_id) }}</span></template>
      </el-table-column>
      <el-table-column label="时间" width="146">
        <template #default="{ row }">
          <time class="log-time" :datetime="row.created_at">
            <b>{{ formatTime(row.created_at) }}</b>
            <small>{{ formatDay(row.created_at) }}</small>
          </time>
        </template>
      </el-table-column>
      <el-table-column label="内容" min-width="340" show-overflow-tooltip>
        <template #default="{ row }"><span class="log-message">{{ row.message }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="86" align="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" :aria-label="`查看第 ${row.id} 条日志详情`" @click="showContext(row)">
            <AppIcon name="eye" :size="13" style="margin-right:4px" />查看
          </el-button>
        </template>
      </el-table-column>

      <template #empty>
        <div class="empty-inline logs-empty">
          <AppIcon :name="emptyIcon" :size="28" />
          <b>{{ emptyTitle }}</b>
          <span>{{ emptyDescription }}</span>
          <el-button v-if="!loading" size="small" :type="loadError ? 'primary' : 'default'" @click="emptyAction">{{ emptyActionLabel }}</el-button>
        </div>
      </template>
    </el-table>

    <div class="pagination-wrap">
      <span>{{ loading ? '正在加载日志…' : `共 ${total.toLocaleString('zh-CN')} 条记录 · 第 ${page} / ${pageCount} 页` }}</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        :pager-count="5"
        layout="sizes,prev,pager,next"
        @current-change="load"
        @size-change="load(1)"
      />
    </div>
  </section>

  <el-dialog
    v-model="contextDialog"
    :title="contextTitle"
    width="min(760px, calc(100vw - 28px))"
    destroy-on-close
  >
    <div v-if="contextRow" class="context-dialog-body">
      <div class="dialog-summary">
        <span class="level-badge" :class="levelMeta(contextRow.level).tone">
          <AppIcon :name="levelMeta(contextRow.level).icon" :size="13" />{{ levelMeta(contextRow.level).label }}
        </span>
        <span class="dialog-chip">{{ categoryLabel(contextRow.category) }}</span>
        <span class="dialog-chip mono">#{{ contextRow.id }}</span>
        <span v-if="contextRow.account_id" class="dialog-chip mono">账号 #{{ contextRow.account_id }}</span>
        <time :datetime="contextRow.created_at">{{ formatDate(contextRow.created_at) }}</time>
      </div>

      <section class="dialog-block">
        <span class="context-label"><AppIcon name="logs" :size="13" />完整消息</span>
        <p class="dialog-message">{{ contextRow.message }}</p>
      </section>

      <section v-if="contextText" class="dialog-block">
        <span class="context-label"><AppIcon name="code" :size="13" />上下文 JSON</span>
        <pre class="context-code dialog-code">{{ contextText }}</pre>
      </section>

      <section v-if="contextStackText" class="dialog-block">
        <span class="context-label"><AppIcon name="terminal" :size="13" />错误堆栈</span>
        <pre class="context-code stack-code dialog-code">{{ contextStackText }}</pre>
      </section>

      <div v-if="!contextText && !contextStackText" class="dialog-empty">
        <AppIcon name="info" :size="17" />该日志没有附加上下文。
      </div>
    </div>
    <template #footer>
      <el-button @click="contextDialog = false">关闭</el-button>
      <el-button v-if="contextText" @click="copyContext(contextRow, 'dialog-context')">
        <AppIcon name="copy" :size="13" style="margin-right:4px" />{{ copiedKey === 'dialog-context' ? '已复制' : '复制上下文' }}
      </el-button>
      <el-button type="primary" @click="copyLog(contextRow)">
        <AppIcon name="copy" :size="13" style="margin-right:4px" />{{ copiedKey === `log-${contextRow?.id}` ? '已复制' : '复制整条日志' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'

const rows = ref<any[]>([])
const categories = ref<any[]>([])
const loading = ref(false)
const loadError = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const filters = reactive({ keyword: '', category: '', level: '' })
const timeRange = ref<any>(null)
const contextDialog = ref(false)
const contextRow = ref<any>(null)
const copiedKey = ref('')
const retentionDays = ref<number | null>(null)
const retentionSaved = ref<number | null>(null)
const retentionVisible = ref(false)
const savingRetention = ref(false)
let requestSeq = 0
let copyTimer: ReturnType<typeof setTimeout> | undefined

const LEVEL_META: Record<string, { label: string; icon: string; tone: string }> = {
  DEBUG: { label: '调试', icon: 'terminal', tone: 'neutral' },
  INFO: { label: '信息', icon: 'info', tone: 'info' },
  WARNING: { label: '警告', icon: 'alert', tone: 'warning' },
  ERROR: { label: '错误', icon: 'alert', tone: 'danger' },
  CRITICAL: { label: '严重', icon: 'shield', tone: 'danger' },
}

const hasFilters = computed(() => Boolean(filters.keyword.trim() || filters.category || filters.level || timeRange.value?.length === 2))
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const resultSummary = computed(() => loading.value ? '正在检索…' : `共 ${total.value.toLocaleString('zh-CN')} 条记录`)
const contextText = computed(() => contextRow.value?.context ? formatContext(contextRow.value.context) : '')
const contextStackText = computed(() => contextStack(contextRow.value?.context))
const contextTitle = computed(() => contextRow.value ? `日志详情 · #${contextRow.value.id}` : '日志详情')
const emptyIcon = computed(() => loading.value ? 'loader' : loadError.value ? 'alert' : hasFilters.value ? 'filter' : 'logs')
const emptyTitle = computed(() => loading.value ? '正在加载日志' : loadError.value ? '日志暂时无法加载' : hasFilters.value ? '没有匹配当前筛选的日志' : '还没有日志记录')
const emptyDescription = computed(() => {
  if (loading.value) return '正在读取当前筛选条件下的平台日志。'
  if (loadError.value) return '请检查后端连接或访问权限，然后重试。'
  if (hasFilters.value) return '尝试缩短关键词，或放宽分类、级别与日期范围。'
  return '系统运行后，账号、任务、AI 与推送日志会出现在这里。'
})
const emptyActionLabel = computed(() => loadError.value ? '重新加载' : hasFilters.value ? '清除筛选' : '刷新日志')

function levelMeta(level: string) {
  const key = String(level || 'INFO').toUpperCase()
  return LEVEL_META[key] || { label: key || '日志', icon: 'info', tone: 'info' }
}

function categoryLabel(value: string) {
  return categories.value.find((category) => category.value === value)?.label || value || '—'
}

function accountLabel(value: unknown) {
  return value ? `#${value}` : '—'
}

function formatContext(value: any): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

function contextStack(value: any): string {
  if (typeof value === 'string') {
    return /(?:Traceback \(most recent call last\)|File ".+", line \d+|^\s+at\s)/m.test(value) ? value : ''
  }
  if (!value || typeof value !== 'object') return ''
  const record = value as Record<string, any>
  for (const key of ['traceback', 'stack', 'stacktrace', 'error_stack']) {
    const item = record[key]
    if (typeof item === 'string' && item.trim()) return item
    if (item && typeof item === 'object') {
      const nested = contextStack(item)
      if (nested) return nested
    }
  }
  for (const key of ['error', 'exception', 'cause']) {
    const nested = contextStack(record[key])
    if (nested) return nested
  }
  return ''
}

function parseDate(value: string) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatDate(value: string) {
  const date = parseDate(value)
  return date ? date.toLocaleString('zh-CN') : '—'
}

function formatTime(value: string) {
  const date = parseDate(value)
  return date ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'
}

function formatDay(value: string) {
  const date = parseDate(value)
  return date ? date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }) : '—'
}

function errorDetail(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length) return String(detail[0]?.msg || fallback)
  if (typeof error?.message === 'string' && error.message) return error.message
  return fallback
}

function buildParams() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  const keyword = filters.keyword.trim()
  if (keyword) params.keyword = keyword
  if (filters.category) params.category = filters.category
  if (filters.level) params.level = filters.level
  if (timeRange.value?.length === 2) {
    const start = new Date(timeRange.value[0])
    const end = new Date(timeRange.value[1])
    if (!Number.isNaN(start.getTime()) && !Number.isNaN(end.getTime())) {
      start.setHours(0, 0, 0, 0)
      end.setHours(23, 59, 59, 999)
      params.start = start.toISOString()
      params.end = end.toISOString()
    }
  }
  return params
}

async function load(nextPage?: number) {
  if (nextPage) page.value = nextPage
  const sequence = ++requestSeq
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get('/logs', { params: buildParams() })
    if (sequence !== requestSeq) return
    rows.value = Array.isArray(data.items) ? data.items : []
    total.value = Number(data.total || 0)
  } catch (error: any) {
    if (sequence === requestSeq) loadError.value = errorDetail(error, '日志请求失败，请检查后端连接')
  } finally {
    if (sequence === requestSeq) loading.value = false
  }
}

async function loadCategories() {
  try {
    const { data } = await api.get('/logs/categories')
    categories.value = Array.isArray(data) ? data : []
  } catch {
    categories.value = []
  }
}

async function loadRetention() {
  try {
    const { data } = await api.get('/system/settings')
    const rowsData = Array.isArray(data) ? data : []
    const row = rowsData.find((item: any) => item.key === 'data_retention_days')
    if (!row) return
    const raw = row.value && typeof row.value === 'object' && 'value' in row.value ? row.value.value : row.value
    const days = Number(raw)
    if (!Number.isFinite(days)) return
    retentionDays.value = days
    retentionSaved.value = days
    retentionVisible.value = true
  } catch {
    retentionVisible.value = false
  }
}

async function saveRetention() {
  if (retentionDays.value === null || savingRetention.value) return
  const next = retentionDays.value
  savingRetention.value = true
  try {
    await api.put('/system/settings/data_retention_days', { value: next })
    retentionSaved.value = next
    ElMessage.success(next > 0
      ? `已保存：全局数据保留 ${next} 天，每日清理任务会自动执行`
      : '已关闭自动清理，全局数据将永久保留')
  } catch (error: any) {
    if (retentionSaved.value !== null) retentionDays.value = retentionSaved.value
    ElMessage.error(errorDetail(error, '保存失败，需要系统设置权限'))
  } finally {
    savingRetention.value = false
  }
}

function clearFilters() {
  filters.keyword = ''
  filters.category = ''
  filters.level = ''
  timeRange.value = null
  load(1)
}

function showContext(row: any) {
  contextRow.value = row
  contextDialog.value = true
}

function logText(row: any) {
  const lines = [
    `#${row.id} [${String(row.level || 'INFO').toUpperCase()}] ${categoryLabel(row.category)}`,
    `时间：${formatDate(row.created_at)}`,
    `账号：${row.account_id ? `#${row.account_id}` : '—'}`,
    '',
    String(row.message || ''),
  ]
  if (row.context) {
    lines.push('', '上下文 JSON：', formatContext(row.context))
  }
  return lines.join('\n')
}

async function copyText(text: string, key: string, label: string) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      if (copiedKey.value === key) copiedKey.value = ''
    }, 2000)
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.error('复制失败，请检查浏览器剪贴板权限或使用 HTTPS 访问')
  }
}

function copyLog(row: any) {
  if (!row) return
  void copyText(logText(row), `log-${row.id}`, '日志详情')
}

function copyContext(row: any, key: string) {
  if (!row?.context) return
  void copyText(formatContext(row.context), key, '上下文 JSON ')
}

function emptyAction() {
  if (loadError.value) load()
  else if (hasFilters.value) clearFilters()
  else load()
}

onMounted(() => {
  void loadCategories()
  void loadRetention()
  void load()
})

onBeforeUnmount(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<style scoped>
.logs-error {
  margin-bottom: 14px;
}

.retention-box {
  display: flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  min-height: 34px;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.retention-caption {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 10px;
  white-space: nowrap;
}

.retention-select {
  width: 108px;
}

:global(.retention-tooltip-popper) {
  max-width: min(340px, calc(100vw - 28px));
  line-height: 1.65;
}

.retention-info {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: none;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-4);
  cursor: pointer;
}

.retention-info:hover {
  color: var(--text-2);
  background: var(--surface-3);
}

.logs-surface {
  min-width: 0;
}

.logs-toolbar {
  align-items: center;
  flex-wrap: wrap;
}

.log-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}

.log-search {
  width: 300px;
}

.filter-select {
  width: 150px;
}

.level-filter {
  width: 132px;
}

.date-filter {
  width: 250px;
}

.log-results {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
  margin-left: auto;
  color: var(--text-4);
  font-size: 10px;
  white-space: nowrap;
}

.log-result-count {
  color: var(--text-2);
  font-weight: 550;
}

.log-page-indicator {
  padding-left: 8px;
  border-left: 1px solid var(--line);
}

.logs-table :deep(.el-table__expanded-cell) {
  padding: 0;
  background: var(--surface-2) !important;
}

.level-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 23px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 600;
  white-space: nowrap;
}

.level-badge.info {
  color: var(--info);
  border-color: var(--info-line);
  background: var(--info-soft);
}

.level-badge.warning {
  color: var(--warning);
  border-color: var(--warning-line);
  background: var(--warning-soft);
}

.level-badge.danger {
  color: var(--danger);
  border-color: var(--danger-line);
  background: var(--danger-soft);
}

.category-label {
  color: var(--text-2);
  font-size: 11px;
}

.account-ref {
  color: var(--text-3);
  font-size: 10px;
}

.log-time {
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-variant-numeric: tabular-nums;
}

.log-time b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 550;
}

.log-time small {
  color: var(--text-4);
  font-size: 9px;
}

.log-message {
  color: var(--text-2);
  line-height: 1.6;
}

.log-detail {
  min-width: 0;
  padding: 16px 18px 18px;
  background: var(--surface-2);
}

.log-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.log-detail-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.log-detail-heading time {
  color: var(--text-4);
  font-size: 9.5px;
}

.detail-id {
  color: var(--text-3);
  font-size: 10px;
}

.detail-category {
  color: var(--text-2);
  font-size: 10.5px;
}

.log-detail-message {
  margin: 12px 0 0;
  color: var(--text);
  font-size: 12px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.context-section {
  margin-top: 14px;
}

.context-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 7px;
}

.context-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.context-code {
  max-height: 280px;
  margin: 7px 0 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--code-bg);
  color: var(--text-2);
  font: 500 10.5px/1.65 var(--font-mono);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.stack-code {
  border-color: var(--danger-line);
}

.detail-empty {
  margin-top: 14px;
  padding: 11px 12px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-sm);
  color: var(--text-4);
  font-size: 10px;
}

.logs-empty {
  min-height: 170px;
}

.logs-empty b {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.logs-empty span {
  max-width: 420px;
  line-height: 1.65;
}

.context-dialog-body {
  min-width: 0;
}

.dialog-summary {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.dialog-summary time {
  margin-left: auto;
  color: var(--text-4);
  font-size: 10px;
}

.dialog-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  color: var(--text-3);
  font-size: 9.5px;
}

.dialog-block {
  margin-top: 16px;
}

.dialog-message {
  max-height: 220px;
  margin: 7px 0 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.dialog-code {
  max-height: 42vh;
}

.dialog-empty {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 16px;
  padding: 12px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-sm);
  color: var(--text-4);
  font-size: 10.5px;
}

@media (max-width: 1100px) {
  .logs-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .log-filters {
    width: 100%;
  }

  .log-results {
    margin-left: 0;
  }
}

@media (max-width: 840px) {
  .log-search,
  .filter-select,
  .level-filter,
  .date-filter {
    width: 100%;
    max-width: none;
  }

  .log-results {
    flex-wrap: wrap;
  }
}

@media (max-width: 600px) {
  .retention-box {
    flex: 1 1 auto;
  }

  .retention-select {
    width: 104px;
  }

  .log-page-indicator {
    padding-left: 0;
    border-left: 0;
  }

  .log-detail {
    padding: 14px 12px 16px;
  }

  .dialog-summary time {
    width: 100%;
    margin-left: 0;
  }

  .dialog-code {
    max-height: 36vh;
  }

  .pagination-wrap :deep(.el-pagination) {
    max-width: 100%;
    flex-wrap: wrap;
    row-gap: 8px;
  }
}
</style>
