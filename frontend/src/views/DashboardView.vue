<template>
  <div class="page-heading"><div><div class="eyebrow">OVERVIEW</div><h1>仪表盘</h1><p>实时掌握机器人平台运行概况</p></div><el-button :icon="Refresh" @click="load">刷新数据</el-button></div>
  <div v-loading="loading">
    <div class="metric-grid">
      <div class="metric-card" v-for="m in metrics" :key="m.label"><div class="metric-top"><span>{{ m.label }}</span><div class="metric-icon" :class="m.tone"><el-icon><component :is="m.icon" /></el-icon></div></div><div class="metric-value">{{ m.value }}</div><div class="metric-foot"><span :class="m.footClass">{{ m.foot }}</span><span>{{ m.hint }}</span></div></div>
    </div>
    <div class="dashboard-grid"><section class="surface chart-surface"><div class="surface-head"><div><h3>消息活动</h3><p>最近 7 天收发趋势</p></div><span class="legend"><i class="legend-in"></i>收取 <i class="legend-out"></i>发送</span></div><v-chart class="trend-chart" :option="messageOption" autoresize /></section>
      <section class="surface chart-surface"><div class="surface-head"><div><h3>AI 调用量</h3><p>每日模型请求统计</p></div><span class="chart-total">{{ aiTotal }} <small>次</small></span></div><v-chart class="trend-chart" :option="aiOption" autoresize /></section></div>
    <div class="dashboard-grid lower-grid"><section class="surface"><div class="surface-head"><div><h3>账号运行状态</h3><p>已配置的 QQ 机器人账号</p></div><el-button link type="primary" @click="$router.push('/accounts')">全部账号 <el-icon><ArrowRight /></el-icon></el-button></div>
        <div v-if="!data?.account_status?.length" class="empty-inline"><el-icon><Avatar /></el-icon><span>还没有配置 QQ 账号</span><el-button type="primary" plain size="small" @click="$router.push('/accounts')">添加账号</el-button></div>
        <div v-else class="account-list"><div v-for="account in data.account_status.slice(0,6)" :key="account.id" class="account-row"><div class="account-avatar"><el-icon><Avatar /></el-icon></div><div class="account-info"><b>{{ account.nickname || account.name }}</b><small>QQ {{ account.qq_number || '未登录' }} · {{ account.protocol === 'mock' ? '模拟适配器' : 'OneBot v11' }}</small></div><el-tag :type="account.state === 'online' ? 'success' : account.state === 'error' ? 'danger' : 'info'" effect="dark" round>{{ stateLabel(account.state) }}</el-tag></div></div>
      </section><section class="surface"><div class="surface-head"><div><h3>近期系统事件</h3><p>最新日志与运行通知</p></div><el-button link type="primary" @click="$router.push('/logs')">日志中心 <el-icon><ArrowRight /></el-icon></el-button></div>
        <div v-if="!data?.recent_events?.length" class="empty-inline"><el-icon><Bell /></el-icon><span>暂无近期事件</span></div><div v-else class="event-list"><div class="event-row" v-for="event in data.recent_events.slice(0,6)" :key="event.id"><div class="event-mark" :class="event.level?.toLowerCase()"></div><div class="event-content"><b>{{ event.message }}</b><small>{{ event.category }} · {{ formatTime(event.created_at) }}</small></div></div></div>
      </section></div>
    <div class="infra-strip"><span class="infra-label">服务健康</span><span class="infra-item"><i :class="system?.db_ok ? 'ok' : 'bad'"></i>PostgreSQL {{ system?.db_ok ? '正常' : '异常' }}</span><span class="infra-item"><i :class="!system?.redis_enabled || system?.redis_ok ? 'ok' : 'bad'"></i>Redis {{ !system?.redis_enabled ? '未启用' : system?.redis_ok ? '正常' : '异常' }}</span><span class="infra-item"><i :class="system?.scheduler_running ? 'ok' : 'warn'"></i>任务调度 {{ system?.scheduler_running ? '运行中' : '已暂停' }}</span><span class="infra-spacer"></span><span>推送成功率 <b>{{ data?.push_success_rate ?? 100 }}%</b></span></div>
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
import { api } from '../api'
use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])
const loading = ref(false), data = ref<any>(), system = ref<any>()
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
const baseChart = { grid: { left: 12, right: 12, top: 24, bottom: 4, containLabel: true }, tooltip: { trigger: 'axis', backgroundColor: '#151b29', borderColor: '#30394b', textStyle: { color: '#e9edf5' } }, xAxis: { type: 'category', boundaryGap: false, data: dates.value, axisLine: { lineStyle: { color: '#2c3545' } }, axisLabel: { color: '#8894a8' }, axisTick: { show: false } }, yAxis: { type: 'value', splitLine: { lineStyle: { color: '#232b39' } }, axisLabel: { color: '#8894a8' } } }
const messageOption = computed(() => ({ ...baseChart, xAxis: { ...baseChart.xAxis, data: dates.value }, series: [{ name: '收取', type: 'line', smooth: true, showSymbol: false, data: (data.value?.message_trend || []).map((x: any) => x.in), lineStyle: { color: '#37c8f0', width: 2 }, areaStyle: { color: 'rgba(55,200,240,.1)' } }, { name: '发送', type: 'line', smooth: true, showSymbol: false, data: (data.value?.message_trend || []).map((x: any) => x.out), lineStyle: { color: '#8970ff', width: 2 }, areaStyle: { color: 'rgba(137,112,255,.08)' } }] }))
const aiOption = computed(() => ({ ...baseChart, xAxis: { ...baseChart.xAxis, data: (data.value?.ai_trend || []).map((x: any) => x.date?.slice(5)) }, series: [{ name: '调用次数', type: 'bar', barWidth: 16, data: (data.value?.ai_trend || []).map((x: any) => x.calls), itemStyle: { color: '#9277ff', borderRadius: [5,5,0,0] } }] }))
function stateLabel(state: string) { return ({ online: '在线', starting: '启动中', error: '异常', stopped: '离线', stopping: '停止中' } as any)[state] || state }
function formatTime(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '' }
async function load() { loading.value = true; try { const [d, s] = await Promise.all([api.get('/dashboard'), api.get('/system/stats')]); data.value = d.data; system.value = s.data } finally { loading.value = false } }
onMounted(load)
</script>
