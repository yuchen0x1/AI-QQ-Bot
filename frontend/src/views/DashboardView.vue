<template>
  <div class="page-heading"><div><div class="eyebrow">OVERVIEW <span class="realtime-badge"><i :class="`socket-led ${realtime.state.value}`"></i>{{ realtime.state.value === 'open' ? 'LIVE' : realtime.state.value.toUpperCase() }}</span></div><h1>仪表盘</h1><p>实时掌握机器人平台运行概况 · {{ realtime.lastMessage.value?.time ? formatTime(realtime.lastMessage.value.time as string) : '等待状态同步' }}</p></div><div class="heading-actions"><el-button v-if="realtime.state.value !== 'open'" text type="primary" @click="realtime.reconnect">重新连接</el-button><el-button :icon="Refresh" @click="load">刷新数据</el-button></div></div>
  <div v-loading="loading">
    <div class="metric-grid">
      <div class="metric-card" v-for="m in metrics" :key="m.label"><div class="metric-top"><span>{{ m.label }}</span><div class="metric-icon" :class="m.tone"><el-icon><component :is="m.icon" /></el-icon></div></div><div class="metric-value">{{ m.value }}</div><div class="metric-foot"><span :class="m.footClass">{{ m.foot }}</span><span>{{ m.hint }}</span></div></div>
    </div>
    <div class="dashboard-grid"><section class="surface chart-surface"><div class="surface-head"><div><h3>消息活动</h3><p>最近 7 天收发趋势</p></div><span class="legend"><i class="legend-in"></i>收取 <i class="legend-out"></i>发送</span></div><v-chart class="trend-chart" :option="messageOption" autoresize /></section>
      <section class="surface chart-surface"><div class="surface-head"><div><h3>AI 调用量</h3><p>每日模型请求统计</p></div><span class="chart-total">{{ aiTotal }} <small>次</small></span></div><v-chart class="trend-chart" :option="aiOption" autoresize /></section></div>
    <div class="dashboard-grid lower-grid"><section class="surface"><div class="surface-head"><div><h3>账号运行状态</h3><p>已配置的 QQ 机器人账号</p></div><el-button link type="primary" @click="$router.push('/accounts')">全部账号 <el-icon><ArrowRight /></el-icon></el-button></div>
        <div v-if="!data?.account_status?.length" class="empty-inline"><el-icon><Avatar /></el-icon><span>还没有配置 QQ 账号</span><el-button type="primary" plain size="small" @click="$router.push('/accounts')">添加账号</el-button></div>
        <div v-else class="account-list"><div v-for="account in data.account_status.slice(0,6)" :key="account.id" class="account-row"><div class="account-avatar"><el-icon><Avatar /></el-icon></div><div class="account-info"><b>{{ account.nickname || account.name }}</b><small>{{ accountMeta(account) }}</small></div><el-tag :type="account.state === 'online' ? 'success' : account.state === 'error' ? 'danger' : 'info'" effect="dark" round>{{ stateLabel(account.state) }}</el-tag></div></div>
      </section><section class="surface"><div class="surface-head"><div><h3>近期系统事件</h3><p>最新日志与运行通知</p></div><el-button link type="primary" @click="$router.push('/logs')">日志中心 <el-icon><ArrowRight /></el-icon></el-button></div>
        <div v-if="!data?.recent_events?.length" class="empty-inline"><el-icon><Bell /></el-icon><span>暂无近期事件</span></div><div v-else class="event-list"><div class="event-row" v-for="event in data.recent_events.slice(0,6)" :key="event.id"><div class="event-mark" :class="event.level?.toLowerCase()"></div><div class="event-content"><b>{{ event.message }}</b><small>{{ event.category }} · {{ formatTime(event.created_at) }}</small></div></div></div>
      </section></div>
    <div class="infra-strip"><span class="infra-label">服务健康</span><span class="infra-item"><i :class="system?.db_ok ? 'ok' : 'bad'"></i>PostgreSQL {{ system?.db_ok ? '正常' : '异常' }}</span><span v-if="realtime.lastMessage.value" class="infra-item"><i class="ok"></i>实时状态 {{ realtime.lastMessage.value.online ?? 0 }}/{{ realtime.lastMessage.value.total_runtime ?? 0 }} 在线</span><span class="infra-item"><i :class="!system?.redis_enabled || system?.redis_ok ? 'ok' : 'bad'"></i>Redis {{ !system?.redis_enabled ? '未启用' : system?.redis_ok ? '正常' : '异常' }}</span><span class="infra-item"><i :class="system?.scheduler_running ? 'ok' : 'warn'"></i>任务调度 {{ system?.scheduler_running ? '运行中' : '已暂停' }}</span><span class="infra-spacer"></span><span>推送成功率 <b>{{ data?.push_success_rate ?? 100 }}%</b></span></div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { ArrowRight, Avatar, Bell, Refresh } from '@element-plus/icons-vue'
import { api, useRealtimeSocket } from '../api'
use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])
const loading = ref(false), data = ref<any>(), system = ref<any>()
const realtime = useRealtimeSocket<any>('/ws/status')
const metrics = computed(() => [
  { label: 'QQ 账号', value: data.value?.accounts_total ?? 0, foot: `${data.value?.accounts_online ?? 0} 个在线`, hint: `${data.value?.accounts_offline ?? 0} 个离线`, icon: 'Avatar', tone: 'blue', footClass: 'accent' },
  { label: '今日消息', value: data.value?.messages_today ?? 0, foot: `↑ ${data.value?.messages_sent_today ?? 0} 条发送`, hint: '收发合计', icon: 'ChatLineSquare', tone: 'cyan', footClass: 'green-text' },
  { label: 'AI 模型调用', value: data.value?.ai_calls_today ?? 0, foot: '今日请求', hint: '多模型中心', icon: 'Cpu', tone: 'purple', footClass: 'accent' },
  { label: 'GitHub 仓库', value: data.value?.repos_total ?? 0, foot: `${data.value?.releases_today ?? 0} 个今日版本`, hint: '监控中', icon: 'Connection', tone: 'orange', footClass: 'orange-text' },
  { label: '今日推送', value: data.value?.pushes_today ?? 0, foot: `成功率 ${data.value?.push_success_rate ?? 100}%`, hint: `${data.value?.failed_tasks ?? 0} 个失败任务`, icon: 'Promotion', tone: 'green', footClass: 'green-text' },
  { label: '群聊数量', value: data.value?.groups_total ?? 0, foot: '已同步群聊', hint: '独立配置', icon: 'ChatDotRound', tone: 'pink', footClass: 'accent' },
])
const aiTotal = computed(() => (data.value?.ai_trend || []).reduce((a: number, x: any) => a + x.calls, 0))
const dates = computed(() => (data.value?.message_trend || []).map((x: any) => x.date?.slice(5)))
const baseChart = {
  grid: { left: 16, right: 16, top: 28, bottom: 8, containLabel: true },
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(10, 15, 26, 0.92)',
    borderColor: 'rgba(56, 75, 110, 0.6)',
    textStyle: { color: '#f0f4fc', fontSize: 12 },
    boxShadow: '0 8px 30px rgba(0, 0, 0, 0.6)',
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: dates.value,
    axisLine: { lineStyle: { color: 'rgba(56, 75, 110, 0.4)' } },
    axisLabel: { color: '#889bb8', fontSize: 11 },
    axisTick: { show: false },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(56, 75, 110, 0.2)', type: 'dashed' } },
    axisLabel: { color: '#889bb8', fontSize: 11 },
  },
}
const messageOption = computed(() => ({
  ...baseChart,
  xAxis: { ...baseChart.xAxis, data: dates.value },
  series: [
    {
      name: '收取',
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: (data.value?.message_trend || []).map((x: any) => x.in),
      lineStyle: { color: '#00f2fe', width: 2.5, shadowColor: 'rgba(0, 242, 254, 0.5)', shadowBlur: 10 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(0, 242, 254, 0.35)' },
            { offset: 1, color: 'rgba(0, 242, 254, 0.0)' },
          ],
        },
      },
    },
    {
      name: '发送',
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: (data.value?.message_trend || []).map((x: any) => x.out),
      lineStyle: { color: '#8b76ff', width: 2.5, shadowColor: 'rgba(139, 118, 255, 0.5)', shadowBlur: 10 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(139, 118, 255, 0.3)' },
            { offset: 1, color: 'rgba(139, 118, 255, 0.0)' },
          ],
        },
      },
    },
  ],
}))
const aiOption = computed(() => ({
  ...baseChart,
  xAxis: { ...baseChart.xAxis, data: (data.value?.ai_trend || []).map((x: any) => x.date?.slice(5)) },
  series: [
    {
      name: '调用次数',
      type: 'bar',
      barWidth: 18,
      data: (data.value?.ai_trend || []).map((x: any) => x.calls),
      itemStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: '#00f5a0' },
            { offset: 1, color: 'rgba(139, 118, 255, 0.6)' },
          ],
        },
        borderRadius: [6, 6, 0, 0],
        shadowColor: 'rgba(0, 245, 160, 0.3)',
        shadowBlur: 8,
      },
    },
  ],
}))
function stateLabel(state: string) { return ({ online: '在线', starting: '启动中', error: '异常', stopped: '离线', stopping: '停止中' } as any)[state] || state }
// 官方机器人没有 QQ 号，只有平台 AppID，不能沿用 OneBot 的「QQ 未登录」文案。
function accountMeta(account: any) {
  const labels: Record<string, string> = { mock: '模拟适配器', qq_official: 'QQ 官方机器人', onebot11: 'OneBot v11' }
  const protocol = labels[account.protocol] || account.protocol || '未知协议'
  if (account.protocol === 'qq_official') {
    return account.app_id ? `${protocol} · AppID ${account.app_id}` : protocol
  }
  return `QQ ${account.qq_number || '未绑定'} · ${protocol}`
}
function formatTime(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '' }
async function load() { loading.value = true; try { const [d, s] = await Promise.all([api.get('/dashboard'), api.get('/system/stats')]); data.value = d.data; system.value = s.data } finally { loading.value = false } }
onMounted(load)
</script>
