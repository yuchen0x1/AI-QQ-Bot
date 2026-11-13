<template>
  <div class="page-heading"><div><h1>邮件告警</h1><p>设置用于发信的邮箱，把失败任务和通知异常发送到你的收件地址。</p></div><el-button @click="$router.push('/help')">查看操作指引</el-button></div>
  <div class="mail-layout">
    <section class="surface mail-form" v-loading="loading">
      <h2>发信设置</h2><el-form label-position="top" @submit.prevent="save">
        <el-form-item label="发信通道"><el-radio-group v-model="form.provider"><el-radio-button value="agentmail">腾讯 Agent Mail</el-radio-button><el-radio-button value="smtp">SMTP 邮箱</el-radio-button></el-radio-group></el-form-item>
        <div v-if="form.provider === 'agentmail'" class="sender-box">
          <strong>{{ state.agent?.connected ? state.agent.sender : '尚未验证发信邮箱' }}</strong><p>由邮箱本人完成腾讯授权，后台使用授权选择的邮箱发信。服务器迁移后需要重新授权。</p>
          <div class="mail-actions"><el-button :loading="connecting" @click="connect">{{ state.agent?.connected ? '更换发信邮箱' : '连接发信邮箱' }}</el-button><el-button :loading="checking" @click="check">检查发信授权</el-button></div>
          <p v-if="state.authorization?.url"><a :href="state.authorization.url" target="_blank" rel="noopener noreferrer">打开腾讯授权页面</a>，完成后点击「检查发信授权」。</p>
          <p v-if="state.authorization?.state === 'starting'">正在获取腾讯授权链接…</p>
          <p v-if="state.authorization?.error || state.agent?.error" class="mail-error">{{ state.authorization?.error || state.agent?.error }}</p>
          <el-alert v-if="state.cli_installed === false" type="warning" :closable="false" title="当前主机尚未安装 Agent Mail 工具。Docker 镜像已内置；本机安装方法见操作文档。" />
        </div>
        <div v-else class="smtp-fields">
          <el-form-item label="SMTP 主机"><el-input v-model="form.smtp_host" autocomplete="off" placeholder="填写邮箱服务商提供的 SMTP 地址" /></el-form-item>
          <div class="mail-two-col"><el-form-item label="端口"><el-input-number v-model="form.smtp_port" :min="1" :max="65535" /></el-form-item><el-form-item label="连接加密"><el-select v-model="form.smtp_security"><el-option label="SSL/TLS（常用 465）" value="ssl" /><el-option label="STARTTLS（常用 587）" value="starttls" /></el-select></el-form-item></div>
          <el-form-item label="发信邮箱"><el-input v-model="form.smtp_sender" type="email" placeholder="用于 From 地址" /></el-form-item>
          <el-form-item label="SMTP 登录账号"><el-input v-model="form.smtp_username" autocomplete="off" /></el-form-item>
          <el-form-item :label="state.has_smtp_password ? 'SMTP 授权码（已保存，留空保留）' : 'SMTP 授权码或密码'"><el-input v-model="form.smtp_password" type="password" autocomplete="new-password" show-password /></el-form-item>
          <el-checkbox v-if="state.has_smtp_password" v-model="form.clear_password">清除已保存的 SMTP 授权码</el-checkbox>
        </div>
        <el-divider />
        <el-form-item label="收件邮箱"><el-input v-model="form.recipient" type="email" placeholder="希望接收失败告警的邮箱，可与发信邮箱不同" /></el-form-item>
        <el-form-item label="需要提醒的异常"><el-checkbox-group v-model="form.categories"><el-checkbox value="task">自动化任务失败</el-checkbox><el-checkbox value="push">群通知投递失败</el-checkbox><el-checkbox value="github">GitHub 同步异常</el-checkbox><el-checkbox value="account">机器人连接异常</el-checkbox><el-checkbox value="error">系统错误</el-checkbox></el-checkbox-group></el-form-item>
        <el-switch v-model="form.enabled" active-text="启用失败邮件告警" />
        <div class="mail-actions form-bottom"><el-button type="primary" :loading="saving" @click="save">保存发信设置</el-button><el-button :loading="testing" :disabled="!form.enabled || !form.recipient" @click="sendTest">保存并发送测试</el-button></div>
      </el-form>
    </section>
    <aside class="surface mail-explainer"><h3>第一次配置</h3><ol><li>选择发信通道并连接自己的发信邮箱。</li><li>填写希望接收提醒的邮箱。</li><li>选择异常类型，开启告警并保存。</li><li>发送测试邮件，在收件箱与下方记录中确认。</li></ol><p>同一错误约 3 分钟内合并提醒，发送故障最多尝试 3 次。关闭告警会取消待发送邮件。</p><p>“服务已接收”表示发信接口接受了邮件，最终投递仍取决于收件服务，请同时检查垃圾邮件。</p><router-link to="/help">阅读完整设置步骤</router-link></aside>
  </div>
  <section class="surface mail-history"><div class="surface-head"><div><h3>最近发信记录</h3><p>最多显示最近 50 条，页面自动刷新。</p></div><el-button @click="loadRecords">刷新记录</el-button></div><el-table :data="records" empty-text="还没有发信记录，保存设置后可发送一封测试邮件"><el-table-column label="时间" width="170"><template #default="s">{{ date(s.row.created_at) }}</template></el-table-column><el-table-column prop="recipient" label="收件邮箱" min-width="190" /><el-table-column prop="title" label="主题" min-width="220" /><el-table-column label="结果" width="130"><template #default="s"><el-tag :type="s.row.status === 'accepted' ? 'success' : s.row.status === 'failed' ? 'danger' : 'warning'">{{ labels[s.row.status] || s.row.status }}</el-tag></template></el-table-column><el-table-column prop="attempts" label="尝试次数" width="100" /><el-table-column prop="error" label="失败原因" min-width="250" show-overflow-tooltip /></el-table></section>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useAutoRefresh } from '../composables/useAutoRefresh'
const form = reactive<any>({ enabled: false, provider: 'agentmail', recipient: '', categories: ['task', 'push', 'github', 'account'], smtp_host: '', smtp_port: 465, smtp_security: 'ssl', smtp_username: '', smtp_sender: '', smtp_password: '', clear_password: false })
const state = ref<any>({}), records = ref<any[]>([]), loading = ref(false), saving = ref(false), testing = ref(false), connecting = ref(false), checking = ref(false)
const labels: Record<string, string> = { pending: '待发送', retrying: '等待重试', sending: '发送中', accepted: '服务已接收', failed: '发送失败', cancelled: '已取消' }
let checkedLogin = true
const date = (value: string) => value ? new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString('zh-CN') : '—'
async function loadRecords() { records.value = (await api.get('/system/email/records')).data }
async function refresh(initial = false) {
  const { data } = await api.get('/system/email'); state.value = data
  if (initial) for (const key of Object.keys(form)) if (key in data) form[key] = data[key]
  if (!checkedLogin && data.authorization?.state === 'complete') { checkedLogin = true; await check() }
  await loadRecords()
}
async function save() { saving.value = true; try { state.value = (await api.put('/system/email', form)).data; form.smtp_password = ''; form.clear_password = false; ElMessage.success('发信设置已保存'); return true } finally { saving.value = false } }
async function check() { checking.value = true; try { state.value = (await api.post('/system/email/agent/check')).data; state.value.agent?.connected ? ElMessage.success(`发信邮箱已连接：${state.value.agent.sender}`) : ElMessage.warning(state.value.agent?.error || '尚未完成发信授权') } finally { checking.value = false } }
async function connect() { connecting.value = true; try { state.value.authorization = (await api.post('/system/email/agent/connect')).data; checkedLogin = false; ElMessage.info('正在创建腾讯授权链接，请在本页打开链接完成授权') } finally { connecting.value = false } }
async function sendTest() { testing.value = true; try { await save(); const { data } = await api.post('/system/email/test'); data.ok ? ElMessage.success(data.message) : ElMessage.error(data.error || data.message); await loadRecords() } finally { testing.value = false } }
onMounted(async () => { loading.value = true; try { await refresh(true) } finally { loading.value = false } })
useAutoRefresh(() => refresh(), 5000)
</script>
<style scoped>
.mail-layout{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:24px;align-items:start}.mail-form{padding:28px;min-width:0}.mail-form h2{font-size:20px;margin:0 0 24px}.mail-form :deep(.el-form-item){margin-bottom:22px}.sender-box{padding:18px;background:#152238;border:1px solid #354964;border-radius:10px;margin-bottom:22px}.sender-box strong{color:#e7f1ff;overflow-wrap:anywhere}.sender-box p,.mail-explainer p{font-size:13px;line-height:1.8;color:#9eb2ce}.mail-actions{display:flex;gap:10px;flex-wrap:wrap}.mail-actions .el-button{margin-left:0}.form-bottom{margin-top:26px}.mail-two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}.mail-explainer{padding:24px}.mail-explainer h3{margin-top:0}.mail-explainer ol{padding-left:20px;color:#b8c9df;font-size:14px;line-height:1.9}.mail-explainer li{margin-bottom:16px}.mail-error{color:#ffaaaa!important}.mail-history{margin-top:24px;padding:24px;min-width:0}.mail-history p{font-size:13px;color:#9eb2ce}a{color:#91deeb;font-size:13px}.mail-form .el-input-number{max-width:100%}@media(max-width:1000px){.mail-layout{grid-template-columns:1fr}}@media(max-width:600px){.mail-form,.mail-history{padding:18px}.mail-two-col{grid-template-columns:1fr}.mail-form .el-radio-button{font-size:13px}}
</style>
