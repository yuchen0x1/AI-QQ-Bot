<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">
        INFRASTRUCTURE TELEMETRY
        <span class="realtime-badge"><i class="socket-led" :class="liveLed"></i>{{ liveLabel }}</span>
      </div>
      <h1>系统监控</h1>
      <p>读取当前进程、数据库、缓存与任务调度器的真实状态；资源趋势每 5 秒采样一次，页面隐藏时自动暂停。</p>
    </div>
    <div class="heading-actions">
      <el-button :loading="loading" :disabled="loading" @click="refreshAllData">
        <AppIcon name="refresh" :size="14" style="margin-right:5px" />刷新状态
      </el-button>
    </div>
  </div>

  <el-alert v-if="loadError" type="error" show-icon :closable="false" class="system-error" title="系统状态加载失败">
    <template #default>
      <span>{{ loadError }}</span>
      <el-button link type="primary" @click="refreshAllData">重试</el-button>
    </template>
  </el-alert>

  <div v-loading="loading" class="page-stack system-shell" :aria-busy="loading">
    <div class="telemetry-strip">
      <div class="telemetry-status" :class="liveState" role="status" aria-live="polite">
        <span class="telemetry-led" aria-hidden="true"></span>
        <div>
          <b>{{ liveLabel }}</b>
          <small>{{ liveDetail }}</small>
        </div>
      </div>
      <div class="telemetry-facts">
        <span><small>最后同步</small><b>{{ lastSyncedText }}</b></span>
        <span><small>历史样本</small><b>{{ samples.length }} / 60</b></span>
        <span><small>采样间隔</small><b>5 秒</b></span>
        <span><small>数据源</small><b class="mono">/system/stats</b></span>
      </div>
    </div>

    <div class="stat-grid telemetry-grid">
      <article v-for="card in resourceCards" :key="card.key" class="stat-tile telemetry-tile">
        <span class="stat-tile-icon" :class="card.tone"><AppIcon :name="card.icon" :size="18" /></span>
        <div class="stat-tile-copy telemetry-copy">
          <span class="stat-tile-label">{{ card.label }}</span>
          <div class="stat-tile-value telemetry-value">{{ card.value }}<small v-if="card.hasValue">%</small></div>
          <span class="stat-tile-meta">{{ card.detail }}</span>
          <div
            v-if="card.hasValue"
            class="telemetry-meter"
            :class="card.tone"
            role="progressbar"
            :aria-label="`${card.label}使用率`"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="card.percent"
            :aria-valuetext="`${card.value}%`"
          >
            <i :style="{ width: `${card.percent}%` }"></i>
          </div>
          <span v-else class="telemetry-pending">等待首次采样</span>
        </div>
      </article>
    </div>

    <section class="surface trend-surface">
      <div class="surface-head trend-head">
        <div><h3>资源趋势</h3><p>客户端保留最近 60 个真实采样点，至少 2 个样本后绘制曲线。</p></div>
        <div class="trend-tools">
          <span class="trend-count">{{ samples.length ? `采集中 ${samples.length} 个样本` : '等待样本' }}</span>
          <span class="trend-legend" aria-hidden="true">
            <span class="cpu"><i></i>CPU</span>
            <span class="memory"><i></i>内存</span>
            <span class="disk"><i></i>磁盘</span>
          </span>
        </div>
      </div>

      <div v-if="pollError" class="poll-warning" role="alert">
        <AppIcon name="alert" :size="15" />
        <span>最近一次后台采样失败：{{ pollError }}</span>
        <el-button link type="primary" @click="pollNow">立即重试</el-button>
      </div>

      <div class="trend-stage">
        <AsyncChart v-if="samples.length >= 2" class="trend-chart" :option="trendOption" autoresize style="width: 100%; height: 100%" />
        <div v-else class="trend-empty">
          <span class="trend-empty-icon"><AppIcon name="chart" :size="24" /></span>
          <b>{{ pollError ? '趋势采样已中断' : '正在采集真实样本' }}</b>
          <p v-if="pollError">已保留 {{ samples.length }} 个样本。恢复连接后将自动继续，不会补造历史点。</p>
          <p v-else>当前 {{ samples.length }} 个样本，至少需要 2 个才能绘制曲线。采样每 5 秒执行一次。</p>
          <el-button v-if="pollError" size="small" @click="pollNow">立即重试</el-button>
        </div>
      </div>
      <p class="sr-only">折线图展示 CPU、内存与磁盘使用率随时间的变化，纵轴范围为 0 到 100%。</p>
    </section>

    <div class="split-grid">
      <section class="surface runtime-surface">
        <div class="surface-head">
          <div><h3>主机与运行时</h3><p>来自当前管理 API 进程的运行时信息</p></div>
          <span class="runtime-source"><AppIcon name="activity" :size="13" />实时探针</span>
        </div>
        <div class="detail-list">
          <div class="detail-row"><span>Python 运行时</span><b class="mono">{{ stats?.python_version || '—' }}</b></div>
          <div class="detail-row"><span>系统负载（1 / 5 / 15 分钟）</span><b class="mono">{{ loadText }}</b></div>
          <div class="detail-row"><span>应用运行时长</span><b>{{ duration(stats?.uptime_seconds) }}</b></div>
          <div class="detail-row"><span>进程运行时长</span><b>{{ duration(stats?.process_uptime_seconds) }}</b></div>
          <div class="detail-row"><span>调度任务</span><b>{{ stats ? `${stats.scheduler_jobs ?? 0} 个已注册` : '—' }}</b></div>
          <div class="detail-row"><span>最近采样</span><b>{{ lastSyncedText }}</b></div>
        </div>
      </section>

      <section class="surface services-surface">
        <div class="surface-head">
          <div><h3>依赖服务状态</h3><p>数据库、可选缓存与任务调度器健康检查</p></div>
          <span class="health-summary" :class="health.tone">
            <AppIcon :name="health.icon" :size="13" />{{ health.label }}
          </span>
        </div>
        <div class="service-list">
          <div v-for="service in services" :key="service.key" class="service-row">
            <span class="service-icon" :class="service.tone"><AppIcon :name="service.icon" :size="17" /></span>
            <div class="service-copy">
              <b>{{ service.label }}</b>
              <small>{{ service.detail }}</small>
            </div>
            <span class="service-state" :class="service.tone">
              <AppIcon :name="service.stateIcon" :size="13" />{{ service.state }}
            </span>
          </div>
        </div>
      </section>
    </div>

    <section class="surface backup-panel">
      <div class="surface-head">
        <div><h3>数据库备份</h3><p>将当前数据库备份到服务器持久化目录；完成备份后会自动刷新列表。</p></div>
        <div class="backup-actions">
          <span class="backup-count">{{ backupsLoaded ? `${backups.length} 份` : '— 份' }}</span>
          <el-button :loading="backupsLoading" :disabled="backupLoading" @click="loadBackups">
            <AppIcon name="refresh" :size="14" style="margin-right:5px" />刷新列表
          </el-button>
          <el-button type="primary" :loading="backupLoading" :disabled="backupLoading || backupsLoading" @click="createBackup">
            <AppIcon name="database" :size="14" style="margin-right:5px" />立即备份
          </el-button>
        </div>
      </div>

      <el-alert v-if="backupError" type="error" show-icon :closable="false" class="backup-error" title="备份状态异常">
        <template #default><span>{{ backupError }}</span></template>
      </el-alert>

      <div class="backup-table-wrap">
        <el-table v-loading="backupsLoading" :data="backups" stripe row-key="name" style="width: 100%">
          <el-table-column label="备份文件" min-width="280">
            <template #default="{ row }">
              <div class="backup-file">
                <span class="backup-file-icon"><AppIcon name="folder" :size="15" /></span>
                <span class="mono">{{ row.name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="文件大小" width="130" align="right">
            <template #default="{ row }">{{ formatBackupSize(row) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="190">
            <template #default="{ row }">
              <time :datetime="row.created_at">{{ formatDate(row.created_at) }}</time>
            </template>
          </el-table-column>
          <template #empty>
            <div v-if="backupError" class="empty-inline backup-empty">
              <span class="backup-empty-icon"><AppIcon name="alert" :size="26" /></span>
              <b>备份列表暂不可用</b>
              <span>检查后端连接或访问权限后重试。</span>
              <el-button size="small" @click="loadBackups">重试</el-button>
            </div>
            <div v-else-if="!backupsLoaded" class="empty-inline backup-empty">
              <span class="backup-empty-icon"><AppIcon name="refresh" :size="26" /></span>
              <b>正在读取备份列表</b>
              <span>从服务器持久化目录读取现有备份文件。</span>
            </div>
            <div v-else class="empty-inline backup-empty">
              <span class="backup-empty-icon"><AppIcon name="folder" :size="26" /></span>
              <b>尚无数据库备份</b>
              <span>点击“立即备份”生成第一份服务器端数据库快照。</span>
            </div>
          </template>
        </el-table>
      </div>
      <div class="backup-foot">
        <AppIcon name="info" :size="13" />
        备份使用数据库在线快照或 pg_dump 生成；创建后会按系统设置的保留数量清理旧文件。
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import { chartTheme } from '../theme'

const AsyncChart = defineAsyncComponent(async () => {
  const [{ use }, { CanvasRenderer }, { LineChart }, { GridComponent, TooltipComponent }, { default: VChart }] =
    await Promise.all([
      import('echarts/core'),
      import('echarts/renderers'),
      import('echarts/charts'),
      import('echarts/components'),
      import('vue-echarts'),
    ])
  use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])
  return VChart
})

type TelemetrySample = {
  time: number
  cpu: number
  memory: number
  disk: number
}

const stats = ref<any>(null)
const backups = ref<any[]>([])
const backupsLoaded = ref(false)
const loading = ref(false)
const backupsLoading = ref(false)
const backupLoading = ref(false)
const loadError = ref('')
const backupError = ref('')
const pollError = ref('')
const statsBusy = ref(false)
const samples = ref<TelemetrySample[]>([])
const lastSyncedAt = ref<Date | null>(null)
const pageHidden = ref(typeof document !== 'undefined' ? document.hidden : false)
let pollTimer: ReturnType<typeof setInterval> | undefined
let disposed = false
let statsEpoch = 0

const liveState = computed(() => {
  if (pageHidden.value) return 'paused'
  if (pollError.value) return 'error'
  return stats.value ? 'live' : 'waiting'
})

const liveLabel = computed(() => ({
  live: '实时采样中',
  paused: '采样已暂停',
  error: '采样中断',
  waiting: '等待数据',
} as Record<string, string>)[liveState.value] || '等待数据')

const liveLed = computed(() => {
  if (liveState.value === 'live') return 'open'
  if (liveState.value === 'error') return 'error'
  if (liveState.value === 'waiting') return 'connecting'
  return ''
})

const liveDetail = computed(() => {
  if (liveState.value === 'paused') return '页面隐藏，轮询已暂停；返回后立即同步'
  if (liveState.value === 'error') return '后台采样失败，现有样本保持不变'
  if (liveState.value === 'live') return '每 5 秒读取 /system/stats；页面隐藏时暂停'
  return '正在读取首个 /system/stats 样本'
})

const lastSyncedText = computed(() => {
  if (!lastSyncedAt.value) return '—'
  return lastSyncedAt.value.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
})

const loadText = computed(() => {
  const values = stats.value?.load_average
  return Array.isArray(values) && values.length ? values.join(' / ') : '—'
})

const health = computed(() => {
  if (!stats.value) return { tone: 'waiting', label: '等待采集', icon: 'info' }
  if (!stats.value.db_ok) return { tone: 'bad', label: '数据库异常', icon: 'alert' }
  if (stats.value.redis_enabled && !stats.value.redis_ok) return { tone: 'bad', label: 'Redis 异常', icon: 'alert' }
  if (!stats.value.scheduler_running) return { tone: 'warning', label: '调度器未运行', icon: 'alert' }
  return { tone: 'ok', label: '核心服务正常', icon: 'check-circle' }
})

const resourceCards = computed(() => {
  const current = stats.value
  return [
    {
      key: 'cpu',
      label: 'CPU 使用率',
      icon: 'cpu',
      tone: 'brand',
      value: current ? formatPercent(current.cpu_percent) : '—',
      percent: current ? clamp(current.cpu_percent) : 0,
      hasValue: Boolean(current),
      detail: current ? `负载 ${loadText.value}` : '等待 /system/stats 返回',
    },
    {
      key: 'memory',
      label: '内存使用率',
      icon: 'memory',
      tone: 'cyan',
      value: current ? formatPercent(current.memory_percent) : '—',
      percent: current ? clamp(current.memory_percent) : 0,
      hasValue: Boolean(current),
      detail: current ? `${formatGB(current.memory_used_mb)} / ${formatGB(current.memory_total_mb)} GB` : '等待 /system/stats 返回',
    },
    {
      key: 'disk',
      label: '磁盘占用率',
      icon: 'disk',
      tone: 'green',
      value: current ? formatPercent(current.disk_percent) : '—',
      percent: current ? clamp(current.disk_percent) : 0,
      hasValue: Boolean(current),
      detail: current ? `${formatNumber(current.disk_used_gb)} / ${formatNumber(current.disk_total_gb)} GB` : '等待 /system/stats 返回',
    },
  ]
})

const services = computed(() => {
  if (!stats.value) {
    return [
      { key: 'db', label: 'PostgreSQL 数据库', icon: 'database', tone: 'waiting', stateIcon: 'info', state: '等待采集', detail: '等待首轮健康检查结果' },
      { key: 'redis', label: 'Redis 缓存', icon: 'layers', tone: 'waiting', stateIcon: 'info', state: '等待采集', detail: '等待首轮健康检查结果' },
      { key: 'scheduler', label: '任务调度器', icon: 'timer', tone: 'waiting', stateIcon: 'info', state: '等待采集', detail: '等待首轮健康检查结果' },
    ]
  }
  const current = stats.value
  const redisTone = !current.redis_enabled ? 'neutral' : current.redis_ok ? 'ok' : 'bad'
  return [
    {
      key: 'db',
      label: 'PostgreSQL 数据库',
      icon: 'database',
      tone: current.db_ok ? 'ok' : 'bad',
      stateIcon: current.db_ok ? 'check-circle' : 'alert',
      state: current.db_ok ? '正常' : '异常',
      detail: current.db_ok ? '业务数据与配置存储连接正常' : '数据库连接检查失败',
    },
    {
      key: 'redis',
      label: 'Redis 缓存',
      icon: 'layers',
      tone: redisTone,
      stateIcon: redisTone === 'neutral' ? 'info' : redisTone === 'ok' ? 'check-circle' : 'alert',
      state: redisTone === 'neutral' ? '未启用' : redisTone === 'ok' ? '正常' : '异常',
      detail: !current.redis_enabled ? '配置未启用 Redis（可选依赖）' : current.redis_ok ? '已启用并通过连通性检查' : '已启用，但 PING 检查未通过',
    },
    {
      key: 'scheduler',
      label: '任务调度器',
      icon: 'timer',
      tone: current.scheduler_running ? 'ok' : 'warning',
      stateIcon: current.scheduler_running ? 'check-circle' : 'pause',
      state: current.scheduler_running ? '运行中' : '未运行',
      detail: `${current.scheduler_jobs ?? 0} 个调度任务已注册`,
    },
  ]
})

function sampleLabel(time: number) {
  return new Date(time).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

const trendOption = computed(() => {
  const palette = chartTheme.value
  const labels = samples.value.map((sample) => sampleLabel(sample.time))
  return {
    animationDuration: 360,
    animationDurationUpdate: 260,
    grid: { left: 8, right: 14, top: 18, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: palette.tooltipBg,
      borderColor: palette.tooltipBorder,
      textStyle: { color: palette.text, fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: palette.axis } },
      valueFormatter: (value: number) => `${value}%`,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels,
      axisLine: { lineStyle: { color: palette.axis } },
      axisTick: { show: false },
      axisLabel: { color: palette.muted, fontSize: 10, margin: 12, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      interval: 25,
      splitLine: { lineStyle: { color: palette.split, type: 'dashed' } },
      axisLabel: { color: palette.muted, fontSize: 10, formatter: '{value}%' },
    },
    series: [
      {
        name: 'CPU',
        type: 'line',
        smooth: 0.28,
        showSymbol: false,
        data: samples.value.map((sample) => sample.cpu),
        lineStyle: { color: palette.brand, width: 2 },
        itemStyle: { color: palette.brand },
        emphasis: { focus: 'series' },
      },
      {
        name: '内存',
        type: 'line',
        smooth: 0.28,
        showSymbol: false,
        data: samples.value.map((sample) => sample.memory),
        lineStyle: { color: palette.cyan, width: 2 },
        itemStyle: { color: palette.cyan },
        emphasis: { focus: 'series' },
      },
      {
        name: '磁盘',
        type: 'line',
        smooth: 0.28,
        showSymbol: false,
        data: samples.value.map((sample) => sample.disk),
        lineStyle: { color: palette.success, width: 2 },
        itemStyle: { color: palette.success },
        emphasis: { focus: 'series' },
      },
    ],
  }
})

function clamp(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, number))
}

function formatPercent(value: unknown) {
  const number = clamp(value)
  return Number.isInteger(number) ? String(number) : number.toFixed(1)
}

function formatNumber(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(1) : '—'
}

function formatGB(valueMb: unknown) {
  const number = Number(valueMb)
  return Number.isFinite(number) ? (number / 1024).toFixed(1) : '—'
}

function duration(seconds: unknown) {
  if (seconds === null || seconds === undefined) return '—'
  const total = Math.max(0, Math.floor(Number(seconds)))
  if (!Number.isFinite(total)) return '—'
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const parts: string[] = []
  if (days) parts.push(`${days} 天`)
  if (hours) parts.push(`${hours} 小时`)
  if (minutes) parts.push(`${minutes} 分`)
  return parts.length ? parts.join(' ') : '不到 1 分钟'
}

function formatDate(value: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN')
}

function formatBackupSize(row: any) {
  const sizeMb = Number(row?.size_mb)
  if (row?.size_mb !== null && row?.size_mb !== undefined && Number.isFinite(sizeMb)) return `${sizeMb.toFixed(2)} MB`
  const bytes = Number(row?.size_bytes)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(1)} ${units[index]}`
}

function errorDetail(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length) return String(detail[0]?.msg || fallback)
  if (typeof error?.message === 'string' && error.message) return error.message
  return fallback
}

function applyStats(next: any) {
  stats.value = next
  const now = Date.now()
  lastSyncedAt.value = new Date(now)
  loadError.value = ''
  pollError.value = ''
  samples.value.push({
    time: now,
    cpu: clamp(next?.cpu_percent),
    memory: clamp(next?.memory_percent),
    disk: clamp(next?.disk_percent),
  })
  if (samples.value.length > 60) samples.value.splice(0, samples.value.length - 60)
}

async function fetchStatsSilently() {
  const response = await fetch('/api/system/stats', {
    credentials: 'include',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  })
  if (response.status === 401) {
    window.location.assign('/login')
    throw new Error('登录状态已失效')
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string' && body.detail) detail = body.detail
    } catch {}
    throw new Error(detail)
  }
  return response.json()
}

async function pollStats() {
  if (disposed || pageHidden.value || statsBusy.value || loading.value) return
  const epoch = statsEpoch
  statsBusy.value = true
  try {
    const next = await fetchStatsSilently()
    if (!disposed && epoch === statsEpoch) applyStats(next)
  } catch (error: any) {
    if (!disposed && epoch === statsEpoch) pollError.value = errorDetail(error, '后台采样失败')
  } finally {
    statsBusy.value = false
  }
}

async function load() {
  statsEpoch += 1
  loading.value = true
  loadError.value = ''
  backupError.value = ''
  const [statsResult, backupsResult] = await Promise.allSettled([
    api.get('/system/stats'),
    api.get('/system/backups'),
  ])
  if (statsResult.status === 'fulfilled') {
    applyStats(statsResult.value.data)
  } else {
    loadError.value = errorDetail(statsResult.reason, '系统状态请求失败，请检查后端连接')
  }
  if (backupsResult.status === 'fulfilled') {
    backups.value = Array.isArray(backupsResult.value.data) ? backupsResult.value.data : []
    backupsLoaded.value = true
  } else {
    backupError.value = errorDetail(backupsResult.reason, '备份列表加载失败')
  }
  loading.value = false
}

async function loadBackups() {
  if (backupsLoading.value) return
  backupsLoading.value = true
  backupError.value = ''
  try {
    const { data } = await api.get('/system/backups')
    backups.value = Array.isArray(data) ? data : []
    backupsLoaded.value = true
  } catch (error: any) {
    backupError.value = errorDetail(error, '备份列表加载失败')
  } finally {
    backupsLoading.value = false
  }
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = undefined
}

function startPolling() {
  stopPolling()
  if (disposed || pageHidden.value) return
  pollTimer = setInterval(() => { void pollStats() }, 5000)
}

async function refreshAllData() {
  if (loading.value) return
  stopPolling()
  await load()
  if (!pageHidden.value && !disposed) startPolling()
}

async function createBackup() {
  if (backupLoading.value) return
  backupLoading.value = true
  backupError.value = ''
  try {
    const { data } = await api.post('/system/backup')
    ElMessage.success(data.message || data.detail || '已创建备份')
    stopPolling()
    await load()
    if (!pageHidden.value && !disposed) startPolling()
  } catch (error: any) {
    backupError.value = errorDetail(error, '创建备份失败')
  } finally {
    backupLoading.value = false
  }
}

function pollNow() {
  void pollStats()
}

function handleVisibility() {
  pageHidden.value = document.hidden
  if (document.hidden) {
    stopPolling()
    return
  }
  if (!disposed) {
    void pollStats()
    startPolling()
  }
}

onMounted(async () => {
  pageHidden.value = document.hidden
  document.addEventListener('visibilitychange', handleVisibility)
  await refreshAllData()
})

onBeforeUnmount(() => {
  disposed = true
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<style scoped>
.system-error {
  margin-bottom: 14px;
}

.system-shell {
  gap: 14px;
}

.telemetry-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--surface) 78%, transparent);
  box-shadow: var(--shadow-xs);
}

.telemetry-status {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.telemetry-led {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: var(--text-4);
  box-shadow: 0 0 0 3px var(--line-soft);
}

.telemetry-status.live .telemetry-led {
  background: var(--success);
  box-shadow: 0 0 0 3px var(--success-soft);
}

.telemetry-status.waiting .telemetry-led {
  background: var(--warning);
  box-shadow: 0 0 0 3px var(--warning-soft);
}

.telemetry-status.error .telemetry-led {
  background: var(--danger);
  box-shadow: 0 0 0 3px var(--danger-soft);
}

.telemetry-status b {
  display: block;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
}

.telemetry-status small {
  display: block;
  margin-top: 2px;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.5;
}

.telemetry-facts {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.telemetry-facts > span {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.telemetry-facts small {
  color: var(--text-4);
  font-size: 9px;
}

.telemetry-facts b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 600;
}

.stat-grid.telemetry-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 0;
}

.telemetry-tile {
  align-items: flex-start;
  min-height: 142px;
  padding: 17px 18px;
}

.telemetry-copy {
  flex: 1;
  gap: 4px;
}

.telemetry-value {
  font-size: 28px;
  font-variant-numeric: tabular-nums;
}

.telemetry-meter {
  width: 100%;
  height: 5px;
  margin-top: 8px;
  overflow: hidden;
  border-radius: 99px;
  background: var(--surface-3);
}

.telemetry-meter i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--text-3);
  transition: width 600ms var(--ease);
}

.telemetry-meter.brand i {
  background: var(--brand);
}

.telemetry-meter.cyan i {
  background: var(--cyan);
}

.telemetry-meter.green i {
  background: var(--success);
}

.telemetry-pending {
  margin-top: 7px;
  color: var(--text-4);
  font-size: 9.5px;
}

.trend-surface {
  padding: 18px 18px 14px;
}

.trend-head {
  align-items: flex-start;
  flex-wrap: wrap;
}

.trend-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.trend-count {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font: 600 9.5px var(--font-mono);
  white-space: nowrap;
}

.trend-legend {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.trend-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 10px;
  white-space: nowrap;
}

.trend-legend i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand);
}

.trend-legend .memory i {
  background: var(--cyan);
}

.trend-legend .disk i {
  background: var(--success);
}

.poll-warning {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 12px;
  padding: 9px 11px;
  border: 1px solid var(--warning-line);
  border-radius: var(--radius-sm);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 10.5px;
  line-height: 1.5;
}

.poll-warning span {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.trend-stage {
  position: relative;
  height: 300px;
  min-width: 0;
}

.trend-chart {
  width: 100%;
  height: 100%;
}

.trend-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  height: 100%;
  padding: 24px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--surface-2) 45%, transparent);
  text-align: center;
}

.trend-empty-icon {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  margin-bottom: 3px;
  border: 1px solid var(--brand-line);
  border-radius: var(--radius-md);
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.trend-empty b {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}

.trend-empty p {
  max-width: 460px;
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.7;
}

.runtime-source,
.health-summary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font: 600 9px var(--font-mono);
  white-space: nowrap;
}

.runtime-source {
  color: var(--brand-strong);
  border-color: var(--brand-line);
  background: var(--brand-soft);
}

.health-summary.ok {
  color: var(--success);
  border-color: var(--success-line);
  background: var(--success-soft);
  font-family: var(--font-sans);
  font-size: 9.5px;
}

.health-summary.warning {
  color: var(--warning);
  border-color: var(--warning-line);
  background: var(--warning-soft);
  font-family: var(--font-sans);
  font-size: 9.5px;
}

.health-summary.bad {
  color: var(--danger);
  border-color: var(--danger-line);
  background: var(--danger-soft);
  font-family: var(--font-sans);
  font-size: 9.5px;
}

.health-summary.waiting {
  font-family: var(--font-sans);
  font-size: 9.5px;
}

.service-list {
  display: flex;
  flex-direction: column;
}

.service-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 0;
  border-top: 1px solid var(--line-soft);
}

.service-row:first-child {
  border-top: 0;
}

.service-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  color: var(--text-3);
}

.service-icon.ok {
  color: var(--success);
  border-color: var(--success-line);
  background: var(--success-soft);
}

.service-icon.bad {
  color: var(--danger);
  border-color: var(--danger-line);
  background: var(--danger-soft);
}

.service-icon.warning {
  color: var(--warning);
  border-color: var(--warning-line);
  background: var(--warning-soft);
}

.service-icon.waiting {
  color: var(--info);
  border-color: var(--info-line);
  background: var(--info-soft);
}

.service-copy {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.service-copy b {
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
}

.service-copy small {
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.service-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  min-height: 23px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 600;
}

.service-state.ok {
  color: var(--success);
  border-color: var(--success-line);
  background: var(--success-soft);
}

.service-state.bad {
  color: var(--danger);
  border-color: var(--danger-line);
  background: var(--danger-soft);
}

.service-state.warning {
  color: var(--warning);
  border-color: var(--warning-line);
  background: var(--warning-soft);
}

.service-state.waiting {
  color: var(--info);
  border-color: var(--info-line);
  background: var(--info-soft);
}

.backup-panel .surface-head {
  align-items: center;
}

.backup-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.backup-count {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font: 600 9.5px var(--font-mono);
  white-space: nowrap;
}

.backup-error {
  margin-bottom: 12px;
}

.backup-table-wrap {
  overflow-x: auto;
  overflow-y: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
}

.backup-file {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.backup-file .mono {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.backup-file-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--brand-strong);
}

.backup-empty-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  color: var(--text-4);
}

.backup-empty b {
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 600;
}

.backup-foot {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 11px;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.6;
}

.backup-foot .app-icon {
  margin-top: 1px;
}

@media (max-width: 1100px) {
  .stat-grid.telemetry-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 840px) {
  .telemetry-strip {
    align-items: flex-start;
  }

  .telemetry-facts {
    width: 100%;
  }

  .backup-panel .surface-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .backup-actions {
    justify-content: flex-start;
    width: 100%;
  }
}

@media (max-width: 760px) {
  .stat-grid.telemetry-grid {
    grid-template-columns: 1fr;
  }

  .trend-tools {
    justify-content: flex-start;
  }

  .trend-stage {
    height: 250px;
  }
}

@media (max-width: 600px) {
  .telemetry-tile {
    min-height: 126px;
    padding: 15px 16px;
  }

  .telemetry-facts {
    gap: 10px 16px;
  }

  .telemetry-facts > span {
    min-width: 92px;
  }

  .trend-surface {
    padding: 16px 12px 12px;
  }

  .trend-stage {
    height: 230px;
  }

  .backup-actions .el-button {
    flex: 1;
  }
}
</style>
