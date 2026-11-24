<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">OPERATIONS OVERVIEW <span class="realtime-badge"><i :class="`socket-led ${realtime.state.value}`"></i>{{ realtimeLabel }}</span></div>
      <h1>仪表盘</h1>
      <p>实时掌握 QQ 机器人集群、AI 模型、GitHub 监控与推送投递的运行状态。</p>
    </div>
    <div class="heading-actions">
      <el-button v-if="realtime.state.value !== 'open'" text type="primary" @click="realtime.reconnect">
        <AppIcon name="refresh" :size="14" style="margin-right:5px" />重新连接
      </el-button>
      <el-button :loading="loading" @click="load()">
        <AppIcon name="refresh" :size="14" style="margin-right:5px" />刷新数据
      </el-button>
      <el-button type="primary" @click="$router.push('/system')">
        <AppIcon name="activity" :size="14" style="margin-right:5px" />系统监控
      </el-button>
    </div>
  </div>

  <el-alert v-if="loadError" type="error" show-icon :closable="false" class="dashboard-error" title="仪表盘数据加载失败">
    <template #default><span>{{ loadError }}</span><el-button link type="danger" @click="load()">重试</el-button></template>
  </el-alert>

  <div v-loading="loading" class="dashboard-shell">
    <section class="overview-banner">
      <div class="overview-copy">
        <div class="overview-kicker">
          <i class="socket-led" :class="health.ok ? 'open' : 'error'"></i>
          LIVE SYSTEM TELEMETRY
        </div>
        <h2 class="overview-title">{{ health.title }}</h2>
        <p class="overview-desc">{{ health.description }}<template v-if="lastUpdated"> · 数据更新于 {{ lastUpdated }}</template></p>
      </div>
      <div class="overview-facts">
        <div class="overview-fact"><span>在线账号</span><b>{{ data?.accounts_online ?? 0 }} / {{ data?.accounts_total ?? 0 }}</b></div>
        <div class="overview-fact"><span>今日消息</span><b>{{ number(data?.messages_today) }}</b></div>
        <div class="overview-fact"><span>推送成功率</span><b>{{ data?.push_success_rate ?? 100 }}%</b></div>
        <div class="overview-fact"><span>实时连接</span><b>{{ realtimeLabel }}</b></div>
      </div>
    </section>

    <div class="metric-grid">
      <div v-for="metric in metrics" :key="metric.label" class="metric-card">
        <div class="metric-top">
          <span>{{ metric.label }}</span>
          <span class="metric-icon" :class="metric.tone"><AppIcon :name="metric.icon" :size="15" /></span>
        </div>
        <div class="metric-value">{{ metric.value }}</div>
        <div class="metric-foot"><span :class="metric.footClass">{{ metric.foot }}</span><span>{{ metric.hint }}</span></div>
      </div>
    </div>

    <div class="dashboard-grid">
      <section class="surface chart-surface">
        <div class="surface-head">
          <div><h3>消息活动</h3><p>最近 7 天消息收取与发送趋势</p></div>
          <span class="legend"><i class="legend-in"></i>收取 <i class="legend-out"></i>发送</span>
        </div>
        <div class="chart-body">
          <div v-if="!hasMessageData" class="chart-empty">
            <span class="chart-empty-icon"><AppIcon name="chat" :size="20" /></span>
            <b>暂无消息活动</b>
            <p>账号收到或发出消息后，最近 7 天的趋势会显示在这里。</p>
          </div>
          <AsyncChart v-else class="trend-chart" :option="messageOption" autoresize />
        </div>
      </section>
      <section class="surface chart-surface">
        <div class="surface-head">
          <div><h3>AI 调用量</h3><p>每日模型请求与路由统计</p></div>
          <span class="chart-total">{{ number(aiTotal) }} <small>次</small></span>
        </div>
        <div class="chart-body">
          <div v-if="!hasAiData" class="chart-empty">
            <span class="chart-empty-icon"><AppIcon name="sparkles" :size="20" /></span>
            <b>暂无 AI 调用</b>
            <p>群聊触发 AI 问答后，调用量会按天汇总到这里。</p>
          </div>
          <AsyncChart v-else class="trend-chart" :option="aiOption" autoresize />
        </div>
      </section>
    </div>

    <div class="dashboard-grid lower-grid">
      <section class="surface">
        <div class="surface-head">
          <div><h3>账号运行状态</h3><p>已配置的 QQ 官方机器人账号</p></div>
          <el-button link type="primary" @click="$router.push('/accounts')">全部账号<AppIcon name="arrow-right" :size="13" style="margin-left:4px" /></el-button>
        </div>
        <div v-if="!data?.account_status?.length" class="empty-inline">
          <AppIcon name="bot" :size="28" />
          <span>还没有配置 QQ 机器人账号</span>
          <el-button type="primary" size="small" @click="$router.push('/accounts')">添加第一个机器人</el-button>
        </div>
        <div v-else class="account-list">
          <div v-for="account in data.account_status.slice(0, 6)" :key="account.id" class="account-row">
            <div class="account-avatar"><AppIcon name="bot" :size="16" /></div>
            <div class="account-info">
              <b>{{ account.nickname || account.name }}</b>
              <small>{{ accountMeta(account) }} · 管理 {{ account.group_count ?? 0 }} 个群</small>
            </div>
            <el-tag :type="account.state === 'online' ? 'success' : account.state === 'error' ? 'danger' : 'info'" size="small">
              {{ stateLabel(account.state) }}
            </el-tag>
          </div>
        </div>
      </section>

      <section class="surface">
        <div class="surface-head">
          <div><h3>近期系统事件</h3><p>最新日志与运行通知</p></div>
          <el-button link type="primary" @click="$router.push('/logs')">日志中心<AppIcon name="arrow-right" :size="13" style="margin-left:4px" /></el-button>
        </div>
        <div v-if="!data?.recent_events?.length" class="empty-inline">
          <AppIcon name="logs" :size="26" />
          <span>暂无近期事件</span>
        </div>
        <div v-else class="event-list">
          <div v-for="event in data.recent_events.slice(0, 6)" :key="event.id" class="event-row">
            <div class="event-mark" :class="String(event.level || '').toLowerCase()"></div>
            <div class="event-content">
              <b>{{ event.message }}</b>
              <small>{{ categoryLabel(event.category) }} · {{ formatTime(event.created_at) }}</small>
            </div>
          </div>
        </div>
      </section>
    </div>

    <div class="dashboard-grid health-grid">
      <section class="surface resource-panel">
        <div class="surface-head">
          <div><h3>主机资源</h3><p>CPU、内存与磁盘的实时占用</p></div>
          <span class="health-pill" :class="health.ok ? 'ok' : 'warn'"><i></i>{{ health.ok ? '健康' : '需关注' }}</span>
        </div>
        <div class="resource-list">
          <div v-for="resource in resources" :key="resource.label" class="resource-row">
            <div class="resource-label"><AppIcon :name="resource.icon" :size="14" /><span>{{ resource.label }}</span></div>
            <b>{{ resource.value }}<small>%</small></b>
            <div class="resource-bar"><i :style="{ width: `${Math.min(resource.value, 100)}%`, background: resource.color }"></i></div>
            <small class="resource-detail">{{ resource.detail }}</small>
          </div>
        </div>
      </section>

      <section class="surface">
        <div class="surface-head">
          <div><h3>异常告警</h3><p>来自系统日志的警告与错误</p></div>
          <el-button link type="primary" @click="$router.push('/logs')">查看全部</el-button>
        </div>
        <div v-if="!alerts.length" class="all-clear">
          <span class="all-clear-icon"><AppIcon name="shield" :size="22" /></span>
          <div><b>当前没有未处理告警</b><small>核心服务与实时连接均在正常阈值内</small></div>
        </div>
        <div v-else class="alert-list">
          <div v-for="alert in alerts" :key="alert.id" class="alert-row" :class="String(alert.level).toLowerCase()">
            <AppIcon name="alert" :size="15" />
            <div><b>{{ alert.message }}</b><small>{{ categoryLabel(alert.category) }} · {{ formatTime(alert.created_at) }}</small></div>
          </div>
        </div>
        <div class="service-health">
          <div><span><i :class="system?.db_ok ? 'ok' : 'bad'"></i>数据库</span><b>{{ system?.db_ok ? '正常' : '异常' }}</b></div>
          <div><span><i :class="!system?.redis_enabled || system?.redis_ok ? 'ok' : 'bad'"></i>Redis</span><b>{{ !system?.redis_enabled ? '未启用' : system?.redis_ok ? '正常' : '异常' }}</b></div>
          <div><span><i :class="system?.scheduler_running ? 'ok' : 'warn'"></i>任务调度</span><b>{{ system?.scheduler_running ? '运行中' : '已暂停' }}</b></div>
        </div>
      </section>

      <section class="surface signal-panel">
        <div class="surface-head">
          <div><h3>实时信号</h3><p>WebSocket 通道与运行时状态</p></div>
          <span class="signal-state" :class="realtime.state.value">{{ realtimeLabel }}</span>
        </div>
        <div class="signal-body">
          <div class="signal-orb" :class="realtime.state.value">
            <span></span><span></span><span></span>
            <AppIcon name="activity" :size="22" />
          </div>
          <div class="signal-copy">
            <b>{{ realtime.state.value === 'open' ? '遥测通道已建立' : '等待遥测通道' }}</b>
            <p>{{ realtime.state.value === 'open' ? '账号状态、消息量与在线数会实时推送到此面板。' : '正在建立与后端的实时连接，部分数据可能延迟。' }}</p>
            <div class="signal-meta">
              <span>在线运行时 <b>{{ realtime.lastMessage.value?.online ?? 0 }}</b></span>
              <span>已注册 <b>{{ realtime.lastMessage.value?.total_runtime ?? 0 }}</b></span>
              <span>今日消息 <b>{{ number(realtime.lastMessage.value?.messages_today ?? 0) }}</b></span>
            </div>
          </div>
        </div>
        <div class="signal-foot">
          <span>最后信号 {{ realtime.lastMessage.value?.time ? formatTime(realtime.lastMessage.value.time as string) : '等待同步' }}</span>
          <el-button v-if="realtime.state.value !== 'open'" link type="primary" @click="realtime.reconnect">重新连接</el-button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import { useStatusStore } from '../stores/status'
import { useAutoRefresh } from '../composables/useAutoRefresh'
import { chartTheme } from '../theme'

const AsyncChart = defineAsyncComponent(async () => {
  const [{ use }, { CanvasRenderer }, { LineChart, BarChart }, { GridComponent, TooltipComponent, LegendComponent }, { default: VChart }] =
    await Promise.all([
      import('echarts/core'),
      import('echarts/renderers'),
      import('echarts/charts'),
      import('echarts/components'),
      import('vue-echarts'),
    ])
  use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])
  return VChart
})

const loading = ref(false)
const data = ref<any>()
const system = ref<any>()
const loadError = ref('')
const lastUpdated = ref('')
const status = useStatusStore()
const { state: socketState, payload: socketPayload } = storeToRefs(status)
const realtime = { state: socketState, lastMessage: socketPayload, reconnect: status.reconnect }

const realtimeLabel = computed(() => ({
  open: '实时同步',
  connecting: '连接中',
  reconnecting: '重连中',
  closed: '已断开',
  error: '连接异常',
} as Record<string, string>)[socketState.value] || '等待连接')

const health = computed(() => {
  const issues: string[] = []
  if (system.value && !system.value.db_ok) issues.push('数据库')
  if (system.value?.redis_enabled && !system.value.redis_ok) issues.push('Redis')
  if (system.value && !system.value.scheduler_running) issues.push('任务调度')
  if (socketState.value === 'closed' || socketState.value === 'error') issues.push('实时通道')
  return {
    ok: issues.length === 0,
    title: issues.length ? '部分服务需要关注' : '机器人集群运行平稳',
    description: issues.length
      ? `${issues.join('、')}暂时不可用，其余核心服务仍在正常响应。`
      : '账号运行、消息收发、AI 路由与推送投递均保持在正常区间。',
  }
})

const metrics = computed(() => [
  {
    label: 'QQ 账号',
    value: number(data.value?.accounts_total),
    foot: `${data.value?.accounts_online ?? 0} 个在线`,
    hint: `${data.value?.accounts_offline ?? 0} 个离线`,
    icon: 'bot',
    tone: 'blue',
    footClass: 'accent',
  },
  {
    label: '今日消息',
    value: number(data.value?.messages_today),
    foot: `↑ ${number(data.value?.messages_sent_today)} 条发送`,
    hint: '收发合计',
    icon: 'chat',
    tone: 'cyan',
    footClass: 'green-text',
  },
  {
    label: 'AI 模型调用',
    value: number(data.value?.ai_calls_today),
    foot: '今日请求',
    hint: '多模型路由',
    icon: 'sparkles',
    tone: 'purple',
    footClass: 'accent',
  },
  {
    label: 'GitHub 仓库',
    value: number(data.value?.repos_total),
    foot: `${data.value?.releases_today ?? 0} 个今日版本`,
    hint: '持续监控',
    icon: 'branch',
    tone: 'orange',
    footClass: 'orange-text',
  },
  {
    label: '今日推送',
    value: number(data.value?.pushes_today),
    foot: `成功率 ${data.value?.push_success_rate ?? 100}%`,
    hint: `${data.value?.failed_tasks ?? 0} 个失败任务`,
    icon: 'send',
    tone: 'green',
    footClass: 'green-text',
  },
  {
    label: '群聊数量',
    value: number(data.value?.groups_total),
    foot: '已建档群聊',
    hint: '独立策略',
    icon: 'users',
    tone: 'pink',
    footClass: 'accent',
  },
])

const resources = computed(() => [
  {
    label: 'CPU 使用率',
    value: Math.round(Number(system.value?.cpu_percent ?? 0)),
    detail: `负载 ${system.value?.load_average?.join(' / ') || '—'}`,
    icon: 'activity',
    color: 'var(--brand)',
  },
  {
    label: '内存占用',
    value: Math.round(Number(system.value?.memory_percent ?? 0)),
    detail: `${((system.value?.memory_used_mb ?? 0) / 1024).toFixed(1)} / ${((system.value?.memory_total_mb ?? 0) / 1024).toFixed(1)} GB`,
    icon: 'server',
    color: 'var(--cyan)',
  },
  {
    label: '磁盘占用',
    value: Math.round(Number(system.value?.disk_percent ?? 0)),
    detail: `${system.value?.disk_used_gb ?? 0} / ${system.value?.disk_total_gb ?? 0} GB`,
    icon: 'database',
    color: 'var(--success)',
  },
])

const alerts = computed(() => (data.value?.recent_events || [])
  .filter((event: any) => ['warning', 'error', 'critical'].includes(String(event.level || '').toLowerCase()))
  .slice(0, 4))

const aiTotal = computed(() => (data.value?.ai_trend || []).reduce((total: number, item: any) => total + Number(item.calls || 0), 0))
const messageDates = computed(() => (data.value?.message_trend || []).map((item: any) => item.date?.slice(5)))
const hasMessageData = computed(() => (data.value?.message_trend || []).some((item: any) => Number(item.in || 0) > 0 || Number(item.out || 0) > 0))
const hasAiData = computed(() => (data.value?.ai_trend || []).some((item: any) => Number(item.calls || 0) > 0))

const baseChart = computed(() => {
  const palette = chartTheme.value
  return {
    grid: { left: 8, right: 12, top: 26, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: palette.tooltipBg,
      borderColor: palette.tooltipBorder,
      textStyle: { color: palette.text, fontSize: 12 },
      extraCssText: 'box-shadow:0 16px 40px rgba(0,0,0,.24);border-radius:10px;padding:10px 12px;',
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: messageDates.value,
      axisLine: { lineStyle: { color: palette.axis } },
      axisTick: { show: false },
      axisLabel: { color: palette.muted, fontSize: 10, margin: 12 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: palette.split, type: 'dashed' } },
      axisLabel: { color: palette.muted, fontSize: 10 },
    },
  }
})

const messageOption = computed(() => {
  const palette = chartTheme.value
  return {
    ...baseChart.value,
    animationDuration: 620,
    series: [
      {
        name: '收取',
        type: 'line',
        smooth: 0.35,
        showSymbol: false,
        symbol: 'circle',
        symbolSize: 7,
        data: (data.value?.message_trend || []).map((item: any) => item.in),
        lineStyle: { color: palette.cyan, width: 2 },
        itemStyle: { color: palette.cyan },
        emphasis: { focus: 'series', scale: 1.2 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: palette.cyanSoft },
              { offset: 1, color: 'transparent' },
            ],
          },
        },
      },
      {
        name: '发送',
        type: 'line',
        smooth: 0.35,
        showSymbol: false,
        symbol: 'circle',
        symbolSize: 7,
        data: (data.value?.message_trend || []).map((item: any) => item.out),
        lineStyle: { color: palette.brand, width: 2 },
        itemStyle: { color: palette.brand },
        emphasis: { focus: 'series', scale: 1.2 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: palette.brandSoft },
              { offset: 1, color: 'transparent' },
            ],
          },
        },
      },
    ],
  }
})

const aiOption = computed(() => {
  const palette = chartTheme.value
  return {
    ...baseChart.value,
    xAxis: { ...baseChart.value.xAxis, boundaryGap: true, data: (data.value?.ai_trend || []).map((item: any) => item.date?.slice(5)) },
    animationDuration: 620,
    series: [
      {
        name: '调用次数',
        type: 'bar',
        barWidth: 16,
        data: (data.value?.ai_trend || []).map((item: any) => item.calls),
        itemStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: palette.brand },
              { offset: 1, color: palette.cyan },
            ],
          },
          borderRadius: [4, 4, 0, 0],
        },
        emphasis: { itemStyle: { opacity: 0.85 } },
      },
    ],
  }
})

const CATEGORY_LABELS: Record<string, string> = {
  system: '系统',
  account: '账号',
  ai: 'AI 模型',
  github: 'GitHub',
  push: '推送',
  task: '任务',
  plugin: '插件',
  email: '邮件',
  auth: '认证',
  qqbot: 'QQ 机器人',
}

function categoryLabel(value: string) {
  return CATEGORY_LABELS[value] || value || '系统'
}

function stateLabel(state: string) {
  return ({ online: '在线', starting: '启动中', error: '异常', stopped: '离线', stopping: '停止中' } as Record<string, string>)[state] || state
}

function accountMeta(account: any) {
  const labels: Record<string, string> = { qq_official: 'QQ 官方机器人' }
  const protocol = labels[account.protocol] || account.protocol || '未知协议'
  if (account.protocol === 'qq_official') return account.app_id ? `${protocol} · AppID ${account.app_id}` : protocol
  return `QQ ${account.qq_number || '未绑定'} · ${protocol}`
}

function number(value: number | string | null | undefined) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatTime(value: string) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

let refreshing = false
async function load(silent = false) {
  if (refreshing) return
  refreshing = true
  if (!silent) loading.value = true
  if (!silent) loadError.value = ''
  try {
    const [dashboard, stats] = await Promise.all([api.get('/dashboard'), api.get('/system/stats')])
    data.value = dashboard.data
    system.value = stats.data
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch (error: any) {
    if (!silent) {
      const detail = error?.response?.data?.detail
      loadError.value = typeof detail === 'string' && detail ? detail : '请求失败，请检查后端连接后重试'
    }
  } finally {
    refreshing = false
    loading.value = false
  }
}

onMounted(() => load())
useAutoRefresh(() => load(true))
</script>

<style scoped>
.dashboard-shell {
  display: flex;
  flex-direction: column;
}
.chart-body {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
}
.chart-body .trend-chart {
  flex: 1;
  min-height: 0;
}
.chart-empty {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 190px;
  border: 1px dashed var(--line);
  border-radius: 11px;
  background: color-mix(in srgb, var(--surface-2) 52%, transparent);
  color: var(--text-3);
  text-align: center;
}
.chart-empty-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  margin-bottom: 3px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface);
  color: var(--brand-strong);
}
.chart-empty b {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}
.chart-empty p {
  max-width: 310px;
  margin: 0;
  color: var(--text-4);
  font-size: 10.5px;
  line-height: 1.6;
}
.dashboard-error {
  margin-bottom: 14px;
}
.health-grid {
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr) minmax(0, 0.9fr);
}
.resource-panel .surface-head,
.signal-panel .surface-head {
  margin-bottom: 14px;
}
.health-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--success-line);
  border-radius: 99px;
  background: var(--success-soft);
  color: var(--success);
  font-size: 9.5px;
  font-weight: 600;
}
.health-pill i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.health-pill.warn {
  color: var(--warning);
  border-color: var(--warning-line);
  background: var(--warning-soft);
}
.resource-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.resource-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 5px 12px;
  align-items: center;
}
.resource-label {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text-3);
  font-size: 11px;
}
.resource-label .app-icon {
  color: var(--text-4);
}
.resource-row > b {
  color: var(--text);
  font-size: 15px;
  font-weight: 640;
  font-variant-numeric: tabular-nums;
}
.resource-row > b small {
  margin-left: 1px;
  color: var(--text-4);
  font-size: 9px;
  font-weight: 500;
}
.resource-bar {
  grid-column: 1 / -1;
  height: 5px;
  overflow: hidden;
  border-radius: 99px;
  background: var(--surface-3);
}
.resource-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  transition: width 600ms var(--ease);
}
.resource-detail {
  grid-column: 1 / -1;
  color: var(--text-4);
  font-size: 9.5px;
}
.all-clear {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--success-line);
  border-radius: 11px;
  background: var(--success-soft);
}
.all-clear-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: none;
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface) 62%, transparent);
  color: var(--success);
}
.all-clear > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.all-clear b {
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
}
.all-clear small {
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.5;
}
.alert-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.alert-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--warning);
}
.alert-row.error,
.alert-row.critical {
  color: var(--danger);
  border-color: var(--danger-line);
  background: var(--danger-soft);
}
.alert-row > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.alert-row b {
  overflow: hidden;
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.alert-row small {
  color: var(--text-4);
  font-size: 9px;
}
.service-health {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--line-soft);
}
.service-health > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: 1;
  min-width: 100px;
}
.service-health span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-3);
  font-size: 9.5px;
}
.service-health i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--success);
}
.service-health i.bad {
  background: var(--danger);
}
.service-health i.warn {
  background: var(--warning);
}
.service-health b {
  color: var(--text-2);
  font-size: 9.5px;
  font-weight: 600;
}
.signal-state {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9px;
  font-weight: 600;
}
.signal-state.open {
  color: var(--success);
  border-color: var(--success-line);
  background: var(--success-soft);
}
.signal-state.connecting,
.signal-state.reconnecting {
  color: var(--warning);
  border-color: var(--warning-line);
  background: var(--warning-soft);
}
.signal-body {
  display: flex;
  align-items: center;
  gap: 16px;
}
.signal-orb {
  position: relative;
  display: grid;
  place-items: center;
  width: 96px;
  height: 96px;
  flex: none;
  border-radius: 50%;
  color: var(--brand-strong);
}
.signal-orb span {
  position: absolute;
  inset: 0;
  border: 1px solid var(--brand-line);
  border-radius: 50%;
  animation: orbit-spin 16s linear infinite;
}
.signal-orb span:nth-child(2) {
  inset: 12px;
  border-color: var(--cyan-line);
  animation-duration: 11s;
  animation-direction: reverse;
  border-style: dashed;
}
.signal-orb span:nth-child(3) {
  inset: 24px;
  border-color: var(--line-strong);
  animation-duration: 20s;
}
.signal-orb.open {
  background: radial-gradient(circle, var(--brand-soft), transparent 68%);
}
.signal-orb.closed,
.signal-orb.error {
  color: var(--danger);
}
.signal-orb.closed span,
.signal-orb.error span {
  border-color: var(--danger-line);
  animation-play-state: paused;
}
.signal-copy {
  min-width: 0;
}
.signal-copy > b {
  display: block;
  margin-bottom: 5px;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}
.signal-copy > p {
  margin: 0 0 10px;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.65;
}
.signal-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 12px;
}
.signal-meta span {
  color: var(--text-4);
  font-size: 9px;
}
.signal-meta b {
  color: var(--text-2);
  font-weight: 600;
}
.signal-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--line-soft);
  color: var(--text-4);
  font-size: 9px;
}
@keyframes orbit-spin {
  to { transform: rotate(360deg); }
}
@media (max-width: 1280px) {
  .health-grid {
    grid-template-columns: 1fr 1fr;
  }
  .signal-panel {
    grid-column: 1 / -1;
  }
}
@media (max-width: 760px) {
  .health-grid {
    grid-template-columns: 1fr;
  }
  .signal-panel {
    grid-column: auto;
  }
  .signal-body {
    align-items: flex-start;
  }
  .signal-orb {
    width: 72px;
    height: 72px;
  }
}
</style>
