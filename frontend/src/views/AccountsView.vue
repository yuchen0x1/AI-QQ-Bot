<template>
  <ResourceView ref="resourceRef" :config="config">
    <template #panel>
      <section class="surface account-command-center">
        <div class="account-live-bar">
          <div class="account-live-state">
            <span class="eyebrow account-live-kicker">FLEET STATUS</span>
            <div class="live-state-line">
              <i :class="`socket-led ${socketState}`"></i>
              <b>{{ liveStateLabel }}</b>
              <span>WebSocket 状态通道</span>
            </div>
          </div>

          <div class="account-live-metrics">
            <template v-if="liveMessage">
              <div class="live-metric">
                <span>运行时在线</span>
                <b>{{ liveMessage.online ?? 0 }} <small>/ {{ liveMessage.total_runtime ?? 0 }}</small></b>
              </div>
              <div v-if="liveMessage.messages_today != null" class="live-metric">
                <span>今日消息</span>
                <b>{{ number(liveMessage.messages_today) }}</b>
              </div>
            </template>
            <span v-else class="live-waiting">等待首条实时运行数据</span>
          </div>

          <el-button
            v-if="socketState === 'closed' || socketState === 'error'"
            text
            type="primary"
            @click="realtime.reconnect"
          >
            <AppIcon name="refresh" :size="14" class="account-button-icon" />重新连接
          </el-button>
        </div>

        <div class="account-protocol-note">
          <span class="account-note-icon"><AppIcon name="key" :size="15" /></span>
          <p>
            <b>官方机器人接入</b>
            使用 QQ 开放平台的 AppID / AppSecret，无需扫码登录个人 QQ。Webhook 模式还需在平台完成回调地址验证。
          </p>
        </div>

        <div v-if="accountRows.length" class="stat-grid account-stat-grid">
          <div class="stat-tile">
            <span class="stat-tile-icon brand"><AppIcon name="bot" :size="17" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">账号总数</span>
              <strong class="stat-tile-value">{{ accountSummary.total }}</strong>
              <span class="stat-tile-meta">当前已配置账号</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon green"><AppIcon name="check-circle" :size="17" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">在线运行</span>
              <strong class="stat-tile-value">{{ accountSummary.online }}</strong>
              <span class="stat-tile-meta">运行状态为在线</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon red"><AppIcon name="alert" :size="17" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">需关注</span>
              <strong class="stat-tile-value">{{ accountSummary.attention }}</strong>
              <span class="stat-tile-meta">运行或连接异常</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon cyan"><AppIcon name="users" :size="17" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">已管理群聊</span>
              <strong class="stat-tile-value">{{ number(accountSummary.groups) }}</strong>
              <span class="stat-tile-meta">各账号已建档群聊合计</span>
            </div>
          </div>
        </div>
      </section>
    </template>
  </ResourceView>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useStatusStore } from '../stores/status'
import ResourceView from '../components/ResourceView.vue'
import AppIcon from '../components/AppIcon.vue'

const resourceRef = ref<any>()
const status = useStatusStore()
const { state: socketState, payload: socketPayload } = storeToRefs(status)
const realtime = { reconnect: status.reconnect }
const liveMessage = computed(() => socketPayload.value)
const accountRows = computed<any[]>(() => resourceRef.value?.rows || [])
const accountSummary = computed(() => {
  const rows = accountRows.value
  return {
    total: rows.length,
    online: rows.filter((row) => row.runtime_state === 'online').length,
    attention: rows.filter(
      (row) => row.runtime_state === 'error' || row.connection?.status === 'error',
    ).length,
    groups: rows.reduce((total, row) => total + Number(row.group_count || 0), 0),
  }
})
const liveStateLabel = computed(() => ({
  open: '实时同步',
  connecting: '连接中',
  reconnecting: '重连中',
  closed: '连接已断开',
  error: '连接异常',
} as Record<string, string>)[socketState.value] || '等待连接')

onMounted(() => {
  status.acquire()
})
watch(liveMessage, payload => {
  if (!payload.accounts) return
  const states = new Map(payload.accounts.map(account => [account.id, account.state]))
  resourceRef.value?.patchRows?.((row: any) => states.has(row.id)
    ? { ...row, runtime_state: states.get(row.id), connection: { ...row.connection, status: states.get(row.id) === 'online' ? 'online' : states.get(row.id) === 'error' ? 'error' : 'offline' } }
    : { ...row, runtime_state: 'stopped', connection: { ...row.connection, status: 'offline' } })
})
watch(socketState, (value, previous) => {
  if (value === 'open' && previous !== 'open') void resourceRef.value?.load?.()
})

function number(value: number | string | null | undefined) {
  return Number(value || 0).toLocaleString('zh-CN')
}

const protocolOptions = [{ value: 'qq_official', label: 'QQ 官方机器人' }]
const officialModeOptions = [
  { value: 'official_ws', label: 'WebSocket（推荐，仅需出站连接）' },
  { value: 'official_webhook', label: 'Webhook（需公网 HTTPS 回调地址）' },
]
const useWebhook = (field: any) => field.connection_mode === 'official_webhook'

// QQ 官方机器人字段：AppID / AppSecret 来自 QQ 开放平台「开发设置」，不走扫码登录。
const officialFields = (editing: boolean) => [
  { key: 'app_id', label: 'AppID（BotAppID）', required: !editing, placeholder: 'QQ 开放平台 → 机器人 → 开发设置' },
  { key: 'app_secret', label: 'AppSecret', type: 'password', required: !editing, placeholder: editing ? '留空保持不变' : 'ClientSecret，仅加密存储在服务端' },
  { key: 'connection_mode', label: '回调方式', type: 'select', default: 'official_ws', options: officialModeOptions },
  { key: 'webhook_url', label: 'Webhook 回调地址（复制到开放平台）', readonly: true, showWhen: useWebhook, placeholder: '保存账号后重新打开编辑即可复制完整地址' },
  { key: 'official_sandbox', label: '沙箱环境', type: 'switch', default: false },
  { key: 'official_allow_proactive', label: '允许主动消息', type: 'switch', default: true },
  { key: 'official_intents', label: '事件 Intents 位值（仅 WebSocket）', type: 'number', default: 33554432, min: 0, max: 2147483647, showWhen: (field: any) => !useWebhook(field) },
  { key: 'official_api_base', label: 'OpenAPI 域名（可选）', placeholder: '留空使用官方默认域名' },
]
const commonFields = () => [
  { key: 'qq_number', label: 'QQ 号码（可选备注）', type: 'number', placeholder: '官方机器人无需填写' },
  { key: 'enabled', label: '启用账号', type: 'switch', default: true },
  { key: 'auto_start', label: '服务启动时自动连接', type: 'switch', default: false },
  { key: 'auto_reconnect', label: '断线自动重连', type: 'switch', default: true },
  { key: 'remark', label: '备注', placeholder: '可选' },
]

const accountColumns = [
  { key: 'name', label: '账号名称', width: 140 },
  { key: 'app_id', label: 'AppID', width: 120, mono: true },
  { key: 'qq_number', label: 'QQ 号码', width: 110, mono: true },
  { key: 'protocol', label: '协议', width: 130, options: protocolOptions },
  { key: 'connection_mode', label: '回调方式', width: 150, options: officialModeOptions },
  { key: 'runtime_state', label: '运行状态', type: 'status', width: 95, options: [{ value: 'online', label: '在线' }, { value: 'stopped', label: '离线' }, { value: 'starting', label: '启动中' }, { value: 'error', label: '异常' }, { value: 'stopping', label: '停止中' }] },
  { key: 'connection.status', label: '连接状态', type: 'status', width: 125, options: [{ value: 'online', label: '已连接' }, { value: 'error', label: '协议端未连接' }, { value: 'offline', label: '未连接' }, { value: 'connecting', label: '连接中' }] },
  { key: 'group_count', label: '管理群数', width: 90 },
  { key: 'auto_reconnect', label: '自动重连', type: 'bool', width: 90 },
]

const config = {
  kicker: 'QQ BOT FLEET',
  title: 'QQ 账号管理',
  description: '使用 QQ 开放平台官方机器人：填 AppID + AppSecret 即可接入，无需扫码登录个人 QQ 号。回调方式二选一：WebSocket（推荐，只需出站连接）或 Webhook（需公网 HTTPS 地址 /api/qqbot/webhook/{AppID}，平台会先发起地址验证）。Webhook 模式下「在线」表示本地已就绪，仍需平台验证通过才会推送事件。请订阅「群聊 @ 消息 / 单聊消息」并配置 IP 白名单。',
  endpoint: '/accounts',
  paged: false,
  keyword: null,
  itemName: '账号',
  nameKey: 'name',
  actionWidth: 310,
  cardView: true,
  cardIcon: 'bot',
  cardTitleKey: 'name',
  cardSubtitleKey: 'app_id',
  emptyText: '还没有配置 QQ 机器人账号',
  emptyHint: '填写 AppID 与 AppSecret 创建第一个官方机器人；保存后即可启动连接并同步可管理的群聊。',
  columns: accountColumns,
  cardFields: accountColumns,
  createLabel: '添加机器人',
  rawCreateLabel: '新增',
  createFields: [
    { key: 'name', label: '账号名称', required: true, placeholder: '例如：主机器人' },
    ...officialFields(false),
    ...commonFields(),
  ],
  editFields: [
    { key: 'name', label: '账号名称', required: true },
    ...officialFields(true),
    ...commonFields(),
  ],
  actions: [
    { labelFor: (row: any) => row.runtime_state === 'online' ? '停止' : '启动', suffix: 'start', method: 'POST', type: 'success', disabled: (row: any) => ['starting', 'stopping'].includes(row.runtime_state) || (!row.enabled && row.runtime_state !== 'online'), path: (row: any) => `/accounts/${row.id}/${row.runtime_state === 'online' ? 'stop' : 'start'}` },
    { label: '重启', suffix: 'restart', method: 'POST', type: 'warning', disabled: (row: any) => ['starting', 'stopping'].includes(row.runtime_state) || !row.enabled, confirm: '确定重启账号「{name}」吗？' },
    { label: '测试连接', suffix: 'test-connection', method: 'POST', type: 'info', success: (data: any) => data.message || '连接测试完成' },
  ],
  deletePath: '/accounts',
}
</script>

<style scoped>
.account-command-center {
  margin-bottom: 14px;
  padding: 16px;
}

.account-live-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  min-height: 58px;
  padding: 13px 15px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background:
    linear-gradient(105deg, color-mix(in srgb, var(--brand-soft) 72%, transparent), transparent 58%),
    var(--surface-2);
}

.account-live-state {
  min-width: 190px;
}

.account-live-kicker {
  margin: 0 0 7px;
  font-size: 9px;
}

.live-state-line {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.live-state-line b {
  color: var(--text);
  font-size: 12px;
  font-weight: 620;
}

.live-state-line > span {
  color: var(--text-4);
  font-size: 9.5px;
}

.account-live-metrics {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  min-width: 0;
}

.live-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 92px;
  padding-left: 14px;
  border-left: 1px solid var(--line);
}

.live-metric > span {
  color: var(--text-4);
  font-size: 9px;
}

.live-metric > b {
  color: var(--text);
  font-size: 14px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.live-metric b small {
  color: var(--text-4);
  font-size: 9px;
  font-weight: 500;
}

.live-waiting {
  color: var(--text-4);
  font-size: 10px;
}

.account-command-center > .account-live-bar > .el-button {
  margin-left: auto;
}

.account-button-icon {
  margin-right: 4px;
}

.account-protocol-note {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 11px;
  padding: 10px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-inset);
}

.account-note-icon {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex: none;
  border: 1px solid var(--cyan-line);
  border-radius: 7px;
  background: var(--cyan-soft);
  color: var(--cyan);
}

.account-protocol-note p {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.account-protocol-note b {
  margin-right: 5px;
  color: var(--text-2);
  font-weight: 600;
}

.account-stat-grid {
  margin: 13px 0 0;
}

.account-stat-grid .stat-tile {
  background: color-mix(in srgb, var(--surface-2) 48%, var(--surface));
  box-shadow: none;
}

@media (max-width: 760px) {
  .account-live-bar {
    align-items: flex-start;
    flex-direction: column;
    gap: 11px;
  }

  .account-live-metrics {
    width: 100%;
  }

  .live-metric:first-child {
    padding-left: 0;
    border-left: 0;
  }

  .account-command-center > .account-live-bar > .el-button {
    margin-left: 0;
  }
}

@media (max-width: 480px) {
  .account-command-center {
    padding: 13px;
  }

  .live-state-line {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .account-live-metrics {
    align-items: flex-start;
    flex-direction: column;
    gap: 9px;
  }

  .live-metric {
    width: 100%;
    padding-left: 0;
    border-left: 0;
  }
}
</style>
