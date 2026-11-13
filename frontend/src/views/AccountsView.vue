<template>
  <div class="accounts-page">
    <div class="account-live-bar"><span class="eyebrow">FLEET STATUS</span><span class="live-count"><i :class="`socket-led ${realtime.state.value}`"></i>{{ realtime.state.value === 'open' ? '实时同步中' : '等待连接' }}</span><span v-if="realtime.lastMessage.value">在线 {{ realtime.lastMessage.value.online ?? 0 }} / {{ realtime.lastMessage.value.total_runtime ?? 0 }}</span><span v-if="realtime.lastMessage.value?.messages_today != null">今日消息 {{ realtime.lastMessage.value.messages_today }}</span></div>
    <ResourceView ref="resourceRef" :config="config" />
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useStatusStore } from '../stores/status'
import { onMounted } from 'vue'
import ResourceView from '../components/ResourceView.vue'

const resourceRef = ref()
const status = useStatusStore()
const { state: socketState, payload: socketPayload } = storeToRefs(status)
const realtime = { state: socketState, lastMessage: socketPayload, reconnect: status.reconnect }
onMounted(() => { status.acquire() })

const protocolOptions = [{ value: 'qq_official', label: 'QQ 官方机器人' }]
const officialModeOptions = [
  { value: 'official_ws', label: 'WebSocket（推荐，仅需出站连接）' },
  { value: 'official_webhook', label: 'Webhook（需公网 HTTPS 回调地址）' },
]
const useWebhook = (f: any) => f.connection_mode === 'official_webhook'

// QQ 官方机器人字段：AppID / AppSecret 来自 QQ 开放平台「开发设置」，不走扫码登录。
const officialFields = (editing: boolean) => [
  { key: 'app_id', label: 'AppID（BotAppID）', required: !editing, placeholder: 'QQ 开放平台 → 机器人 → 开发设置' },
  { key: 'app_secret', label: 'AppSecret', type: 'password', required: !editing, placeholder: editing ? '留空保持不变' : 'ClientSecret，仅加密存储在服务端' },
  { key: 'connection_mode', label: '回调方式', type: 'select', default: 'official_ws', options: officialModeOptions },
  { key: 'webhook_url', label: 'Webhook 回调地址（复制到开放平台）', readonly: true, showWhen: useWebhook, placeholder: '保存账号后重新打开编辑即可复制完整地址' },
  { key: 'official_sandbox', label: '沙箱环境', type: 'switch', default: false },
  { key: 'official_allow_proactive', label: '允许主动消息', type: 'switch', default: true },
  { key: 'official_intents', label: '事件 Intents 位值（仅 WebSocket）', type: 'number', default: 33554432, min: 0, max: 2147483647, showWhen: (f: any) => !useWebhook(f) },
  { key: 'official_api_base', label: 'OpenAPI 域名（可选）', placeholder: '留空使用官方默认域名' },
]
const commonFields = () => [
  { key: 'qq_number', label: 'QQ 号码（可选备注）', type: 'number', placeholder: '官方机器人无需填写' },
  { key: 'enabled', label: '启用账号', type: 'switch', default: true },
  { key: 'auto_start', label: '服务启动时自动连接', type: 'switch', default: false },
  { key: 'auto_reconnect', label: '断线自动重连', type: 'switch', default: true },
  { key: 'remark', label: '备注', placeholder: '可选' },
]

const config = {
  kicker: 'QQ BOT FLEET',
  title: 'QQ 账号管理',
  description: '使用 QQ 开放平台官方机器人：填 AppID + AppSecret 即可接入，无需扫码登录个人 QQ 号。回调方式二选一：WebSocket（推荐，只需出站连接）或 Webhook（需公网 HTTPS 地址 /api/qqbot/webhook/{AppID}，平台会先发起地址验证）。Webhook 模式下「在线」表示本地已就绪，仍需平台验证通过才会推送事件。请订阅「群聊 @ 消息 / 单聊消息」并配置 IP 白名单。',
  endpoint: '/accounts', paged: false, keyword: null, itemName: '账号', nameKey: 'name', actionWidth: 310,
  columns: [
    { key: 'name', label: '账号名称', width: 140 },
    { key: 'app_id', label: 'AppID', width: 120 },
    { key: 'qq_number', label: 'QQ 号码', width: 110 },
    { key: 'protocol', label: '协议', width: 130, options: protocolOptions },
    { key: 'connection_mode', label: '回调方式', width: 150, options: officialModeOptions },
    { key: 'runtime_state', label: '运行状态', type: 'status', width: 95, options: [{ value: 'online', label: '在线' }, { value: 'stopped', label: '离线' }, { value: 'starting', label: '启动中' }, { value: 'error', label: '异常' }, { value: 'stopping', label: '停止中' }] },
    { key: 'connection.status', label: '连接状态', type: 'status', width: 125, options: [{ value: 'online', label: '已连接' }, { value: 'error', label: '协议端未连接' }, { value: 'offline', label: '未连接' }, { value: 'connecting', label: '连接中' }] },
    { key: 'group_count', label: '管理群数', width: 90 },
    { key: 'auto_reconnect', label: '自动重连', type: 'bool', width: 90 },
  ],
  createLabel: '添加机器人', rawCreateLabel: '新增',
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
    { labelFor: (r: any) => r.runtime_state === 'online' ? '停止' : '启动', suffix: 'start', method: 'POST', type: 'success', path: (r: any) => `/accounts/${r.id}/${r.runtime_state === 'online' ? 'stop' : 'start'}` },
    { label: '重启', suffix: 'restart', method: 'POST', type: 'warning', confirm: '确定重启账号「{name}」吗？' },
    { label: '测试连接', suffix: 'test-connection', method: 'POST', type: 'info', success: (d: any) => d.message || '连接测试完成' },
  ],
  deletePath: '/accounts',
}
</script>
<style scoped>
.account-live-bar {
  display: flex;
  align-items: center;
  gap: 18px;
  min-height: 38px;
  margin: -10px 0 16px;
  padding: 8px 16px;
  border: 1px solid rgba(0, 242, 254, 0.25);
  border-radius: 10px;
  background: rgba(14, 22, 38, 0.7);
  backdrop-filter: blur(12px);
  color: #9cb2d4;
  font-size: 11px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
}
.account-live-bar .eyebrow {
  margin: 0;
  color: #00f2fe;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.5px;
}
.live-count {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #00f5a0;
  font-weight: 500;
}
@media(max-width:600px){
  .account-live-bar {
    gap: 10px;
    flex-wrap: wrap;
  }
}
</style>
