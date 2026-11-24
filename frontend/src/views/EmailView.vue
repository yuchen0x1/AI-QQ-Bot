<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">ALERT DELIVERY</div>
      <h1>邮件告警</h1>
      <p>设置用于发信的邮箱，把失败任务和通知异常发送到你的收件地址。</p>
    </div>
    <div class="heading-actions">
      <el-button @click="$router.push('/help')">
        <AppIcon name="book" :size="14" class="button-icon" />查看操作指引
      </el-button>
    </div>
  </div>

  <div class="mail-layout">
    <section v-loading="loading" class="surface mail-form" aria-labelledby="mail-form-title">
      <div class="section-heading">
        <span class="section-icon"><AppIcon name="mail" :size="17" /></span>
        <div>
          <h2 id="mail-form-title">发信设置</h2>
          <p>发信通道决定邮件由谁投递，收件地址与提醒类型可以单独调整。</p>
        </div>
        <span class="state-badge" :class="activeProviderBadge.tone" role="status">
          <AppIcon :name="activeProviderBadge.icon" :size="12" />
          <span>{{ activeProviderBadge.label }}</span>
        </span>
      </div>

      <el-form label-position="top" @submit.prevent="save">
        <div class="form-section channel-section">
          <div class="form-section-heading">
            <div>
              <h3>发信通道</h3>
              <p>选择腾讯 Agent Mail 授权发信，或使用现有邮箱的 SMTP 服务。</p>
            </div>
          </div>

          <el-form-item label="发信方式">
            <el-radio-group v-model="form.provider" class="provider-switch">
              <el-radio-button value="agentmail">
                <span class="provider-option">
                  <AppIcon name="sparkles" :size="17" />
                  <span><b>腾讯 Agent Mail</b><small>邮箱本人授权，无需保存密码</small></span>
                </span>
              </el-radio-button>
              <el-radio-button value="smtp">
                <span class="provider-option">
                  <AppIcon name="server" :size="17" />
                  <span><b>SMTP 邮箱</b><small>使用服务商主机与授权码</small></span>
                </span>
              </el-radio-button>
            </el-radio-group>
          </el-form-item>

          <div v-if="form.provider === 'agentmail'" class="channel-panel">
            <div class="sender-row">
              <span class="sender-icon"><AppIcon name="send" :size="17" /></span>
              <div class="sender-copy">
                <span>当前发信身份</span>
                <strong>{{ agentDisplaySender }}</strong>
              </div>
            </div>
            <p class="helper-copy">由邮箱本人完成腾讯授权，后台使用授权选择的邮箱发信。服务器迁移后需要重新授权。</p>
            <div class="mail-actions">
              <el-button :loading="connecting" @click="connect">
                <AppIcon name="mail" :size="14" class="button-icon" />{{ state.agent?.connected ? '更换发信邮箱' : '连接发信邮箱' }}
              </el-button>
              <el-button :loading="checking" @click="check">
                <AppIcon name="check-circle" :size="14" class="button-icon" />检查发信授权
              </el-button>
            </div>
            <p v-if="state.authorization?.url" class="authorization-line">
              <AppIcon name="external" :size="13" />
              <a :href="state.authorization.url" target="_blank" rel="noopener noreferrer">打开腾讯授权页面</a>
              <span>，完成后点击「检查发信授权」。</span>
            </p>
            <p v-if="state.authorization?.state === 'starting'" class="authorization-line">
              <AppIcon name="loader" :size="13" class="spin-icon" />正在获取腾讯授权链接…
            </p>
            <p v-if="state.authorization?.error || state.agent?.error" class="mail-error" role="alert">
              <AppIcon name="alert" :size="13" />{{ state.authorization?.error || state.agent?.error }}
            </p>
            <el-alert
              v-if="state.cli_installed === false"
              type="warning"
              :closable="false"
              show-icon
              title="当前主机尚未安装 Agent Mail 工具。Docker 镜像已内置；本机安装方法见操作文档。"
            />
          </div>

          <div v-else class="channel-panel smtp-panel">
            <div class="smtp-heading">
              <div>
                <strong>SMTP 服务器</strong>
                <p>端口与加密方式需要和邮箱服务商的要求一致。</p>
              </div>
              <span class="state-badge" :class="smtpBadge.tone">
                <AppIcon :name="smtpBadge.icon" :size="12" />
                <span>{{ smtpBadge.label }}</span>
              </span>
            </div>
            <el-form-item label="SMTP 主机">
              <el-input v-model="form.smtp_host" autocomplete="off" placeholder="填写邮箱服务商提供的 SMTP 地址" />
            </el-form-item>
            <div class="mail-two-col">
              <el-form-item label="端口">
                <el-input-number v-model="form.smtp_port" :min="1" :max="65535" />
              </el-form-item>
              <el-form-item label="连接加密">
                <el-select v-model="form.smtp_security">
                  <el-option label="SSL/TLS（常用 465）" value="ssl" />
                  <el-option label="STARTTLS（常用 587）" value="starttls" />
                </el-select>
              </el-form-item>
            </div>
            <el-form-item label="发信邮箱">
              <el-input v-model="form.smtp_sender" type="email" placeholder="用于 From 地址" />
            </el-form-item>
            <el-form-item label="SMTP 登录账号">
              <el-input v-model="form.smtp_username" autocomplete="off" />
            </el-form-item>
            <el-form-item :label="state.has_smtp_password ? 'SMTP 授权码（已保存，留空保留）' : 'SMTP 授权码或密码'">
              <el-input
                v-model="form.smtp_password"
                type="password"
                autocomplete="new-password"
                show-password
                placeholder="请填写服务商提供的 SMTP 授权码"
              />
            </el-form-item>
            <el-checkbox v-if="state.has_smtp_password" v-model="form.clear_password" class="clear-password">
              清除已保存的 SMTP 授权码
            </el-checkbox>
          </div>
        </div>

        <div class="form-section">
          <div class="form-section-heading">
            <div>
              <h3>收件与提醒范围</h3>
              <p>收件邮箱可以和发信邮箱不同；只勾选你真正需要收到的异常。</p>
            </div>
          </div>
          <el-form-item label="收件邮箱">
            <el-input
              v-model="form.recipient"
              type="email"
              placeholder="希望接收失败告警的邮箱，可与发信邮箱不同"
            />
          </el-form-item>
          <el-form-item label="需要提醒的异常">
            <el-checkbox-group v-model="form.categories" class="category-grid">
              <el-checkbox value="task">自动化任务失败</el-checkbox>
              <el-checkbox value="push">群通知投递失败</el-checkbox>
              <el-checkbox value="github">GitHub 同步异常</el-checkbox>
              <el-checkbox value="account">机器人连接异常</el-checkbox>
              <el-checkbox value="error">系统错误</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <div class="enable-row">
            <div>
              <b>启用失败邮件告警</b>
              <p>关闭后会取消仍在等待发送的邮件，不会删除历史发信记录。</p>
            </div>
            <el-switch v-model="form.enabled" aria-label="启用失败邮件告警" />
          </div>
        </div>

        <div class="mail-actions form-bottom">
          <el-button type="primary" :loading="saving" @click="save">
            <AppIcon name="check" :size="14" class="button-icon" />保存发信设置
          </el-button>
          <el-button :loading="testing" :disabled="!form.enabled || !form.recipient" @click="sendTest">
            <AppIcon name="send" :size="14" class="button-icon" />保存并发送测试
          </el-button>
        </div>
      </el-form>
    </section>

    <aside class="surface mail-explainer" aria-labelledby="mail-guide-title">
      <div class="explainer-heading">
        <span class="section-icon cyan"><AppIcon name="book" :size="17" /></span>
        <div>
          <h2 id="mail-guide-title">第一次配置</h2>
          <p>按顺序完成，再用测试邮件确认整条链路。</p>
        </div>
      </div>

      <div class="status-summary">
        <div class="summary-row">
          <span>当前通道</span>
          <b>{{ form.provider === 'agentmail' ? '腾讯 Agent Mail' : 'SMTP 邮箱' }}</b>
        </div>
        <div class="summary-row">
          <span>发信身份</span>
          <b>{{ senderSummary }}</b>
        </div>
        <div class="summary-row">
          <span>收件地址</span>
          <b>{{ form.recipient || '未填写' }}</b>
        </div>
        <div class="summary-row">
          <span>已保存状态</span>
          <b :class="state.enabled ? 'summary-ok' : 'summary-muted'">{{ state.enabled ? '已启用' : '未启用' }}</b>
        </div>
      </div>

      <ol class="setup-list">
        <li><span class="setup-number">1</span><span>选择发信通道并连接自己的发信邮箱。</span></li>
        <li><span class="setup-number">2</span><span>填写希望接收提醒的邮箱。</span></li>
        <li><span class="setup-number">3</span><span>选择异常类型，开启告警并保存。</span></li>
        <li><span class="setup-number">4</span><span>发送测试邮件，在收件箱与下方记录中确认。</span></li>
      </ol>

      <div class="explainer-note">
        <AppIcon name="timer" :size="15" />
        <p>同一错误约 3 分钟内合并提醒，发送故障最多尝试 3 次。关闭告警会取消待发送邮件。</p>
      </div>
      <div class="explainer-note">
        <AppIcon name="info" :size="15" />
        <p>“服务已接收”表示发信接口接受了邮件，最终投递仍取决于收件服务，请同时检查垃圾邮件。</p>
      </div>

      <router-link class="help-link" to="/help">
        阅读完整设置步骤<AppIcon name="arrow-right" :size="14" />
      </router-link>
    </aside>
  </div>

  <section class="surface mail-history" aria-labelledby="mail-history-title">
    <div class="surface-head">
      <div class="history-heading">
        <span class="section-icon cyan"><AppIcon name="history" :size="17" /></span>
        <div>
          <h2 id="mail-history-title">最近发信记录</h2>
          <p>最多显示最近 50 条，页面每 5 秒自动刷新。</p>
        </div>
      </div>
      <el-button @click="loadRecords">
        <AppIcon name="refresh" :size="14" class="button-icon" />刷新记录
      </el-button>
    </div>

    <el-table :data="records" class="mail-table">
      <el-table-column label="时间" width="175">
        <template #default="scope">
          <div class="time-cell">
            <b>{{ day(scope.row.created_at) }}</b>
            <span>{{ time(scope.row.created_at) }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="recipient" label="收件邮箱" min-width="190" show-overflow-tooltip />
      <el-table-column prop="title" label="主题" min-width="220" show-overflow-tooltip />
      <el-table-column label="结果" width="138">
        <template #default="scope">
          <span class="result-badge" :class="recordBadge(scope.row.status).tone">
            <AppIcon :name="recordBadge(scope.row.status).icon" :size="12" />
            <span>{{ recordBadge(scope.row.status).label }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="尝试次数" width="100">
        <template #default="scope"><span class="attempt-count">{{ scope.row.attempts ?? 0 }}<small>次</small></span></template>
      </el-table-column>
      <el-table-column label="失败原因" min-width="250" show-overflow-tooltip>
        <template #default="scope">
          <span :class="{ 'failure-copy': scope.row.error }">{{ scope.row.error || '—' }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <div class="record-empty">
          <span class="empty-icon"><AppIcon name="inbox" :size="24" /></span>
          <div>
            <b>还没有发信记录</b>
            <p>保存发信设置并启用告警后，发送一封测试邮件即可在这里核对投递结果。</p>
          </div>
          <el-button
            :disabled="!form.enabled || !form.recipient"
            :loading="testing"
            @click="sendTest"
          >
            发送测试邮件
          </el-button>
        </div>
      </template>
    </el-table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import { useAutoRefresh } from '../composables/useAutoRefresh'

type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const form = reactive<any>({
  enabled: false,
  provider: 'agentmail',
  recipient: '',
  categories: ['task', 'push', 'github', 'account'],
  smtp_host: '',
  smtp_port: 465,
  smtp_security: 'ssl',
  smtp_username: '',
  smtp_sender: '',
  smtp_password: '',
  clear_password: false,
})
const state = ref<any>({}), records = ref<any[]>([]), loading = ref(false), saving = ref(false)
const testing = ref(false), connecting = ref(false), checking = ref(false)
const labels: Record<string, string> = {
  pending: '待发送',
  retrying: '等待重试',
  sending: '发送中',
  accepted: '服务已接收',
  failed: '发送失败',
  cancelled: '已取消',
}
let checkedLogin = true

const agentBadge = computed<{ label: string; tone: BadgeTone; icon: string }>(() => {
  if (state.value.cli_installed === false) return { label: 'CLI 未安装', tone: 'warning', icon: 'alert' }
  if (state.value.agent?.connected) return { label: '已连接', tone: 'success', icon: 'check-circle' }
  if (state.value.authorization?.state === 'starting') return { label: '等待授权', tone: 'info', icon: 'clock' }
  if (state.value.authorization?.error || state.value.agent?.error) return { label: '需要检查', tone: 'danger', icon: 'alert' }
  return { label: '未连接', tone: 'neutral', icon: 'info' }
})

const smtpBadge = computed<{ label: string; tone: BadgeTone; icon: string }>(() => {
  if (state.value.has_smtp_password) return { label: '凭据已保存', tone: 'success', icon: 'check-circle' }
  if (state.value.smtp_host) return { label: '待补全授权码', tone: 'warning', icon: 'key' }
  return { label: '待配置', tone: 'neutral', icon: 'settings' }
})

const activeProviderBadge = computed(() => form.provider === 'agentmail' ? agentBadge.value : smtpBadge.value)
const agentDisplaySender = computed(() => state.value.agent?.connected
  ? (state.value.agent.sender || '已连接，发信地址待同步')
  : '尚未验证发信邮箱')
const senderSummary = computed(() => {
  if (form.provider === 'agentmail') {
    return state.value.agent?.connected ? (state.value.agent.sender || '已连接') : '未连接'
  }
  return state.value.smtp_sender || form.smtp_sender || '未填写'
})

function recordBadge(status: string): { label: string; tone: BadgeTone; icon: string } {
  if (status === 'accepted') return { label: labels[status] || status, tone: 'success', icon: 'check-circle' }
  if (status === 'failed') return { label: labels[status] || status, tone: 'danger', icon: 'alert' }
  if (status === 'sending') return { label: labels[status] || status, tone: 'info', icon: 'loader' }
  if (status === 'cancelled') return { label: labels[status] || status, tone: 'neutral', icon: 'close' }
  return { label: labels[status] || status, tone: 'warning', icon: 'clock' }
}

function normalizedDate(value: string) {
  return value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`
}
const day = (value: string) => value ? new Date(normalizedDate(value)).toLocaleDateString('zh-CN') : '—'
const time = (value: string) => value ? new Date(normalizedDate(value)).toLocaleTimeString('zh-CN') : '—'

async function loadRecords() { records.value = (await api.get('/system/email/records')).data }
async function refresh(initial = false) {
  const { data } = await api.get('/system/email')
  state.value = data
  if (initial) for (const key of Object.keys(form)) if (key in data) form[key] = data[key]
  if (!checkedLogin && data.authorization?.state === 'complete') {
    checkedLogin = true
    await check()
  }
  await loadRecords()
}
async function save() {
  saving.value = true
  try {
    state.value = (await api.put('/system/email', form)).data
    form.smtp_password = ''
    form.clear_password = false
    ElMessage.success('发信设置已保存')
    return true
  } finally {
    saving.value = false
  }
}
async function check() {
  checking.value = true
  try {
    state.value = (await api.post('/system/email/agent/check')).data
    state.value.agent?.connected
      ? ElMessage.success(`发信邮箱已连接：${state.value.agent.sender}`)
      : ElMessage.warning(state.value.agent?.error || '尚未完成发信授权')
  } finally {
    checking.value = false
  }
}
async function connect() {
  connecting.value = true
  try {
    state.value.authorization = (await api.post('/system/email/agent/connect')).data
    checkedLogin = false
    ElMessage.info('正在创建腾讯授权链接，请在本页打开链接完成授权')
  } finally {
    connecting.value = false
  }
}
async function sendTest() {
  testing.value = true
  try {
    await save()
    const { data } = await api.post('/system/email/test')
    data.ok ? ElMessage.success(data.message) : ElMessage.error(data.error || data.message)
    await loadRecords()
  } finally {
    testing.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await refresh(true)
  } finally {
    loading.value = false
  }
})
useAutoRefresh(() => refresh(), 5000)
</script>

<style scoped>
.mail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 320px);
  gap: 18px;
  align-items: start;
}

.mail-form {
  min-width: 0;
  padding: 22px;
}

.section-heading,
.explainer-heading,
.history-heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  min-width: 0;
}

.section-heading {
  margin-bottom: 20px;
}

.section-heading > div,
.explainer-heading > div,
.history-heading > div {
  flex: 1;
  min-width: 0;
}

.section-heading h2,
.explainer-heading h2,
.history-heading h2 {
  margin: 0 0 4px;
  color: var(--text);
  font-size: 15px;
  font-weight: 640;
  letter-spacing: -0.015em;
}

.section-heading p,
.explainer-heading p,
.history-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.section-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.section-icon.cyan {
  border-color: var(--cyan-line);
  background: var(--cyan-soft);
  color: var(--cyan);
}

.form-section {
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.form-section + .form-section {
  margin-top: 20px;
}

.form-section-heading {
  margin-bottom: 14px;
}

.form-section-heading h3 {
  margin: 0 0 4px;
  color: var(--text);
  font-size: 12px;
  font-weight: 620;
}

.form-section-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.6;
}

.mail-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.mail-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 560;
}

.mail-form :deep(.el-select),
.mail-form :deep(.el-input-number) {
  width: 100%;
}

.provider-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.provider-switch :deep(.el-radio-button) {
  display: block;
  min-width: 0;
}

.provider-switch :deep(.el-radio-button__inner) {
  width: 100%;
  min-height: 65px;
  margin-left: 0;
  padding: 11px 13px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  color: var(--text-2);
  box-shadow: none;
  text-align: left;
}

.provider-switch :deep(.el-radio-button.is-active .el-radio-button__inner),
.provider-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  border-color: var(--brand-line);
  background: color-mix(in srgb, var(--brand-soft) 76%, var(--surface));
  color: var(--text);
  box-shadow: inset 0 0 0 1px var(--brand-line);
}

.provider-option {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.provider-option > .app-icon {
  color: var(--brand-strong);
}

.provider-option > span {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.provider-option b {
  color: inherit;
  font-size: 11px;
  font-weight: 600;
}

.provider-option small {
  color: var(--text-3);
  font-size: 9px;
  line-height: 1.45;
}

.channel-panel {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
}

.sender-row {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.sender-icon,
.empty-icon {
  display: grid;
  place-items: center;
  flex: none;
  border: 1px solid var(--cyan-line);
  border-radius: 9px;
  background: var(--cyan-soft);
  color: var(--cyan);
}

.sender-icon {
  width: 34px;
  height: 34px;
}

.sender-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.sender-copy span {
  color: var(--text-4);
  font-size: 9px;
}

.sender-copy strong {
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 12px;
  font-weight: 580;
}

.helper-copy {
  margin: 12px 0 14px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.75;
}

.mail-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mail-actions :deep(.el-button) {
  margin-left: 0;
}

.button-icon {
  margin-right: 5px;
}

.authorization-line,
.mail-error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 12px 0 0;
  font-size: 10.5px;
  line-height: 1.65;
}

.authorization-line {
  color: var(--text-3);
}

.authorization-line .app-icon,
.mail-error .app-icon {
  margin-top: 2px;
}

.authorization-line a,
.help-link {
  color: var(--brand-strong);
  text-decoration: none;
}

.authorization-line a:hover,
.help-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.mail-error {
  color: var(--danger);
  font-weight: 550;
}

.channel-panel :deep(.el-alert) {
  margin-top: 13px;
}

.smtp-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.smtp-heading strong {
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
}

.smtp-heading p {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.6;
}

.smtp-panel :deep(.el-form-item:last-of-type) {
  margin-bottom: 10px;
}

.mail-two-col {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}

.clear-password {
  margin-top: -2px;
}

.state-badge,
.result-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  min-height: 22px;
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}

.state-badge.success,
.result-badge.success {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.state-badge.warning,
.result-badge.warning {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}

.state-badge.danger,
.result-badge.danger {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}

.state-badge.info,
.result-badge.info {
  border-color: var(--info-line);
  background: var(--info-soft);
  color: var(--info);
}

.state-badge.neutral,
.result-badge.neutral {
  color: var(--text-3);
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.category-grid :deep(.el-checkbox) {
  min-width: 0;
  min-height: 40px;
  margin: 0;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-2);
  color: var(--text-2);
}

.category-grid :deep(.el-checkbox:hover) {
  border-color: var(--line-strong);
  background: var(--surface-hover);
}

.category-grid :deep(.el-checkbox.is-checked) {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--text);
}

.category-grid :deep(.el-checkbox__label) {
  padding-left: 7px;
  font-size: 10.5px;
  line-height: 1.45;
  white-space: normal;
}

.enable-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
}

.enable-row > div {
  min-width: 0;
}

.enable-row b {
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
}

.enable-row p {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.6;
}

.enable-row :deep(.el-switch) {
  flex: none;
}

.form-bottom {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.mail-explainer {
  position: sticky;
  top: calc(var(--topbar-height) + 18px);
  min-width: 0;
  padding: 20px;
}

.explainer-heading {
  margin-bottom: 15px;
}

.status-summary {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
}

.summary-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 9px 11px;
  border-bottom: 1px solid var(--line-soft);
  font-size: 9.5px;
}

.summary-row:last-child {
  border-bottom: 0;
}

.summary-row > span {
  color: var(--text-3);
}

.summary-row b {
  max-width: 68%;
  overflow-wrap: anywhere;
  color: var(--text-2);
  font-weight: 560;
  text-align: right;
}

.summary-row b.summary-ok {
  color: var(--success);
}

.summary-row b.summary-muted {
  color: var(--text-4);
}

.setup-list {
  display: flex;
  flex-direction: column;
  gap: 13px;
  margin: 18px 0;
  padding: 0;
  list-style: none;
}

.setup-list li {
  display: grid;
  grid-template-columns: 23px minmax(0, 1fr);
  gap: 9px;
  align-items: start;
  color: var(--text-2);
  font-size: 10.5px;
  line-height: 1.7;
}

.setup-number {
  display: grid;
  place-items: center;
  width: 23px;
  height: 23px;
  border: 1px solid var(--brand-line);
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font: 650 9px/1 var(--font-mono);
}

.explainer-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 10px;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-inset);
  color: var(--text-4);
}

.explainer-note .app-icon {
  margin-top: 1px;
  color: var(--text-3);
}

.explainer-note p {
  margin: 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.7;
}

.help-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 16px;
  font-size: 10.5px;
  font-weight: 600;
}

.mail-history {
  min-width: 0;
  margin-top: 18px;
  padding: 20px;
}

.mail-history:hover {
  border-color: var(--line);
}

.mail-history .surface-head {
  align-items: center;
  margin-bottom: 15px;
}

.time-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.time-cell b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 560;
}

.time-cell span {
  color: var(--text-4);
  font-size: 9.5px;
  font-variant-numeric: tabular-nums;
}

.result-badge {
  min-height: 21px;
  font-size: 9px;
}

.attempt-count {
  color: var(--text-2);
  font: 550 11px/1 var(--font-mono);
}

.attempt-count small {
  margin-left: 2px;
  color: var(--text-4);
  font-size: 9px;
}

.failure-copy {
  color: var(--danger);
}

.record-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 13px;
  min-height: 154px;
  padding: 24px;
  text-align: left;
}

.record-empty .empty-icon {
  width: 38px;
  height: 38px;
  border-color: var(--line);
  background: var(--surface-2);
  color: var(--text-4);
}

.record-empty > div {
  max-width: 410px;
}

.record-empty b {
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
}

.record-empty p {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.6;
}

.record-empty :deep(.el-button) {
  margin-left: 3px;
  flex: none;
}

.spin-icon {
  animation: mail-spin 1.2s linear infinite;
}

.authorization-line a:focus-visible,
.help-link:focus-visible,
.mail-form :deep(.el-button:focus-visible),
.mail-history :deep(.el-button:focus-visible) {
  outline: 2px solid var(--brand-strong);
  outline-offset: 2px;
}

@keyframes mail-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1100px) {
  .mail-layout {
    grid-template-columns: 1fr;
  }

  .mail-explainer {
    position: static;
  }
}

@media (max-width: 680px) {
  .mail-form,
  .mail-explainer,
  .mail-history {
    padding: 16px;
  }

  .section-heading {
    flex-wrap: wrap;
  }

  .section-heading .state-badge {
    margin-left: 47px;
  }

  .provider-switch,
  .mail-two-col,
  .category-grid {
    grid-template-columns: 1fr;
  }

  .mail-history .surface-head,
  .record-empty {
    align-items: flex-start;
    flex-direction: column;
  }

  .mail-history .surface-head :deep(.el-button) {
    margin-left: 47px;
  }

  .record-empty :deep(.el-button) {
    margin-left: 0;
  }

  .smtp-heading {
    flex-direction: column;
  }

  .enable-row {
    align-items: flex-start;
  }
}

@media (max-width: 420px) {
  .mail-actions :deep(.el-button) {
    width: 100%;
    justify-content: center;
  }

  .category-grid :deep(.el-checkbox) {
    min-height: 38px;
  }

  .summary-row {
    flex-direction: column;
    gap: 3px;
  }

  .summary-row b {
    max-width: 100%;
    text-align: left;
  }

  .section-heading .state-badge,
  .mail-history .surface-head :deep(.el-button) {
    margin-left: 0;
  }
}
</style>
