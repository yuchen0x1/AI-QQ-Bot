<template>
  <div class="accounts-page">
    <ResourceView ref="resourceRef" :config="config" />
    <QrLoginDialog ref="qrRef" @completed="reload" />
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import ResourceView from '../components/ResourceView.vue'
import QrLoginDialog from '../components/QrLoginDialog.vue'
const resourceRef = ref(), qrRef = ref()
const config = {
  kicker: 'QQ BOT FLEET', title: 'QQ 账号管理', description: '扫码登录优先；已有协议端可使用高级 OneBot 接入。账号显示异常时，请先确认 NapCat / OneBot 协议端已启动且地址填写正确', endpoint: '/accounts', paged: false, keyword: null, itemName: '账号', nameKey: 'name', actionWidth: 230,
  columns: [{ key: 'name', label: '账号名称', width: 140 }, { key: 'qq_number', label: 'QQ 号码', width: 110 }, { key: 'protocol', label: '协议', width: 100, options: [{ value: 'onebot11', label: 'OneBot v11' }, { value: 'mock', label: '模拟适配器' }] }, { key: 'runtime_state', label: '运行状态', type: 'status', width: 95, options: [{ value: 'online', label: '在线' }, { value: 'stopped', label: '离线' }, { value: 'starting', label: '启动中' }, { value: 'error', label: '异常' }, { value: 'stopping', label: '停止中' }] }, { key: 'connection.status', label: '连接状态', type: 'status', width: 125, options: [{ value: 'online', label: '已连接' }, { value: 'error', label: '协议端未连接' }, { value: 'offline', label: '未连接' }, { value: 'connecting', label: '连接中' }] }, { key: 'group_count', label: '管理群数', width: 90 }, { key: 'auto_reconnect', label: '自动重连', type: 'bool', width: 90 }],
  createLabel: '扫码添加 QQ', rawCreateLabel: '高级 OneBot 接入', secondaryCreateLabel: '高级 OneBot 接入', onCreate: () => qrRef.value?.open(), createFields: [
    { key: 'name', label: '账号名称', required: true, placeholder: '例如：主机器人' },
    { key: 'protocol', label: '协议适配器', type: 'select', default: 'onebot11', required: true, options: [{ value: 'onebot11', label: 'OneBot v11' }, { value: 'mock', label: '模拟适配器（仅测试）' }] },
    { key: 'qq_number', label: 'QQ 号码', type: 'number', placeholder: '登录后可自动获取' },
    { key: 'connection_mode', label: '连接模式', type: 'select', default: 'ws_client', options: [{ value: 'ws_client', label: 'WebSocket 客户端' }, { value: 'ws_server', label: 'WebSocket 服务端' }, { value: 'http', label: 'HTTP API' }] },
    { key: 'api_base', label: 'HTTP API 地址', placeholder: 'http://127.0.0.1:3000' }, { key: 'ws_url', label: 'WebSocket 地址', placeholder: 'ws://127.0.0.1:3001' },
    { key: 'access_token', label: '访问令牌', type: 'password', placeholder: 'OneBot access token' },
    { key: 'enabled', label: '启用账号', type: 'switch', default: true }, { key: 'auto_start', label: '服务启动时自动连接', type: 'switch', default: false }, { key: 'auto_reconnect', label: '断线自动重连', type: 'switch', default: true }, { key: 'remark', label: '备注', placeholder: '可选' },
  ],
  editFields: [{ key: 'name', label: '账号名称', required: true }, { key: 'protocol', label: '协议适配器', type: 'select', options: [{ value: 'onebot11', label: 'OneBot v11' }, { value: 'mock', label: '模拟适配器' }] }, { key: 'qq_number', label: 'QQ 号码', type: 'number' }, { key: 'connection_mode', label: '连接模式', type: 'select', options: [{ value: 'ws_client', label: 'WebSocket 客户端' }, { value: 'ws_server', label: 'WebSocket 服务端' }, { value: 'http', label: 'HTTP API' }] }, { key: 'api_base', label: 'HTTP API 地址' }, { key: 'ws_url', label: 'WebSocket 地址' }, { key: 'access_token', label: '更新访问令牌', type: 'password', placeholder: '留空保持不变' }, { key: 'auto_reconnect', label: '断线自动重连', type: 'switch' }, { key: 'remark', label: '备注' }],
  actions: [
    { labelFor: (r: any) => r.runtime_state === 'online' ? '停止' : '启动', suffix: 'start', method: 'POST', type: 'success', path: (r: any) => `/accounts/${r.id}/${r.runtime_state === 'online' ? 'stop' : 'start'}` },
    { label: '重启', suffix: 'restart', method: 'POST', type: 'warning', confirm: '确定重启账号「{name}」吗？' },
    { label: '测试连接', suffix: 'test-connection', method: 'POST', type: 'info', success: (d: any) => d.message || '连接测试完成' },
  ],
  deletePath: '/accounts',
}
function reload() { resourceRef.value?.load() }
</script>
