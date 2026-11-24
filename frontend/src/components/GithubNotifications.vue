<template>
  <section class="notifications surface" aria-labelledby="notifications-title">
    <div class="notification-heading">
      <span class="notification-heading-icon"><AppIcon name="bell" :size="19" /></span>
      <div class="notification-heading-copy">
        <div class="eyebrow">NOTIFICATION ROUTING</div>
        <h2 id="notifications-title">全部项目动态，发送到你的通知群</h2>
        <p>提交、PR、Issue 与评论都会进入所选通知群。新增仓库会自动接入已有设置；每个群可独立启停。</p>
      </div>
      <el-tag
        :type="state.delivery_blocked ? 'danger' : state.enabled && state.group_bound && identity?.connected ? 'success' : 'warning'"
        effect="plain"
      >
        {{ state.delivery_blocked ? '群投递受限' : state.enabled && state.group_bound && identity?.connected ? '监控已启用' : '等待完成设置' }}
      </el-tag>
    </div>

    <div class="setup-layout">
      <div class="setup-controls">
        <section class="setup-step" aria-labelledby="github-connect-title">
          <span class="step-number" aria-hidden="true">1</span>
          <div class="step-body">
            <div class="step-heading">
              <div>
                <span class="step-kicker">IDENTITY</span>
                <h3 id="github-connect-title">连接你的 GitHub</h3>
              </div>
              <el-tag :type="identity?.connected ? 'success' : 'info'" size="small" effect="plain">
                {{ identity?.connected ? '已连接' : '未连接' }}
              </el-tag>
            </div>
            <p v-if="identity?.connected">已连接 @{{ identity.account?.login }}，仅接入这个账号拥有、且 Token 可以访问的仓库。</p>
            <p v-else>粘贴一次 Token 即可，无需创建 OAuth App。私有仓库也可以一起监控。</p>
            <div class="identity-source">
              <span class="source-icon" :class="{ connected: identity?.connected }">
                <AppIcon :name="identity?.connected ? 'check-circle' : 'key'" :size="16" />
              </span>
              <div class="source-copy">
                <b>{{ identity?.connected ? `@${identity.account?.login}` : '等待 GitHub 身份' }}</b>
                <small>{{ identity?.connected ? 'Token 已加密保存在服务端，不会回显' : '支持 Fine-grained token 或经典 Personal Access Token' }}</small>
              </div>
              <el-button :type="identity?.connected ? 'default' : 'primary'" @click="tokenVisible = true">
                <AppIcon name="key" :size="14" />
                {{ identity?.connected ? '更新 GitHub Token' : '使用 Token 连接 GitHub' }}
              </el-button>
            </div>
          </div>
        </section>

        <section class="setup-step" aria-labelledby="notification-target-title">
          <span class="step-number" aria-hidden="true">2</span>
          <div class="step-body">
            <div class="step-heading">
              <div>
                <span class="step-kicker">ROUTING</span>
                <h3 id="notification-target-title">设置通知群</h3>
              </div>
              <el-button size="small" type="primary" @click="openTarget()">
                <AppIcon name="plus" :size="13" />
                添加通知群
              </el-button>
            </div>
            <p>支持同时推送到多个群。官方机器人的真实群号由你填写，群内口令用于关联发送目标。</p>
            <div v-if="!state.targets?.length" class="target-empty">
              还没有通知群，点击「添加通知群」开始设置。
            </div>
            <div v-for="target in state.targets || []" :key="target.id" class="notification-target">
              <div class="target-title">
                <span class="target-icon"><AppIcon name="users" :size="15" /></span>
                <div class="target-label">
                  <b>QQ群 {{ target.group_label }}</b>
                  <small>{{ target.account_name }}</small>
                </div>
                <div class="target-badges">
                  <el-tag size="small" :type="target.bound ? 'success' : 'warning'" effect="plain">
                    {{ target.bound ? '已绑定' : '待绑定' }}
                  </el-tag>
                  <span class="target-enabled-label">{{ target.enabled ? '投递启用' : '投递暂停' }}</span>
                  <el-switch
                    :model-value="target.enabled"
                    :aria-label="`启用群 ${target.group_label} 的通知`"
                    @change="toggleTarget(target, Boolean($event))"
                  />
                </div>
              </div>
              <p v-if="target.delivery" class="delivery-summary">
                近 7 天：成功 {{ target.delivery.delivered }} 条 · 失败 {{ target.delivery.failed }} 条 · 待发送 {{ target.delivery.pending }} 条
              </p>
              <p
                v-if="target.delivery?.permission_checked_at"
                :class="target.delivery.allow_proactive_msg === false ? 'status-error' : 'delivery-summary'"
              >
                QQ 主动推送：{{ target.delivery.allow_proactive_msg === true ? '已允许' : target.delivery.allow_proactive_msg === false ? '未允许' : '无法确认' }}
                <span>（{{ new Date(target.delivery.permission_checked_at).toLocaleString('zh-CN') }} 检查）</span>
              </p>
              <p v-if="target.delivery?.proactive_blocked" class="status-error">
                请在 QQ 群内开启机器人的「允许主动发送／主动推送」，再检查权限并测试通知。绑定回复成功不代表主动推送已开启。
              </p>
              <p v-if="target.delivery?.last_error" class="status-error">最近投递错误：{{ target.delivery.last_error }}</p>
              <p v-if="target.delivery?.permission_error" class="status-warning">权限查询失败：{{ target.delivery.permission_error }}</p>
              <div class="inline-actions">
                <el-button
                  v-if="target.protocol === 'qq_official'"
                  size="small"
                  :loading="binding === target.id"
                  @click="generateCode(target)"
                >
                  <AppIcon name="key" :size="13" />
                  {{ target.bound ? '重新绑定' : '生成绑定口令' }}
                </el-button>
                <el-button
                  v-if="target.protocol === 'qq_official'"
                  size="small"
                  :disabled="!target.bound"
                  :loading="checking === target.id"
                  @click="checkPermission(target)"
                >
                  <AppIcon name="shield" :size="13" />
                  检查群权限
                </el-button>
                <el-button size="small" :disabled="!target.bound" :loading="testing === target.id" @click="sendTest(target)">
                  <AppIcon name="send" :size="13" />
                  测试主动通知
                </el-button>
                <el-button size="small" @click="openTarget(target)">
                  <AppIcon name="edit" :size="13" />
                  修改
                </el-button>
                <el-button size="small" type="danger" plain @click="removeTarget(target)">
                  <AppIcon name="trash" :size="13" />
                  移除
                </el-button>
              </div>
            </div>
          </div>
        </section>

        <section class="setup-step" aria-labelledby="notification-events-title">
          <span class="step-number" aria-hidden="true">3</span>
          <div class="step-body">
            <div class="step-heading">
              <div>
                <span class="step-kicker">EVENT SCOPE</span>
                <h3 id="notification-events-title">选择要接收的动态</h3>
              </div>
              <span class="step-count">{{ form.event_types.length }} 项</span>
            </div>
            <el-checkbox-group v-model="form.event_types" class="event-options">
              <el-checkbox v-for="option in state.event_options || []" :key="option.value" :value="option.value">
                {{ option.label }}
              </el-checkbox>
            </el-checkbox-group>
            <div class="delivery-options">
              <el-checkbox v-model="form.enabled">启用全部仓库通知</el-checkbox>
              <label>
                轮询间隔（秒）
                <el-input-number
                  v-model="form.poll_interval_seconds"
                  :min="60"
                  :max="86400"
                  :step="60"
                  controls-position="right"
                />
              </label>
            </div>
            <el-checkbox v-model="form.install_webhooks" class="webhook-option">
              自动为仓库配置实时 Webhook（服务器部署后开启）
            </el-checkbox>
            <p class="step-note">轮询无需公网回调，但 GitHub 的动态列表可能延迟或遗漏；实时通知需公网 HTTPS 地址和 Token 的 Webhooks 写权限。</p>
          </div>
        </section>
      </div>

      <aside class="notification-status" aria-label="通知运行状态">
        <div class="status-heading">
          <span class="status-icon"><AppIcon name="activity" :size="16" /></span>
          <h3>运行状态</h3>
          <el-tag size="small" effect="plain">{{ syncLabels[state.sync_status] || '尚未同步' }}</el-tag>
        </div>
        <div class="detail-list status-details">
          <div class="detail-row">
            <span>GitHub</span>
            <b>{{ identity?.connected ? `@${identity.account?.login}` : '尚未连接' }}</b>
          </div>
          <div class="detail-row">
            <span>通知群</span>
            <b>{{ state.bound_target_count || 0 }} 个已绑定并启用 / 共 {{ state.targets?.length || 0 }} 个</b>
          </div>
          <div class="detail-row">
            <span>已接入仓库</span>
            <b>{{ state.monitored_count ?? '—' }} 个</b>
          </div>
          <div class="detail-row">
            <span>近 7 天失败投递</span>
            <b>{{ state.failed_deliveries ?? '—' }} 条</b>
          </div>
          <div class="detail-row">
            <span>同步状态</span>
            <b>{{ syncLabels[state.sync_status] || '尚未同步' }}</b>
          </div>
          <div class="detail-row">
            <span>上次同步</span>
            <b>{{ state.last_sync_at ? new Date(state.last_sync_at).toLocaleString('zh-CN') : '—' }}</b>
          </div>
          <div v-if="state.effective_poll_interval_seconds" class="detail-row">
            <span>实际轮询间隔</span>
            <b>{{ state.effective_poll_interval_seconds }} 秒</b>
          </div>
        </div>
        <div v-if="state.warnings?.length" class="status-alert-list">
          <p v-for="warning in state.warnings" :key="warning" class="status-warning">
            <AppIcon name="alert" :size="13" />
            <span>{{ warning }}</span>
          </p>
        </div>
        <p v-if="state.last_error" class="status-error">{{ state.last_error }}</p>
        <details v-if="state.failures?.length" class="failure-details">
          <summary>{{ state.failures.length }} 项同步异常</summary>
          <p v-for="failure in state.failures" :key="failure.repository">{{ failure.repository }}：{{ failure.error }}</p>
        </details>
        <div class="inline-actions status-actions">
          <el-button :disabled="!state.enabled || !identity?.connected" @click="syncNow">
            <AppIcon name="refresh" :size="13" />
            立即同步
          </el-button>
        </div>
        <p class="status-note">
          首次接入只建立基线，不推送旧动态。仓库清单约每分钟同步，已删除或不可访问的仓库停止监控并保留历史；群通知按上方轮询间隔检查。
          <router-link to="/help">查看分步指引</router-link>
        </p>
      </aside>
    </div>

    <footer class="notification-footer">
      <span>设置保存在服务端；服务器使用新数据库时，需要重新连接一次。</span>
      <el-button type="primary" :loading="saving" :disabled="!form.event_types.length" @click="save">
        <AppIcon name="check" :size="14" />
        保存通知设置
      </el-button>
    </footer>
  </section>

  <el-dialog v-model="targetVisible" :title="targetForm.id ? '修改通知群' : '添加通知群'" width="min(600px, calc(100vw - 28px))">
    <p class="dialog-lead">为已启用的 QQ 官方机器人添加实际群号。保存后可生成一次性口令完成群内绑定。</p>
    <el-form label-position="top" class="target-form" @submit.prevent="saveTarget">
      <section class="dialog-section">
        <div class="dialog-section-head">
          <span class="form-section-icon"><AppIcon name="bot" :size="16" /></span>
          <div>
            <h3>发送目标</h3>
            <p>选择负责发送通知的机器人，并填写 QQ 中看到的真实群号</p>
          </div>
        </div>
        <el-form-item label="发送机器人">
          <el-select v-model="targetForm.account_id" placeholder="选择发送机器人">
            <el-option v-for="account in accounts" :key="account.id" :value="account.id" :label="account.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="实际 QQ 群号">
          <el-input v-model="targetForm.group_label" inputmode="numeric" maxlength="20" placeholder="填写你在 QQ 中看到的群号码" />
        </el-form-item>
      </section>
      <div class="switch-field">
        <div>
          <b>启用这个群的通知</b>
          <small>关闭后保留绑定与历史，但暂停向此群投递</small>
        </div>
        <el-switch v-model="targetForm.enabled" aria-label="启用这个群的通知" />
      </div>
    </el-form>
    <p v-if="official" class="dialog-note">保存后，在这个群中 @ 机器人发送绑定口令即可。添加新群会保留其他群的绑定和推送设置。</p>
    <p v-else class="dialog-note">请确认所选机器人已经加入这个群。</p>
    <template #footer>
      <el-button @click="targetVisible = false">取消</el-button>
      <el-button
        type="primary"
        :loading="savingTarget"
        :disabled="!targetForm.account_id || !targetForm.group_label"
        @click="saveTarget"
      >
        {{ official ? '保存并绑定' : '保存通知群' }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="tokenVisible" title="连接 GitHub Token" width="min(620px, calc(100vw - 28px))" @closed="token = ''">
    <div class="token-guide">
      <p>在 GitHub 创建专门给机器人的 Token，仓库访问选择「All repositories」。Token 只保存在后端，连接后不会回显。</p>
      <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">
        打开 GitHub 创建 Token
        <AppIcon name="external" :size="13" />
      </a>
    </div>
    <el-alert
      type="info"
      :closable="false"
      title="权限建议：Contents、Issues、Pull requests、Actions、Discussions 读取；自动配置实时通知还需要 Webhooks 读写。只能监控 Token 获准访问的仓库。"
    />
    <el-form label-position="top" class="token-form" @submit.prevent="connectToken">
      <el-form-item label="GitHub Token">
        <el-input v-model="token" type="password" autocomplete="off" placeholder="github_pat_… 或 ghp_…" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="tokenVisible = false">取消</el-button>
      <el-button type="primary" :loading="connecting" :disabled="!token.trim()" @click="connectToken">
        连接并读取账号
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="codeVisible" title="在通知群绑定机器人" width="min(600px, calc(100vw - 28px))">
    <p>请把机器人加入群 <b>{{ bindingCode.group_label }}</b>，在该群 <b>@ 机器人</b> 并发送以下口令：</p>
    <div class="binding-command-wrap">
      <pre class="binding-command" aria-label="通知群绑定口令">{{ bindingCode.command }}</pre>
      <el-button type="primary" plain @click="copyCode">
        <AppIcon name="copy" :size="14" />
        复制口令
      </el-button>
    </div>
    <p>口令 10 分钟内有效、只能使用一次。机器人回复绑定成功后，本页会自动更新状态。</p>
    <el-alert
      type="info"
      :closable="false"
      title="如果没有回复，请核对两处接收方式：QQ 账号管理与 QQ 开放平台 → 开发设置 → 事件订阅与回调。本地运行请选择 WebSocket，并在开放平台点击保存。"
    />
    <template #footer>
      <el-button @click="codeVisible = false">关闭</el-button>
      <el-button type="primary" @click="copyCode">
        <AppIcon name="copy" :size="14" />
        复制口令
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from './AppIcon.vue'
import { api } from '../api'

defineProps<{ identity: any }>()
const emit = defineEmits(['connected', 'changed'])
const state = ref<any>({})
const accounts = ref<any[]>([])
const form = reactive<any>({ enabled: true, event_types: [], poll_interval_seconds: 300, install_webhooks: false })
const targetVisible = ref(false), savingTarget = ref(false)
const targetForm = reactive<any>({ id: null, account_id: null, group_label: '', enabled: true })
const official = computed(() => accounts.value.find((account) => account.id === targetForm.account_id)?.protocol === 'qq_official')
const saving = ref(false), binding = ref<number | null>(null), connecting = ref(false), testing = ref<number | null>(null)
const checking = ref<number | null>(null)
const tokenVisible = ref(false), codeVisible = ref(false), token = ref('')
const bindingCode = ref<any>({})
const syncLabels: Record<string, string> = {
  waiting: '等待连接 GitHub',
  queued: '等待后台同步',
  running: '正在同步',
  ok: '同步完成',
  partial: '部分仓库异常',
  error: '同步失败',
}
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
      accounts.value = response.data.filter((account: any) => account.enabled && account.protocol === 'qq_official')
      for (const key of Object.keys(form)) if (data[key] !== undefined) form[key] = data[key]
      if (!data.event_types) form.event_types = (data.event_options || []).map((option: any) => option.value)
    }
    if (previousSync !== data.last_sync_at) emit('changed')
    if (
      codeVisible.value
      && data.targets?.some((target: any) => (
        target.id === bindingCode.value.target_id
        && target.bound
        && target.updated_at !== bindingCode.value.previous_updated_at
      ))
    ) {
      codeVisible.value = false
      ElMessage.success('通知群绑定成功')
    }
  } finally {
    refreshing = false
  }
}

function openTarget(target?: any) {
  Object.assign(targetForm, {
    id: target?.id || null,
    account_id: target?.account_id || (accounts.value.length === 1 ? accounts.value[0].id : null),
    group_label: target?.group_label || '',
    enabled: target?.enabled ?? true,
  })
  targetVisible.value = true
}

async function saveTarget() {
  if (!/^[1-9][0-9]{4,19}$/.test(targetForm.group_label)) {
    ElMessage.warning('请填写有效的 QQ 群号码')
    return
  }
  savingTarget.value = true
  try {
    const previousIds = new Set((state.value.targets || []).map((target: any) => target.id))
    const payload = {
      account_id: targetForm.account_id,
      group_label: targetForm.group_label,
      enabled: targetForm.enabled,
    }
    const { data } = targetForm.id
      ? await api.put(`/github/automation/targets/${targetForm.id}`, payload)
      : await api.post('/github/automation/targets', payload)
    state.value = data
    const target = data.targets.find((item: any) => (
      targetForm.id ? item.id === targetForm.id : !previousIds.has(item.id)
    ))
    targetVisible.value = false
    ElMessage.success('通知群已保存')
    if (target?.protocol === 'qq_official' && !target.bound) await generateCode(target)
    emit('changed')
  } finally {
    savingTarget.value = false
  }
}

async function toggleTarget(target: any, enabled: boolean) {
  const { data } = await api.put(`/github/automation/targets/${target.id}`, {
    account_id: target.account_id,
    group_label: target.group_label,
    enabled,
  })
  state.value = data
  ElMessage.success(enabled ? '已启用这个群的通知' : '已暂停这个群的通知')
  emit('changed')
}

async function removeTarget(target: any) {
  try {
    await ElMessageBox.confirm(`移除通知群 ${target.group_label}？其他群的通知会保留。`, '移除通知群', { type: 'warning' })
  } catch {
    return
  }
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
  } finally {
    saving.value = false
  }
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
  } finally {
    connecting.value = false
  }
}

async function generateCode(target: any) {
  binding.value = target.id
  try {
    const { data } = await api.post('/github/automation/binding-code', null, { params: { target_id: target.id } })
    bindingCode.value = { ...data, previous_updated_at: target.updated_at }
    codeVisible.value = true
  } finally {
    binding.value = null
  }
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(bindingCode.value.command)
    ElMessage.success('口令已复制')
  } catch {
    ElMessage.info('请选中上方口令手动复制')
  }
}

async function syncNow() {
  const { data } = await api.post('/github/automation/sync')
  ElMessage.success(data.message)
  await refresh()
}

async function sendTest(target: any) {
  try {
    await ElMessageBox.confirm(
      `向通知群 ${target.group_label} 发送一条主动通知，验证仓库更新时能否自动发群？`,
      '测试主动通知',
    )
  } catch {
    return
  }
  testing.value = target.id
  try {
    const { data } = await api.post('/github/automation/test', null, { params: { target_id: target.id } })
    ElMessage.success(data.message)
  } finally {
    testing.value = null
    await refresh()
  }
}

async function checkPermission(target: any) {
  checking.value = target.id
  try {
    const { data } = await api.post(`/github/automation/targets/${target.id}/permissions`)
    state.value = data
    const allowed = data.targets.find((item: any) => item.id === target.id)?.delivery?.allow_proactive_msg
    if (allowed === true) ElMessage.success('QQ 已允许该群接收主动通知')
    else if (allowed === false) ElMessage.warning('QQ 尚未允许主动推送，请在群内开启')
    else ElMessage.info('QQ 未返回明确的主动推送权限状态')
  } finally {
    checking.value = null
    await refresh()
  }
}

onMounted(async () => {
  await refresh(true)
  refreshTimer = setInterval(() => {
    refresh().catch(() => {})
  }, 8000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.notifications {
  margin-bottom: 0;
  padding: var(--space-6);
}

.notification-heading {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}

.notification-heading-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 11px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.notification-heading-copy {
  min-width: 0;
  flex: 1;
}

.notification-heading-copy .eyebrow {
  margin-bottom: 5px;
}

.notification-heading h2 {
  margin: 0 0 5px;
  color: var(--text);
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.35;
}

.notification-heading p {
  max-width: 760px;
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.notification-heading > .el-tag {
  flex: none;
}

.setup-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 318px;
  gap: 28px;
  align-items: start;
}

.setup-controls {
  min-width: 0;
}

.setup-step {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 13px;
  padding-bottom: 24px;
}

.setup-step + .setup-step {
  margin-top: 2px;
  padding-top: 24px;
  border-top: 1px solid var(--line-soft);
}

.setup-step:last-child {
  padding-bottom: 0;
}

.step-number {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--brand-line);
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font: 600 11px/1 var(--font-mono);
}

.step-body {
  min-width: 0;
}

.step-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.step-heading > div {
  min-width: 0;
}

.step-kicker {
  display: block;
  margin-bottom: 3px;
  color: var(--text-4);
  font: 600 8.5px/1.4 var(--font-mono);
  letter-spacing: 0.12em;
}

.step-heading h3 {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  font-weight: 620;
  letter-spacing: -0.01em;
}

.step-body > p {
  max-width: 74ch;
  margin: 0 0 12px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.7;
}

.step-body > p.step-note {
  margin-top: 10px;
  margin-bottom: 0;
  color: var(--text-4);
  font-size: 9.5px;
}

.step-count {
  color: var(--text-4);
  font: 550 9.5px/1 var(--font-mono);
}

.identity-source {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface-2);
}

.source-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-3);
}

.source-icon.connected {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.source-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.source-copy b {
  overflow: hidden;
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-copy small {
  color: var(--text-4);
  font-size: 9px;
  line-height: 1.45;
}

.identity-source .el-button {
  flex: none;
}

.target-empty {
  padding: 18px;
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  background: var(--surface-inset);
  color: var(--text-3);
  font-size: 10.5px;
  text-align: center;
}

.notification-target {
  margin-top: 10px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface-2);
}

.target-title {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.target-icon {
  display: grid;
  place-items: center;
  width: 29px;
  height: 29px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-3);
}

.target-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.target-label b {
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
}

.target-label small {
  color: var(--text-4);
  font-size: 9px;
}

.target-badges {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin-left: auto;
}

.target-enabled-label {
  color: var(--text-4);
  font-size: 9px;
}

.notification-target > p {
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.notification-target > p.delivery-summary {
  color: var(--text-2);
}

.notification-target > p.status-error {
  color: var(--danger);
}

.notification-target > p.status-warning {
  color: var(--warning);
}

.notification-target > p span {
  color: var(--text-4);
}

.inline-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 11px;
}

.inline-actions .el-button {
  margin-left: 0;
}

:deep(.el-button .app-icon) {
  margin-right: 4px;
}

.event-options {
  display: flex;
  flex-wrap: wrap;
  column-gap: 18px;
  margin: 4px 0 0;
}

.event-options :deep(.el-checkbox) {
  min-width: 116px;
  margin-right: 0;
  height: 30px;
}

.delivery-options {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  margin: 13px 0;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-2);
}

.delivery-options label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-2);
  font-size: 10px;
}

.delivery-options :deep(.el-input-number) {
  width: 126px;
}

.webhook-option {
  height: auto;
  white-space: normal;
}

.notification-status {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-inset);
}

.status-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}

.status-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border: 1px solid var(--cyan-line);
  border-radius: 8px;
  background: var(--cyan-soft);
  color: var(--cyan);
}

.status-heading h3 {
  margin: 0;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 620;
  flex: 1;
}

.status-details {
  margin-top: 2px;
}

.status-details .detail-row {
  gap: 12px;
  padding: 9px 0;
  font-size: 9.5px;
}

.status-details .detail-row > b {
  font-size: 9.5px;
  font-weight: 550;
}

.status-alert-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 10px;
}

.status-warning,
.status-error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 9px 0 0;
  font-size: 9.5px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.status-warning {
  color: var(--warning);
}

.status-error {
  color: var(--danger);
}

.failure-details {
  margin-top: 10px;
  padding: 9px 10px;
  border: 1px solid var(--warning-line);
  border-radius: 8px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 9px;
}

.failure-details summary {
  cursor: pointer;
  font-weight: 600;
}

.failure-details p {
  margin: 6px 0 0;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.status-actions {
  margin-top: 12px;
}

.status-note {
  margin: 14px 0 0;
  padding-top: 11px;
  border-top: 1px solid var(--line-soft);
  color: var(--text-4);
  font-size: 9px;
  line-height: 1.7;
}

.status-note a {
  color: var(--brand-strong);
  white-space: nowrap;
}

.notification-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 22px;
  padding-top: 17px;
  border-top: 1px solid var(--line);
}

.notification-footer span {
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.55;
}

.dialog-lead {
  margin: 0 0 14px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.target-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dialog-section {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface-2);
}

.dialog-section-head {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 11px;
}

.dialog-section-head > div {
  min-width: 0;
}

.form-section-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.dialog-section h3 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 620;
}

.dialog-section-head p {
  margin: 0;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.55;
}

.target-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.target-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.target-form :deep(.el-select) {
  width: 100%;
}

.switch-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-2);
}

.switch-field > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.switch-field b {
  color: var(--text-2);
  font-size: 10px;
  font-weight: 600;
}

.switch-field small {
  color: var(--text-4);
  font-size: 9px;
  line-height: 1.45;
}

.dialog-note {
  margin: 11px 0 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.65;
}

.token-guide {
  margin-bottom: 13px;
}

.token-guide p {
  margin: 0 0 8px;
  color: var(--text-2);
  font-size: 10.5px;
  line-height: 1.7;
}

.token-guide a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--brand-strong);
  font-size: 10.5px;
}

.token-form {
  margin-top: 15px;
}

.binding-command-wrap {
  display: flex;
  align-items: stretch;
  gap: 9px;
  margin: 13px 0;
}

.binding-command {
  flex: 1;
  min-width: 0;
  margin: 0;
  padding: 15px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  background: var(--code-bg);
  color: var(--text);
  font: 13px/1.65 var(--font-mono);
}

.binding-command-wrap .el-button {
  flex: none;
  height: auto;
}

.notifications :deep(.el-alert) {
  border-radius: 10px;
}

.notifications :deep(.el-alert__title) {
  line-height: 1.65;
}

@media (max-width: 1150px) {
  .setup-layout {
    grid-template-columns: 1fr;
  }

  .notification-status {
    margin-top: 2px;
  }
}

@media (max-width: 760px) {
  .notification-heading {
    flex-wrap: wrap;
  }

  .notification-heading > .el-tag {
    margin-left: 51px;
  }

  .setup-step {
    grid-template-columns: 26px minmax(0, 1fr);
    gap: 10px;
  }

  .step-number {
    width: 26px;
    height: 26px;
  }

  .identity-source {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .identity-source .el-button {
    width: 100%;
  }

  .target-badges {
    width: 100%;
    margin-left: 38px;
  }

  .notification-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .notification-footer .el-button {
    width: 100%;
  }

  .binding-command-wrap {
    flex-direction: column;
  }

  .binding-command-wrap .el-button {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .notifications {
    padding: 16px;
  }

  .notification-heading h2 {
    font-size: 15px;
  }

  .notification-heading > .el-tag {
    margin-left: 0;
  }

  .step-heading {
    align-items: flex-start;
  }

  .target-badges {
    margin-left: 0;
  }

  .inline-actions,
  .inline-actions .el-button {
    width: 100%;
  }

  .delivery-options {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  .delivery-options label {
    align-items: flex-start;
    flex-direction: column;
    width: 100%;
  }

  .delivery-options :deep(.el-input-number) {
    width: 100%;
  }

  .status-details .detail-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 3px;
  }

  .status-details .detail-row > b {
    text-align: left;
  }
}
</style>
