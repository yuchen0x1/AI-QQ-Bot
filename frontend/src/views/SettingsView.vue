<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">PLATFORM CONFIGURATION</div>
      <h1>系统设置</h1>
      <p>管理数据生命周期、告警通道、在线更新、登录安全与后台访问权限。所有配置均通过服务端接口持久化。</p>
    </div>
    <div class="heading-actions">
      <el-button @click="$router.push('/help')"><AppIcon name="book" :size="14" style="margin-right:5px" />操作文档</el-button>
      <el-button type="primary" :loading="refreshingAll" @click="refreshAll"><AppIcon name="refresh" :size="14" style="margin-right:5px" />重新载入</el-button>
    </div>
  </div>

  <div class="settings-layout">
    <aside class="settings-rail">
      <div class="rail-sticky">
        <div v-for="group in railGroups" :key="group.label" class="rail-group">
          <p class="rail-label">{{ group.label }}</p>
          <button
            v-for="item in group.items"
            :key="item.id"
            type="button"
            class="rail-item"
            :class="{ active: activeSection === item.id }"
            @click="goSection(item.id)"
          >
            <span class="rail-icon"><AppIcon :name="item.icon" :size="16" /></span>
            <span class="rail-copy"><b>{{ item.label }}</b><small>{{ item.desc }}</small></span>
          </button>
        </div>
        <div class="rail-note">
          <AppIcon name="shield" :size="15" />
          <span>敏感配置加密存储<br />访问操作写入审计日志</span>
        </div>
      </div>
    </aside>

    <div class="settings-content">
      <section id="lifecycle" data-settings-section class="settings-section surface">
        <div class="section-heading">
          <span class="section-icon"><AppIcon name="database" :size="17" /></span>
          <div><h2>数据与生命周期</h2><p>历史消息、系统日志、任务记录与调用数据的自动清理策略。</p></div>
          <el-tag :type="retentionDays === 0 ? 'info' : 'primary'" size="small">{{ retentionDays === 0 ? '永久保留' : `${retentionDays} 天` }}</el-tag>
        </div>
        <div class="settings-row">
          <div class="field-block">
            <label>数据保留周期</label>
            <p>超过该天数的消息、日志和任务记录将被每日清理任务自动删除。设为 0 表示永久保留。</p>
          </div>
          <div class="field-control">
            <el-input-number v-model="retentionDays" :min="0" :max="365" :disabled="!can('system:manage')" />
            <span class="field-unit">天</span>
            <el-button type="primary" :disabled="!can('system:manage')" :loading="savingRetention" @click="saveRetention">保存设置</el-button>
          </div>
        </div>
        <div class="cleanup-strip">
          <div>
            <span>清理任务</span>
            <b v-if="cleanupTask">{{ cleanupTask.enabled ? '已启用' : '已停用' }} · 每日 03:20</b>
            <b v-else>每日 03:20 自动执行</b>
          </div>
          <div>
            <span>上次结果</span>
            <b>{{ cleanupTask?.last_status || '等待首次执行' }}</b>
          </div>
          <div>
            <span>下次执行</span>
            <b>{{ cleanupTask?.next_run_at ? formatDate(cleanupTask.next_run_at) : '—' }}</b>
          </div>
          <div>
            <span>累计执行</span>
            <b>{{ cleanupTask?.total_runs ?? 0 }} 次</b>
          </div>
          <el-button text type="primary" @click="$router.push('/tasks')">管理清理任务<AppIcon name="arrow-right" :size="13" style="margin-left:4px" /></el-button>
        </div>
      </section>

      <section id="alerts" data-settings-section class="settings-section surface">
        <div class="section-heading">
          <span class="section-icon"><AppIcon name="bell" :size="17" /></span>
          <div><h2>告警通知</h2><p>机器人离线、关键接口异常时向飞书、钉钉、企业微信或自定义 Webhook 发送通知。</p></div>
          <el-tag :type="alertWebhookUrl.trim() ? 'success' : 'info'" size="small">{{ alertWebhookUrl.trim() ? '已配置' : '待配置' }}</el-tag>
        </div>
        <el-form label-position="top" class="settings-form">
          <div class="form-cols">
            <el-form-item label="通道类型">
              <el-select v-model="alertChannelType" :disabled="!can('system:manage')" style="width:100%">
                <el-option label="自动检测（根据 Webhook URL）" value="auto" />
                <el-option label="飞书 / Lark" value="feishu" />
                <el-option label="钉钉" value="dingtalk" />
                <el-option label="企业微信" value="wechat" />
                <el-option label="通用 Webhook（JSON）" value="custom" />
              </el-select>
            </el-form-item>
            <el-form-item label="Webhook URL">
              <el-input v-model="alertWebhookUrl" :disabled="!can('system:manage')" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
            </el-form-item>
          </div>
          <div class="inline-actions">
            <el-button type="primary" :disabled="!can('system:manage')" :loading="savingAlert" @click="saveAlertConfig">保存配置</el-button>
            <el-button :disabled="!can('system:manage')" :loading="testingAlert" @click="testAlertWebhook">发送测试通知</el-button>
            <span v-if="alertTestResult" class="test-result" :class="alertTestResult.ok ? 'ok' : 'bad'">
              <i></i>{{ alertTestResult.ok ? '最近测试成功' : '最近测试失败' }} · {{ alertTestResult.time }}
            </span>
          </div>
          <el-alert class="inline-note" type="info" :closable="false" show-icon title="同类告警在 3 分钟内只发送一次；Webhook 目标默认阻止私有与回环地址，避免管理端被用作 SSRF 跳板。" />
        </el-form>
      </section>

      <UpdatePanel v-if="can('system:view')" :can-manage="can('system:manage')" />

      <section id="security" data-settings-section class="settings-section surface">
        <div class="section-heading">
          <span class="section-icon"><AppIcon name="shield" :size="17" /></span>
          <div><h2>登录安全</h2><p>修改后台密码，并使用基于时间的一次性验证码保护管理员账户。</p></div>
        </div>
        <div class="security-grid">
          <div class="inner-card">
            <div class="inner-head"><div><h3>修改密码</h3><p>修改后其它会话的令牌会立即失效。</p></div><AppIcon name="key" :size="17" /></div>
            <el-form ref="passwordRef" :model="password" :rules="passwordRules" label-position="top">
              <el-form-item label="当前密码" prop="old_password"><el-input v-model="password.old_password" type="password" show-password autocomplete="current-password" /></el-form-item>
              <div class="form-cols">
                <el-form-item label="新密码" prop="new_password"><el-input v-model="password.new_password" type="password" show-password autocomplete="new-password" /></el-form-item>
                <el-form-item label="确认新密码" prop="confirm"><el-input v-model="password.confirm" type="password" show-password autocomplete="new-password" /></el-form-item>
              </div>
              <el-button type="primary" :loading="passwordLoading" @click="changePassword">更新密码</el-button>
            </el-form>
          </div>
          <div class="inner-card">
            <div class="inner-head">
              <div><h3>两步验证</h3><p>使用身份验证器生成 6 位动态验证码。</p></div>
              <el-tag :type="totpEnabled ? 'success' : 'info'" size="small">{{ totpEnabled ? '已启用' : '未启用' }}</el-tag>
            </div>
            <div v-if="!totpEnabled && !totpSetup" class="security-action">
              <span>启用后，每次登录都需要输入动态验证码。推荐所有管理员开启。</span>
              <el-button type="primary" @click="setupTotp">开始绑定</el-button>
            </div>
            <div v-if="totpSetup" class="totp-setup">
              <div class="totp-qr">
                <img v-if="totpQr" :src="totpQr" alt="TOTP 绑定二维码" />
                <span v-else>二维码生成中…</span>
              </div>
              <div class="totp-copy">
                <el-alert title="使用 Google Authenticator、Microsoft Authenticator 或 1Password 扫描二维码" type="info" :closable="false" show-icon />
                <el-form label-position="top" @submit.prevent="confirmTotp">
                  <el-form-item label="手动密钥">
                    <el-input :model-value="totpSetup.secret" readonly><template #append><el-button @click="copyText(totpSetup.secret)">复制</el-button></template></el-input>
                  </el-form-item>
                  <el-form-item label="验证码"><el-input v-model="totpCode" maxlength="6" inputmode="numeric" placeholder="输入 6 位验证码" /></el-form-item>
                  <div class="inline-actions"><el-button @click="cancelTotpSetup">取消</el-button><el-button type="primary" :loading="totpLoading" @click="confirmTotp">确认并启用</el-button></div>
                </el-form>
              </div>
            </div>
            <div v-if="totpEnabled" class="security-action">
              <span>动态验证码已启用。关闭前需要验证当前密码和验证码。</span>
              <el-button type="danger" plain @click="disableTotpDialog = true">关闭两步验证</el-button>
            </div>
            <el-alert class="inline-note" type="info" :closable="false" show-icon title="AppSecret、API Key 等敏感配置仅加密存储，查询接口不会返回完整密钥。" />
          </div>
        </div>
      </section>

      <section id="sessions" data-settings-section class="settings-section surface">
        <div class="section-heading">
          <span class="section-icon"><AppIcon name="monitor" :size="17" /></span>
          <div><h2>活跃会话</h2><p>查看当前登录设备与来源 IP，发现异常时可立即撤销。</p></div>
          <div class="section-actions">
            <el-button size="small" :loading="sessionsLoading" @click="loadSessions()">刷新</el-button>
            <el-button size="small" type="warning" plain @click="revokeOtherSessions">撤销其它会话</el-button>
          </div>
        </div>
        <div class="table-scroll">
          <el-table :data="sessions" stripe empty-text="暂无其它活跃会话">
            <el-table-column label="设备 / 浏览器" min-width="300">
              <template #default="scope">
                <div class="session-device">
                  <b>{{ shortAgent(scope.row.user_agent) }}</b>
                  <small>{{ scope.row.ip || '未知 IP' }} · 最近使用 {{ formatDate(scope.row.last_seen_at) }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="登录时间" width="180"><template #default="scope">{{ formatDate(scope.row.created_at) }}</template></el-table-column>
            <el-table-column label="状态" width="110"><template #default="scope"><el-tag :type="scope.row.current ? 'success' : 'info'" size="small">{{ scope.row.current ? '当前会话' : '活跃' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="90" align="right"><template #default="scope"><el-button v-if="!scope.row.current" link type="danger" @click="revokeSession(scope.row)">撤销</el-button><span v-else class="muted">—</span></template></el-table-column>
          </el-table>
        </div>
      </section>

      <section v-if="can('user:manage')" id="users" data-settings-section class="settings-section surface">
        <div class="section-heading">
          <span class="section-icon"><AppIcon name="users" :size="17" /></span>
          <div><h2>后台用户</h2><p>通过 RBAC 角色控制后台访问范围与可执行操作。</p></div>
          <el-button type="primary" size="small" @click="openUserDialog"><AppIcon name="plus" :size="13" style="margin-right:4px" />添加用户</el-button>
        </div>
        <div class="table-scroll">
          <el-table :data="users" v-loading="userLoading" stripe empty-text="还没有后台用户">
            <el-table-column prop="username" label="用户名" min-width="130" />
            <el-table-column prop="display_name" label="显示名称" min-width="130" />
            <el-table-column label="角色" width="140"><template #default="scope"><el-tag size="small" type="primary">{{ scope.row.role?.name || '—' }}</el-tag></template></el-table-column>
            <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.is_active ? 'success' : 'info'" size="small">{{ scope.row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
            <el-table-column label="最近登录" width="180"><template #default="scope">{{ formatDate(scope.row.last_login_at) }}</template></el-table-column>
            <el-table-column label="操作" width="100" align="right"><template #default="scope"><el-button link :type="scope.row.is_active ? 'warning' : 'success'" @click="toggleUser(scope.row)">{{ scope.row.is_active ? '停用' : '启用' }}</el-button></template></el-table-column>
          </el-table>
        </div>
      </section>

      <section v-if="can('audit:view')" id="audit" data-settings-section class="settings-section surface">
        <div class="section-heading">
          <span class="section-icon"><AppIcon name="logs" :size="17" /></span>
          <div><h2>操作审计</h2><p>记录后台用户的关键操作，支持筛选与脱敏导出。</p></div>
          <div class="section-actions">
            <el-button size="small" :loading="auditLoading" @click="loadAudit()">刷新</el-button>
            <el-button size="small" :loading="auditExporting" @click="exportAudit">导出 CSV</el-button>
          </div>
        </div>
        <div class="audit-filters">
          <el-input v-model="auditFilters.username" clearable placeholder="用户名" @keyup.enter="loadAudit(1)" />
          <el-input v-model="auditFilters.action" clearable placeholder="操作类型" @keyup.enter="loadAudit(1)" />
          <el-input v-model="auditFilters.ip" clearable placeholder="来源 IP" @keyup.enter="loadAudit(1)" />
          <el-button type="primary" @click="loadAudit(1)">筛选</el-button>
        </div>
        <div class="table-scroll">
          <el-table :data="audits" v-loading="auditLoading" stripe empty-text="没有匹配的审计记录">
            <el-table-column label="时间" width="180"><template #default="scope">{{ formatDate(scope.row.created_at) }}</template></el-table-column>
            <el-table-column prop="username" label="用户" width="120" />
            <el-table-column prop="action" label="操作" min-width="170" />
            <el-table-column prop="target" label="目标" min-width="150" show-overflow-tooltip />
            <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip />
            <el-table-column prop="ip" label="来源 IP" width="130" />
          </el-table>
        </div>
        <div class="pagination-wrap">
          <span>共 {{ auditTotal }} 条记录</span>
          <el-pagination v-model:current-page="auditPage" :page-size="20" :total="auditTotal" layout="prev,pager,next" @current-change="loadAudit" />
        </div>
      </section>
    </div>
  </div>

  <el-dialog v-model="disableTotpDialog" title="关闭两步验证" width="min(420px, calc(100vw - 28px))">
    <el-form label-position="top">
      <el-form-item label="当前密码"><el-input v-model="disableForm.password" type="password" show-password /></el-form-item>
      <el-form-item label="动态验证码"><el-input v-model="disableForm.code" maxlength="6" inputmode="numeric" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="disableTotpDialog = false">取消</el-button><el-button type="danger" :loading="totpLoading" @click="disableTotp">确认关闭</el-button></template>
  </el-dialog>

  <el-dialog v-model="userDialog" title="添加后台用户" width="min(480px, calc(100vw - 28px))">
    <el-form ref="userRef" :model="newUser" :rules="userRules" label-position="top">
      <div class="form-cols">
        <el-form-item label="用户名" prop="username"><el-input v-model="newUser.username" autocomplete="off" /></el-form-item>
        <el-form-item label="初始密码" prop="password"><el-input v-model="newUser.password" type="password" show-password autocomplete="new-password" /></el-form-item>
      </div>
      <el-form-item label="显示名称"><el-input v-model="newUser.display_name" /></el-form-item>
      <el-form-item label="邮箱"><el-input v-model="newUser.email" /></el-form-item>
      <el-form-item label="角色" prop="role_id">
        <el-select v-model="newUser.role_id" style="width:100%"><el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" /></el-select>
      </el-form-item>
    </el-form>
    <template #footer><el-button @click="userDialog = false">取消</el-button><el-button type="primary" :loading="userSaving" @click="createUser">创建用户</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import QRCode from 'qrcode'
import AppIcon from '../components/AppIcon.vue'
import UpdatePanel from '../components/UpdatePanel.vue'
import { api } from '../api'

const userPermissions = ref<string[]>([])
const refreshingAll = ref(false)
const activeSection = ref('lifecycle')
let observer: IntersectionObserver | undefined

const railGroups = [
  {
    label: '平台配置',
    items: [
      { id: 'lifecycle', label: '数据与生命周期', desc: '保留周期与清理', icon: 'database' },
      { id: 'alerts', label: '告警通知', desc: 'Webhook 与通道', icon: 'bell' },
      { id: 'updates', label: '在线更新', desc: '版本与升级进度', icon: 'zap' },
    ],
  },
  {
    label: '账户安全',
    items: [
      { id: 'security', label: '登录安全', desc: '密码与两步验证', icon: 'shield' },
      { id: 'sessions', label: '活跃会话', desc: '设备与撤销', icon: 'monitor' },
    ],
  },
  {
    label: '访问控制',
    items: [
      { id: 'users', label: '后台用户', desc: '角色与启用状态', icon: 'users' },
      { id: 'audit', label: '操作审计', desc: '筛选与导出', icon: 'logs' },
    ],
  },
]

function can(permission: string) {
  return userPermissions.value.includes('*') || userPermissions.value.includes(permission)
}

function goSection(id: string) {
  activeSection.value = id
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const retentionDays = ref(30)
const savingRetention = ref(false)
const cleanupTask = ref<any>(null)

const alertWebhookUrl = ref('')
const alertChannelType = ref('auto')
const savingAlert = ref(false)
const testingAlert = ref(false)
const alertTestResult = ref<{ ok: boolean; time: string } | null>(null)

const passwordRef = ref<any>()
const passwordLoading = ref(false)
const password = reactive({ old_password: '', new_password: '', confirm: '' })
const passwordRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [{ required: true, min: 8, message: '新密码至少 8 位', trigger: 'blur' }],
  confirm: [{ validator: (_: any, value: string, callback: any) => value === password.new_password ? callback() : callback(new Error('两次密码不一致')), trigger: 'blur' }],
}

const totpEnabled = ref(false)
const totpSetup = ref<any>(null)
const totpQr = ref('')
const totpCode = ref('')
const totpLoading = ref(false)
const disableTotpDialog = ref(false)
const disableForm = reactive({ password: '', code: '' })

const sessions = ref<any[]>([])
const sessionsLoading = ref(false)

const users = ref<any[]>([])
const roles = ref<any[]>([])
const userLoading = ref(false)
const userSaving = ref(false)
const userDialog = ref(false)
const userRef = ref<any>()
const newUser = reactive<any>({ username: '', password: '', display_name: '', email: '', role_id: null })
const userRules = {
  username: [{ required: true, min: 3, message: '用户名至少 3 位', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: '密码至少 8 位', trigger: 'blur' }],
  role_id: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

const audits = ref<any[]>([])
const auditLoading = ref(false)
const auditExporting = ref(false)
const auditPage = ref(1)
const auditTotal = ref(0)
const auditFilters = reactive({ username: '', action: '', ip: '' })

function unwrapSetting(value: any) {
  return value && typeof value === 'object' && 'value' in value ? value.value : value
}

async function loadRetention() {
  try {
    const { data } = await api.get('/system/settings')
    const rows = Array.isArray(data) ? data : []
    const retention = rows.find((item: any) => item.key === 'data_retention_days')
    if (retention) retentionDays.value = Number(unwrapSetting(retention.value))
    const url = rows.find((item: any) => item.key === 'alert_webhook_url')
    if (url) alertWebhookUrl.value = String(unwrapSetting(url.value) || '')
    const channel = rows.find((item: any) => item.key === 'alert_channel_type')
    if (channel) alertChannelType.value = String(unwrapSetting(channel.value) || 'auto')
  } catch {
    /* permission handled by disabled controls */
  }
}

async function loadCleanupTask() {
  if (!can('task:view')) return
  try {
    const { data } = await api.get('/tasks')
    const rows = Array.isArray(data) ? data : (data.items || [])
    cleanupTask.value = rows.find((task: any) => String(task.name || '').includes('清理')) || null
  } catch {
    cleanupTask.value = null
  }
}

async function saveRetention() {
  savingRetention.value = true
  try {
    await api.put('/system/settings/data_retention_days', { value: retentionDays.value })
    ElMessage.success('数据生命周期配置已更新')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    savingRetention.value = false
  }
}

async function saveAlertConfig() {
  savingAlert.value = true
  try {
    await Promise.all([
      api.put('/system/settings/alert_webhook_url', { value: alertWebhookUrl.value.trim() }),
      api.put('/system/settings/alert_channel_type', { value: alertChannelType.value }),
    ])
    ElMessage.success('告警通道配置已保存')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '保存告警配置失败')
  } finally {
    savingAlert.value = false
  }
}

async function testAlertWebhook() {
  if (!alertWebhookUrl.value.trim()) {
    ElMessage.warning('请先填写 Webhook URL')
    return
  }
  testingAlert.value = true
  try {
    const { data } = await api.post('/system/alert/test', {
      webhook_url: alertWebhookUrl.value.trim(),
      channel_type: alertChannelType.value,
    })
    alertTestResult.value = { ok: Boolean(data.ok), time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }
    if (data.ok) ElMessage.success('测试告警推送成功，请在对应应用中查收')
    else ElMessage.error(data.message || '推送失败')
  } catch (error: any) {
    alertTestResult.value = { ok: false, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }
    ElMessage.error(error.response?.data?.detail || '测试推送失败')
  } finally {
    testingAlert.value = false
  }
}

async function changePassword() {
  await passwordRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    passwordLoading.value = true
    try {
      const { data } = await api.post('/auth/password', {
        old_password: password.old_password,
        new_password: password.new_password,
      })
      ElMessage.success(data.detail || '密码已修改')
      Object.assign(password, { old_password: '', new_password: '', confirm: '' })
    } catch (error: any) {
      ElMessage.error(error.response?.data?.detail || '修改密码失败')
    } finally {
      passwordLoading.value = false
    }
  })
}

async function loadUsers() {
  if (!can('user:manage')) return
  userLoading.value = true
  try {
    const [userResponse, roleResponse] = await Promise.all([
      api.get('/users', { params: { page: 1, page_size: 100 } }),
      api.get('/roles'),
    ])
    users.value = userResponse.data.items || []
    roles.value = roleResponse.data || []
  } finally {
    userLoading.value = false
  }
}

async function loadTotp() {
  try {
    const { data } = await api.get('/auth/2fa')
    totpEnabled.value = Boolean(data.enabled)
  } catch {
    /* optional */
  }
}

async function setupTotp() {
  totpLoading.value = true
  try {
    const { data } = await api.post('/auth/2fa/setup')
    totpSetup.value = data
    totpQr.value = await QRCode.toDataURL(data.provisioning_uri, { width: 190, margin: 1 })
  } finally {
    totpLoading.value = false
  }
}

function cancelTotpSetup() {
  totpSetup.value = null
  totpQr.value = ''
  totpCode.value = ''
}

async function confirmTotp() {
  if (!/^\d{6}$/.test(totpCode.value)) {
    ElMessage.warning('请输入 6 位验证码')
    return
  }
  totpLoading.value = true
  try {
    await api.post('/auth/2fa/confirm', { code: totpCode.value })
    ElMessage.success('两步验证已启用')
    totpEnabled.value = true
    cancelTotpSetup()
    await loadSessions()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '验证码校验失败')
  } finally {
    totpLoading.value = false
  }
}

async function disableTotp() {
  if (!disableForm.password || !/^\d{6}$/.test(disableForm.code)) {
    ElMessage.warning('请输入密码和 6 位验证码')
    return
  }
  totpLoading.value = true
  try {
    await api.post('/auth/2fa/disable', disableForm)
    ElMessage.success('两步验证已关闭，请重新登录')
    location.href = '/login'
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '关闭失败')
  } finally {
    totpLoading.value = false
  }
}

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const { data } = await api.get('/auth/sessions')
    sessions.value = data || []
  } finally {
    sessionsLoading.value = false
  }
}

async function revokeSession(row: any) {
  try {
    await ElMessageBox.confirm(`确定撤销来自 ${row.ip || '未知 IP'} 的会话吗？`, '撤销会话', { type: 'warning' })
    await api.delete(`/auth/sessions/${row.id}`)
    ElMessage.success('会话已撤销')
    await loadSessions()
  } catch { /* cancelled */ }
}

async function revokeOtherSessions() {
  try {
    await ElMessageBox.confirm('其它设备将立即退出登录，是否继续？', '撤销其它会话', { type: 'warning' })
    await api.post('/auth/sessions/revoke-others')
    ElMessage.success('其它会话已撤销')
    await loadSessions()
  } catch { /* cancelled */ }
}

function copyText(value: string) {
  navigator.clipboard?.writeText(value)
  ElMessage.success('密钥已复制')
}

function auditParams() {
  return {
    page: auditPage.value,
    page_size: 20,
    ...Object.fromEntries(Object.entries(auditFilters).filter(([, value]) => value)),
  }
}

async function loadAudit(page?: number) {
  if (!can('audit:view')) return
  if (page) auditPage.value = page
  auditLoading.value = true
  try {
    const { data } = await api.get('/audit-logs', { params: auditParams() })
    audits.value = data.items || []
    auditTotal.value = data.total || 0
  } finally {
    auditLoading.value = false
  }
}

async function exportAudit() {
  auditExporting.value = true
  try {
    const response = await api.get('/audit-logs/export', { params: auditParams(), responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = `qbot-audit-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('审计记录已导出')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '导出失败')
  } finally {
    auditExporting.value = false
  }
}

function openUserDialog() {
  Object.assign(newUser, { username: '', password: '', display_name: '', email: '', role_id: roles.value[0]?.id ?? null })
  userDialog.value = true
}

async function createUser() {
  await userRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    userSaving.value = true
    try {
      const { data } = await api.post('/users', newUser)
      ElMessage.success(`用户 ${data.username} 已创建`)
      userDialog.value = false
      await loadUsers()
    } catch (error: any) {
      ElMessage.error(error.response?.data?.detail || '创建用户失败')
    } finally {
      userSaving.value = false
    }
  })
}

async function toggleUser(user: any) {
  try {
    const { data } = await api.put(`/users/${user.id}`, { is_active: !user.is_active })
    ElMessage.success(`${data.username} 已${data.is_active ? '启用' : '停用'}`)
    await loadUsers()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '更新失败')
  }
}

function shortAgent(value?: string) {
  if (!value) return '未知设备'
  const browser = value.match(/(Chrome|Firefox|Safari|Edg|AaBrowser)\/[\d.]+/i)?.[0] || value.slice(0, 40)
  const system = /Windows NT 10/.test(value) ? 'Windows' : /Mac OS X/.test(value) ? 'macOS' : /Linux/.test(value) ? 'Linux' : /Android/.test(value) ? 'Android' : /iPhone|iPad/.test(value) ? 'iOS' : '未知系统'
  return `${system} · ${browser}`
}

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

async function refreshAll() {
  refreshingAll.value = true
  try {
    await Promise.all([
      loadRetention(),
      loadCleanupTask(),
      loadSessions(),
      loadTotp(),
      loadUsers(),
      loadAudit(),
    ])
    ElMessage.success('设置数据已重新载入')
  } finally {
    refreshingAll.value = false
  }
}

async function initSections() {
  await nextTick()
  observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
    if (visible[0]?.target.id) activeSection.value = visible[0].target.id
  }, { rootMargin: '-90px 0px -62% 0px', threshold: 0 })
  document.querySelectorAll('[data-settings-section]').forEach((section) => observer?.observe(section))
}

onMounted(async () => {
  try {
    const { data } = await api.get('/auth/me')
    userPermissions.value = data.permissions || []
  } catch { /* route guard handles auth */ }
  await Promise.all([loadRetention(), loadCleanupTask(), loadTotp(), loadSessions()])
  if (can('user:manage')) await loadUsers()
  if (can('audit:view')) await loadAudit()
  await initSections()
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.settings-layout {
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}
.settings-rail {
  position: relative;
}
.rail-sticky {
  position: sticky;
  top: calc(var(--topbar-height) + 18px);
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rail-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.rail-label {
  margin: 0 0 5px;
  padding: 0 10px;
  color: var(--text-4);
  font: 650 9px var(--font-sans);
  letter-spacing: 0.13em;
  text-transform: uppercase;
}
.rail-item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: var(--text-3);
  text-align: left;
  cursor: pointer;
  transition: color var(--duration-fast), background var(--duration-fast), border-color var(--duration-fast);
}
.rail-item:hover {
  color: var(--text);
  background: var(--surface-2);
}
.rail-item.active {
  color: var(--text);
  border-color: var(--brand-line);
  background: linear-gradient(90deg, var(--brand-soft), transparent);
}
.rail-icon {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-2);
  color: var(--text-4);
}
.rail-item.active .rail-icon {
  color: var(--brand-strong);
  border-color: var(--brand-line);
  background: var(--brand-soft);
}
.rail-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.rail-copy b {
  font-size: 11px;
  font-weight: 560;
}
.rail-copy small {
  color: var(--text-4);
  font-size: 9px;
}
.rail-note {
  display: flex;
  gap: 9px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-2);
  color: var(--text-4);
  font-size: 9px;
  line-height: 1.65;
}
.rail-note .app-icon {
  color: var(--success);
  flex: none;
}
.settings-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.settings-section {
  scroll-margin-top: calc(var(--topbar-height) + 22px);
  padding: 22px;
}
.section-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 18px;
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
.section-heading > div {
  flex: 1;
  min-width: 0;
}
.section-heading h2 {
  margin: 0 0 4px;
  color: var(--text);
  font-size: 14px;
  font-weight: 640;
  letter-spacing: -0.015em;
}
.section-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.6;
}
.section-actions {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  flex: none;
}
.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 22px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface-2);
}
.field-block {
  min-width: 0;
}
.field-block label {
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
}
.field-block p {
  max-width: 560px;
  margin: 5px 0 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.65;
}
.field-control {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.field-control .el-input-number {
  width: 130px;
}
.field-unit {
  color: var(--text-4);
  font-size: 10px;
}
.cleanup-strip {
  display: flex;
  align-items: center;
  gap: 22px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding: 13px 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-inset);
}
.cleanup-strip > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.cleanup-strip span {
  color: var(--text-4);
  font-size: 9px;
}
.cleanup-strip b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 550;
}
.cleanup-strip .el-button {
  margin-left: auto;
}
.settings-form {
  max-width: 100%;
}
.form-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}
.inline-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.test-result {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--success);
  font-size: 10px;
}
.test-result.bad {
  color: var(--danger);
}
.test-result i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.inline-note {
  margin-top: 14px;
}
.security-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}
.inner-card {
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-2);
  min-width: 0;
}
.inner-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 15px;
}
.inner-head h3 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 12px;
  font-weight: 620;
}
.inner-head p {
  margin: 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.55;
}
.inner-head > .app-icon {
  color: var(--text-4);
}
.security-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}
.totp-setup {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.totp-qr {
  display: grid;
  place-items: center;
  min-height: 190px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  color: #5a6577;
  font-size: 10px;
}
.totp-qr img {
  width: 172px;
  height: 172px;
}
.totp-copy {
  min-width: 0;
}
.table-scroll {
  overflow-x: auto;
}
.session-device {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.session-device b {
  overflow: hidden;
  color: var(--text-2);
  font-size: 11px;
  font-weight: 550;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-device small {
  color: var(--text-4);
  font-size: 9.5px;
}
.audit-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.audit-filters .el-input {
  width: 180px;
}
.pagination-wrap {
  margin: 0 -22px -22px;
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}
@media (max-width: 1180px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
  .settings-rail {
    display: none;
  }
  .security-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 720px) {
  .settings-row {
    align-items: flex-start;
    flex-direction: column;
  }
  .field-control {
    width: 100%;
    flex-wrap: wrap;
  }
  .form-cols {
    grid-template-columns: 1fr;
  }
  .totp-setup {
    grid-template-columns: 1fr;
  }
  .cleanup-strip .el-button {
    margin-left: 0;
  }
  .audit-filters .el-input {
    width: 100%;
  }
  .section-heading {
    flex-wrap: wrap;
  }
}
</style>
