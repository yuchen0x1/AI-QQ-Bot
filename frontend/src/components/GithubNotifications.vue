<template>
  <section class="notifications surface" aria-labelledby="notifications-title">
    <div class="notification-heading">
      <div>
        <h2 id="notifications-title">全部项目动态，发送到你的通知群</h2>
        <p>提交了什么、谁提了 PR、哪里有新评论，直接在 QQ 里看。以后新建的仓库也会自动接入。</p>
      </div>
      <el-tag :type="state.delivery_blocked ? 'danger' : state.enabled && state.group_bound && identity?.connected ? 'success' : 'warning'">
        {{ state.delivery_blocked ? '群投递受限' : state.enabled && state.group_bound && identity?.connected ? '监控已启用' : '等待完成设置' }}
      </el-tag>
    </div>
    <div class="setup-layout">
      <div class="setup-controls">
        <div class="setup-step">
          <span class="step-number">1</span>
          <div class="step-body">
            <strong>连接你的 GitHub</strong>
            <p v-if="identity?.connected">已连接 @{{ identity.account?.login }}，仅接入这个账号拥有、且 Token 可以访问的仓库。</p>
            <p v-else>粘贴一次 Token 即可，无需创建 OAuth App。私有仓库也可以一起监控。</p>
            <el-button :type="identity?.connected ? 'default' : 'primary'" @click="tokenVisible = true">
              {{ identity?.connected ? '更新 GitHub Token' : '使用 Token 连接 GitHub' }}
            </el-button>
          </div>
        </div>
        <div class="setup-step">
          <span class="step-number">2</span>
          <div class="step-body">
            <div class="target-heading"><strong>设置通知群</strong><el-button size="small" type="primary" @click="openTarget()">添加通知群</el-button></div>
            <p>支持同时推送到多个群，每个群可以单独绑定和启停。官方机器人的真实群号由你填写，群内口令用于关联发送目标。</p>
            <div v-if="!state.targets?.length" class="target-empty">还没有通知群，点击「添加通知群」开始设置。</div>
            <div v-for="target in state.targets || []" :key="target.id" class="notification-target">
              <div class="target-title"><b>QQ群 {{ target.group_label }}</b><el-tag size="small" :type="target.bound ? 'success' : 'warning'">{{ target.bound ? '已绑定' : '待绑定' }}</el-tag><el-switch :model-value="target.enabled" :aria-label="`启用群 ${target.group_label} 的通知`" @change="toggleTarget(target, Boolean($event))" /></div>
              <p>{{ target.account_name }}</p>
              <p v-if="target.delivery" class="delivery-summary">近 7 天：成功 {{ target.delivery.delivered }} 条 · 失败 {{ target.delivery.failed }} 条 · 待发送 {{ target.delivery.pending }} 条</p>
              <p v-if="target.delivery?.permission_checked_at" :class="target.delivery.allow_proactive_msg === false ? 'status-error' : 'delivery-summary'">
                QQ 主动推送：{{ target.delivery.allow_proactive_msg === true ? '已允许' : target.delivery.allow_proactive_msg === false ? '未允许' : '无法确认' }}
                <span>（{{ new Date(target.delivery.permission_checked_at).toLocaleString('zh-CN') }} 检查）</span>
              </p>
              <p v-if="target.delivery?.proactive_blocked" class="status-error">请在 QQ 群内开启机器人的「允许主动发送／主动推送」，再检查权限并测试通知。绑定回复成功不代表主动推送已开启。</p>
              <p v-if="target.delivery?.last_error" class="status-error">最近投递错误：{{ target.delivery.last_error }}</p>
              <p v-if="target.delivery?.permission_error" class="status-warning">权限查询失败：{{ target.delivery.permission_error }}</p>
              <div class="inline-actions">
                <el-button v-if="target.protocol === 'qq_official'" size="small" :loading="binding === target.id" @click="generateCode(target)">{{ target.bound ? '重新绑定' : '生成绑定口令' }}</el-button>
                <el-button v-if="target.protocol === 'qq_official'" size="small" :disabled="!target.bound" :loading="checking === target.id" @click="checkPermission(target)">检查群权限</el-button>
                <el-button size="small" :disabled="!target.bound" :loading="testing === target.id" @click="sendTest(target)">测试主动通知</el-button>
                <el-button size="small" @click="openTarget(target)">修改</el-button>
                <el-button size="small" type="danger" plain @click="removeTarget(target)">移除</el-button>
              </div>
            </div>
          </div>
        </div>
        <div class="setup-step">
          <span class="step-number">3</span>
          <div class="step-body">
            <strong>选择要接收的动态</strong>
            <el-checkbox-group v-model="form.event_types" class="event-options">
              <el-checkbox v-for="option in state.event_options || []" :key="option.value" :value="option.value">{{ option.label }}</el-checkbox>
            </el-checkbox-group>
            <div class="delivery-options">
              <el-checkbox v-model="form.enabled">启用全部仓库通知</el-checkbox>
              <label>轮询间隔（秒） <el-input-number v-model="form.poll_interval_seconds" :min="60" :max="86400" :step="60" controls-position="right" /></label>
            </div>
            <el-checkbox v-model="form.install_webhooks">自动为仓库配置实时 Webhook（服务器部署后开启）</el-checkbox>
            <p>轮询无需公网回调，但 GitHub 的动态列表可能延迟或遗漏；实时通知需公网 HTTPS 地址和 Token 的 Webhooks 写权限。</p>
          </div>
        </div>
      </div>
      <aside class="notification-status" aria-label="通知状态">
        <strong>运行状态</strong>
        <dl>
          <div><dt>GitHub</dt><dd>{{ identity?.connected ? `@${identity.account?.login}` : '尚未连接' }}</dd></div>
          <div><dt>通知群</dt><dd>{{ state.bound_target_count || 0 }} 个已绑定并启用 / 共 {{ state.targets?.length || 0 }} 个</dd></div>
          <div><dt>已接入仓库</dt><dd>{{ state.monitored_count ?? 0 }} 个</dd></div>
          <div><dt>近 7 天失败投递</dt><dd>{{ state.failed_deliveries || 0 }} 条</dd></div>
          <div><dt>同步状态</dt><dd>{{ syncLabels[state.sync_status] || '尚未同步' }}</dd></div>
          <div><dt>上次同步</dt><dd>{{ state.last_sync_at ? new Date(state.last_sync_at).toLocaleString('zh-CN') : '—' }}</dd></div>
          <div v-if="state.effective_poll_interval_seconds"><dt>实际轮询间隔</dt><dd>{{ state.effective_poll_interval_seconds }} 秒</dd></div>
        </dl>
        <p v-for="warning in state.warnings || []" :key="warning" class="status-warning">{{ warning }}</p>
        <p v-if="state.last_error" class="status-error">{{ state.last_error }}</p>
        <details v-if="state.failures?.length"><summary>{{ state.failures.length }} 项同步异常</summary><p v-for="failure in state.failures" :key="failure.repository">{{ failure.repository }}：{{ failure.error }}</p></details>
        <div class="inline-actions status-actions">
          <el-button :disabled="!state.enabled || !identity?.connected" @click="syncNow">立即同步</el-button>
        </div>
        <p class="status-note">首次接入只建立基线，不推送旧动态。仓库清单约每分钟同步，已删除或不可访问的仓库停止监控并保留历史；群通知按上方轮询间隔检查。<router-link to="/help">查看分步指引</router-link></p>
      </aside>
    </div>
    <footer class="notification-footer">
      <span>设置保存在服务端；服务器使用新数据库时，需要重新连接一次。</span>
      <el-button type="primary" :loading="saving" :disabled="!form.event_types.length" @click="save">保存通知设置</el-button>
    </footer>
  </section>

  <el-dialog v-model="targetVisible" :title="targetForm.id ? '修改通知群' : '添加通知群'" width="min(600px, calc(100vw - 28px))">
    <el-form label-position="top" @submit.prevent="saveTarget">
      <el-form-item label="发送机器人"><el-select v-model="targetForm.account_id" placeholder="选择发送机器人" style="width:100%"><el-option v-for="account in accounts" :key="account.id" :value="account.id" :label="account.name" /></el-select></el-form-item>
      <el-form-item label="实际 QQ 群号"><el-input v-model="targetForm.group_label" inputmode="numeric" maxlength="20" placeholder="填写你在 QQ 中看到的群号码" /></el-form-item>
      <el-checkbox v-model="targetForm.enabled">启用这个群的通知</el-checkbox>
    </el-form>
    <p v-if="official">保存后，在这个群中 @ 机器人发送绑定口令即可。添加新群会保留其他群的绑定和推送设置。</p>
    <p v-else>请确认所选机器人已经加入这个群。</p>
    <template #footer><el-button @click="targetVisible = false">取消</el-button><el-button type="primary" :loading="savingTarget" :disabled="!targetForm.account_id || !targetForm.group_label" @click="saveTarget">{{ official ? '保存并绑定' : '保存通知群' }}</el-button></template>
  </el-dialog>
  <el-dialog v-model="tokenVisible" title="连接 GitHub Token" width="min(620px, calc(100vw - 28px))" @closed="token = ''">
    <p>在 GitHub 创建专门给机器人的 Token，仓库访问选择「All repositories」。Token 只保存在后端，连接后不会回显。</p>
    <p><a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">打开 GitHub 创建 Token</a></p>
    <el-alert type="info" :closable="false" title="权限建议：Contents、Issues、Pull requests、Actions、Discussions 读取；自动配置实时通知还需要 Webhooks 读写。只能监控 Token 获准访问的仓库。" />
    <el-form label-position="top" class="token-form" @submit.prevent="connectToken">
      <el-form-item label="GitHub Token"><el-input v-model="token" type="password" autocomplete="off" placeholder="github_pat_… 或 ghp_…" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="tokenVisible = false">取消</el-button><el-button type="primary" :loading="connecting" :disabled="!token.trim()" @click="connectToken">连接并读取账号</el-button></template>
  </el-dialog>
  <el-dialog v-model="codeVisible" title="在通知群绑定机器人" width="min(600px, calc(100vw - 28px))">
    <p>请把机器人加入群 <b>{{ bindingCode.group_label }}</b>，在该群 <b>@ 机器人</b> 并发送以下口令：</p>
    <pre class="binding-command">{{ bindingCode.command }}</pre>
    <p>口令 10 分钟内有效、只能使用一次。机器人回复绑定成功后，本页会自动更新状态。</p>
    <el-alert type="info" :closable="false" title="如果没有回复，请核对两处接收方式：QQ 账号管理与 QQ 开放平台 → 开发设置 → 事件订阅与回调。本地运行请选择 WebSocket，并在开放平台点击保存。" />
    <template #footer><el-button @click="codeVisible = false">关闭</el-button><el-button type="primary" @click="copyCode">复制口令</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

defineProps<{ identity: any }>()
const emit = defineEmits(['connected', 'changed'])
const state = ref<any>({})
const accounts = ref<any[]>([])
const form = reactive<any>({ enabled: true, event_types: [], poll_interval_seconds: 300, install_webhooks: false })
const targetVisible = ref(false), savingTarget = ref(false)
const targetForm = reactive<any>({ id: null, account_id: null, group_label: '', enabled: true })
const official = computed(() => accounts.value.find(a => a.id === targetForm.account_id)?.protocol === 'qq_official')
const saving = ref(false), binding = ref<number | null>(null), connecting = ref(false), testing = ref<number | null>(null)
const checking = ref<number | null>(null)
const tokenVisible = ref(false), codeVisible = ref(false), token = ref('')
const bindingCode = ref<any>({})
const syncLabels: Record<string, string> = { waiting: '等待连接 GitHub', queued: '等待后台同步', running: '正在同步', ok: '同步完成', partial: '部分仓库异常', error: '同步失败' }
let refreshTimer: ReturnType<typeof setInterval> | undefined
let refreshing = false

async function refresh(initial = false) {
  if (refreshing) return
  refreshing = true
  try {
    const { data } = await api.get('/github/automation')
    const previousSync = state.value.last_sync_at
    state.value = data
    if (initial) {
      const response = await api.get('/accounts')
      accounts.value = response.data.filter((a: any) => a.enabled && a.protocol === 'qq_official')
      for (const key of Object.keys(form)) if (data[key] !== undefined) form[key] = data[key]
      if (!data.event_types) form.event_types = (data.event_options || []).map((o: any) => o.value)
    }
    if (previousSync !== data.last_sync_at) emit('changed')
    if (codeVisible.value && data.targets?.some((t: any) => t.id === bindingCode.value.target_id && t.bound && t.updated_at !== bindingCode.value.previous_updated_at)) { codeVisible.value = false; ElMessage.success('通知群绑定成功') }
  } finally { refreshing = false }
}
function openTarget(target?: any) {
  Object.assign(targetForm, { id: target?.id || null, account_id: target?.account_id || (accounts.value.length === 1 ? accounts.value[0].id : null), group_label: target?.group_label || '', enabled: target?.enabled ?? true })
  targetVisible.value = true
}
async function saveTarget() {
  if (!/^[1-9][0-9]{4,19}$/.test(targetForm.group_label)) { ElMessage.warning('请填写有效的 QQ 群号码'); return }
  savingTarget.value = true
  try {
    const previousIds = new Set((state.value.targets || []).map((t: any) => t.id))
    const payload = { account_id: targetForm.account_id, group_label: targetForm.group_label, enabled: targetForm.enabled }
    const { data } = targetForm.id ? await api.put(`/github/automation/targets/${targetForm.id}`, payload) : await api.post('/github/automation/targets', payload)
    state.value = data
    const target = data.targets.find((t: any) => targetForm.id ? t.id === targetForm.id : !previousIds.has(t.id))
    targetVisible.value = false
    ElMessage.success('通知群已保存')
    if (target?.protocol === 'qq_official' && !target.bound) await generateCode(target)
    emit('changed')
  } finally { savingTarget.value = false }
}
async function toggleTarget(target: any, enabled: boolean) {
  const { data } = await api.put(`/github/automation/targets/${target.id}`, { account_id: target.account_id, group_label: target.group_label, enabled })
  state.value = data
  ElMessage.success(enabled ? '已启用这个群的通知' : '已暂停这个群的通知')
  emit('changed')
}
async function removeTarget(target: any) {
  try { await ElMessageBox.confirm(`移除通知群 ${target.group_label}？其他群的通知会保留。`, '移除通知群', { type: 'warning' }) } catch { return }
  const { data } = await api.delete(`/github/automation/targets/${target.id}`)
  state.value = data
  ElMessage.success('已移除通知群')
  emit('changed')
}
async function save() {
  saving.value = true
  try {
    const payload = { ...form }
    const { data } = await api.put('/github/automation', payload)
    state.value = data
    ElMessage.success(data.connected ? '设置已保存，后台将接入你的全部仓库' : '设置已保存，请连接 GitHub Token')
  } finally { saving.value = false }
}
async function connectToken() {
  connecting.value = true
  try {
    await api.post('/github/oauth/token', { token: token.value.trim() })
    token.value = ''
    tokenVisible.value = false
    emit('connected')
    ElMessage.success('GitHub 已连接，请保存通知设置以接入全部仓库')
    await refresh()
  } finally { connecting.value = false }
}
async function generateCode(target: any) {
  binding.value = target.id
  try {
    const { data } = await api.post('/github/automation/binding-code', null, { params: { target_id: target.id } })
    bindingCode.value = { ...data, previous_updated_at: target.updated_at }
    codeVisible.value = true
  } finally { binding.value = null }
}
async function copyCode() {
  try { await navigator.clipboard.writeText(bindingCode.value.command); ElMessage.success('口令已复制') }
  catch { ElMessage.info('请选中上方口令手动复制') }
}
async function syncNow() { const { data } = await api.post('/github/automation/sync'); ElMessage.success(data.message); await refresh() }
async function sendTest(target: any) {
  try { await ElMessageBox.confirm(`向通知群 ${target.group_label} 发送一条主动通知，验证仓库更新时能否自动发群？`, '测试主动通知') } catch { return }
  testing.value = target.id
  try { const { data } = await api.post('/github/automation/test', null, { params: { target_id: target.id } }); ElMessage.success(data.message) } finally { testing.value = null; await refresh() }
}
async function checkPermission(target: any) {
  checking.value = target.id
  try {
    const { data } = await api.post(`/github/automation/targets/${target.id}/permissions`)
    state.value = data
    const allowed = data.targets.find((t: any) => t.id === target.id)?.delivery?.allow_proactive_msg
    if (allowed === true) ElMessage.success('QQ 已允许该群接收主动通知')
    else if (allowed === false) ElMessage.warning('QQ 尚未允许主动推送，请在群内开启')
    else ElMessage.info('QQ 未返回明确的主动推送权限状态')
  } finally { checking.value = null; await refresh() }
}
onMounted(async () => {
  await refresh(true)
  refreshTimer = setInterval(() => { refresh().catch(() => {}) }, 8000)
})
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<style scoped>
.notifications{margin-bottom:20px;padding:24px;border:1px solid #293951;border-radius:14px;background:#101827}
.notification-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:28px}
h2{margin:0 0 10px;color:#f0f3fa;font-size:22px;letter-spacing:-.3px}
p{margin:8px 0 14px;color:#98a8bf;line-height:1.7;font-size:13px;max-width:72ch}
.setup-layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:36px;align-items:start}
.setup-step{display:flex;gap:16px;margin-bottom:26px}.step-number{display:grid;place-items:center;flex-shrink:0;width:28px;height:28px;border:1px solid #405271;border-radius:50%;color:#92dbe4;font-size:13px}
.step-body{min-width:0;flex:1}.step-body>strong,.notification-status>strong{font-size:15px;color:#f0f3fa}.destination-form{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:14px}
.inline-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.event-options{display:flex;flex-wrap:wrap;column-gap:16px;margin-top:12px}.event-options .el-checkbox{margin-right:0;min-width:115px}
.target-heading,.target-title{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.target-heading{justify-content:space-between}.target-title b{color:#e9f2ff;font-size:15px;overflow-wrap:anywhere}.target-title .el-switch{margin-left:auto}.notification-target{border:1px solid #33445e;background:#132035;border-radius:10px;padding:16px;margin-top:12px}.notification-target p{margin:8px 0 12px}.notification-target .el-button{margin-left:0}.target-empty{padding:22px;border:1px dashed #405271;border-radius:10px;color:#98a8bf}
.delivery-options{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin:14px 0}.delivery-options label{color:#aebbd0;font-size:12px}.delivery-options .el-input-number{width:125px;margin-left:8px}
.notification-status{padding:20px;border-left:2px solid #667de0;background:#131e30;border-radius:0 10px 10px 0;min-width:0}dl{margin:18px 0}dl div{display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-bottom:1px solid #27354c;font-size:12px}dt{color:#8e9fb7}dd{margin:0;color:#e2e9f5;text-align:right;overflow-wrap:anywhere}.status-warning{color:#edc987;margin:10px 0}.status-error{color:#ffa5a5}.status-note{font-size:12px;margin-top:18px}.status-actions{margin-top:18px}.status-actions .el-button{margin-left:0}details{color:#d0a96b;font-size:12px}
.notification-target .delivery-summary{font-size:12px;color:#9fb4ce}.notification-target .status-error{color:#ffa5a5;overflow-wrap:anywhere}
.notification-footer{display:flex;justify-content:space-between;align-items:center;gap:20px;padding-top:18px;border-top:1px solid #293951}.notification-footer span{color:#8293ad;font-size:12px}
.token-form{margin-top:20px}.binding-command{padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid #405271;border-radius:8px;color:#92dbe4;font-size:15px;background:#101827}a{color:#8bd7e5}
:deep(.el-alert){background:#18253a;color:#b9cce8;border:1px solid #324866}:deep(.el-alert__title){color:#b9cce8;line-height:1.7}
@media(max-width:1150px){.setup-layout{grid-template-columns:1fr}.notification-status{border-left:0;border-top:2px solid #667de0}.notification-heading{flex-wrap:wrap}}
@media(max-width:650px){.notifications{padding:18px}.destination-form{grid-template-columns:1fr;gap:0}.notification-footer{align-items:flex-start;flex-direction:column}h2{font-size:19px}.step-number{display:none}}
</style>
