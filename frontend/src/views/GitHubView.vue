<template><ResourceView :config="config" /></template>
<script setup lang="ts">
import ResourceView from '../components/ResourceView.vue'
const config = {
  kicker: 'RELEASE TRACKER', title: 'GitHub 仓库监控', description: '跟踪 Release 与版本更新，支持 Webhook 实时事件和定时轮询', endpoint: '/github/repos', itemName: '仓库', nameKey: 'full_name', paged: false, actionWidth: 190,
  columns: [{ key: 'full_name', label: '仓库', width: 180 }, { key: 'description', label: '项目描述', width: 220 }, { key: 'language', label: '语言', width: 90 }, { key: 'stars', label: 'Stars', width: 80 }, { key: 'last_release_tag', label: '最新版本', width: 115 }, { key: 'last_checked_at', label: '上次检查', type: 'date', width: 160 }, { key: 'monitor_enabled', label: '监控状态', type: 'bool', width: 95 }],
  createLabel: '添加仓库', createFields: [{ key: 'url', label: 'GitHub 仓库地址', placeholder: 'https://github.com/owner/repo' }, { key: 'owner', label: '用户名 / Owner', placeholder: '与仓库名一起填写' }, { key: 'name', label: '仓库名', placeholder: '与用户名一起填写' }, { key: 'token', label: 'GitHub Token（可选）', type: 'password', placeholder: '访问私有仓库或提高限额' }, { key: 'webhook_secret', label: 'Webhook Secret（可选）', type: 'password' }, { key: 'poll_interval_seconds', label: '轮询间隔（秒）', type: 'number', default: 900, min: 60 }, { key: 'monitor_enabled', label: '启用监控', type: 'switch', default: true }, { key: 'notify_prerelease', label: '接收预发布版本', type: 'switch', default: false }],
  editFields: [{ key: 'token', label: 'GitHub Token', type: 'password', placeholder: '留空保持不变' }, { key: 'webhook_secret', label: 'Webhook Secret', type: 'password', placeholder: '留空保持不变' }, { key: 'poll_interval_seconds', label: '轮询间隔（秒）', type: 'number', min: 60 }, { key: 'monitor_enabled', label: '启用监控', type: 'switch' }, { key: 'notify_prerelease', label: '接收预发布版本', type: 'switch' }],
  actions: [{ label: '检查更新', suffix: 'check', method: 'POST', success: (d: any) => d.message || '检查完成' }, { label: 'Release', type: 'info', handler: (r: any) => window.open(`https://github.com/${r.full_name}/releases`, '_blank', 'noopener') }], deletePath: '/github/repos',
  secondaryAction: { label: '检查全部', path: '/github/repos/check-all', method: 'POST', success: (d: any) => `检查完成，共处理 ${Array.isArray(d) ? d.length : 0} 个仓库` },
}
</script>
