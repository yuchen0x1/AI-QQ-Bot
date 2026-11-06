<template>
  <ResourceView ref="tableRef" :config="config">
    <template #panel>
      <section class="gh-bind surface" v-loading="statusLoading">
        <div class="gh-left">
          <div class="gh-mark" :class="{ on: status?.connected }">
            <el-icon><Connection /></el-icon>
          </div>
          <div class="gh-copy">
            <div class="eyebrow">GITHUB IDENTITY</div>
            <strong v-if="status?.connected">已绑定 @{{ status.account?.login }}</strong>
            <strong v-else-if="status?.configured">尚未绑定 GitHub 账号</strong>
            <strong v-else>GitHub OAuth 尚未配置</strong>
            <p v-if="status?.connected">
              授权范围 {{ scopeText }}<template v-if="status.account?.bound_at"> · 绑定于 {{ formatDate(status.account.bound_at) }}</template> ·
              导入的仓库按你的账号隔离，Token 加密存储且不会回显
            </p>
            <p v-else-if="status?.configured">绑定后可列出你的全部仓库（含私有仓库）并批量导入，无需逐个粘贴 Token。</p>
            <p v-else>{{ status?.message || '正在读取 GitHub 授权状态…' }}</p>
          </div>
        </div>
        <div class="gh-actions">
          <el-tag v-if="status?.connected" type="success" effect="dark" size="small">已授权</el-tag>
          <el-tag v-else-if="status?.configured" type="info" effect="dark" size="small">未授权</el-tag>
          <el-tag v-else type="warning" effect="dark" size="small">待配置</el-tag>
          <el-button v-if="status?.can_configure" size="small" @click="openAppDialog">
            {{ status?.configured ? 'OAuth 配置' : '配置 OAuth App' }}
          </el-button>
          <el-button v-if="status?.configured && !status?.connected" size="small" type="primary" :loading="binding" @click="startBind">
            绑定 GitHub 账号
          </el-button>
          <template v-if="status?.connected">
            <el-button size="small" type="primary" :icon="Download" @click="openImport">从 GitHub 导入</el-button>
            <el-button size="small" @click="unbind">解除绑定</el-button>
          </template>
        </div>
      </section>
    </template>
  </ResourceView>

  <el-dialog v-model="importVisible" title="从 GitHub 导入仓库" width="min(780px, calc(100vw - 28px))" destroy-on-close>
    <div class="import-toolbar">
      <el-input v-model="keyword" placeholder="按仓库名 / 描述过滤" clearable :prefix-icon="Search" style="width:260px" />
      <el-button :icon="Refresh" :loading="reposLoading" @click="loadGithubRepos()">刷新</el-button>
      <span class="muted">可导入 {{ importable.length }} 个 · 已选 {{ selected.length }} 个</span>
    </div>
    <el-table
      v-loading="reposLoading"
      :data="filtered"
      height="360"
      row-key="full_name"
      empty-text="没有可导入的仓库（已监控的仓库不会重复出现）"
      @selection-change="onSelection"
    >
      <el-table-column type="selection" width="44" :selectable="(row: any) => !row.monitored" />
      <el-table-column label="仓库" min-width="240">
        <template #default="{ row }">
          <div class="repo-cell">
            <b>{{ row.full_name }}</b>
            <small>{{ row.description || '暂无描述' }}</small>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="语言" prop="language" width="96" />
      <el-table-column label="Stars" prop="stars" width="78" />
      <el-table-column label="状态" width="92">
        <template #default="{ row }">
          <el-tag size="small" effect="dark" :type="row.monitored ? 'info' : row.private ? 'warning' : 'success'">
            {{ row.monitored ? '已监控' : row.private ? '私有' : '公开' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
    <div class="import-foot">
      <span class="muted">轮询间隔</span>
      <el-input-number v-model="importInterval" :min="60" :max="86400" :step="60" controls-position="right" style="width:130px" />
      <span class="muted">秒</span>
      <el-switch v-model="importPrerelease" />
      <span class="muted">接收预发布版本</span>
      <span class="grow" />
      <span class="muted">历史版本会标记为已通知，不会刷屏</span>
    </div>
    <template #footer>
      <el-button @click="importVisible = false">取消</el-button>
      <el-button type="primary" :loading="importing" :disabled="!selected.length" @click="doImport">
        导入选中的 {{ selected.length }} 个仓库
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="appVisible" title="GitHub OAuth App 配置" width="min(660px, calc(100vw - 28px))">
    <el-alert type="info" :closable="false" show-icon>
      <template #title>在 GitHub 上创建 OAuth App 后填入凭据</template>
      <ol class="steps">
        <li v-for="step in appInfo?.steps || []" :key="step">{{ step }}</li>
      </ol>
    </el-alert>
    <div class="callback-row">
      <span class="muted">Authorization callback URL</span>
      <code>{{ appInfo?.redirect_uri || status?.redirect_uri }}</code>
      <el-button link type="primary" @click="copyCallback">复制</el-button>
    </div>
    <el-form label-position="top" class="app-form">
      <el-form-item label="Client ID">
        <el-input v-model="appForm.client_id" :placeholder="appInfo?.client_id ? `当前：${appInfo.client_id}（重新填写可覆盖）` : 'Iv1.xxxxxxxxxxxx'" />
      </el-form-item>
      <el-form-item label="Client Secret">
        <el-input
          v-model="appForm.client_secret"
          type="password"
          show-password
          :placeholder="appInfo?.has_secret ? '留空保持现有密钥不变' : 'GitHub 只显示一次，请立即填入'"
        />
      </el-form-item>
      <el-form-item label="授权范围（Scopes）">
        <el-input v-model="appForm.scopes" placeholder="read:user repo" />
        <div class="muted hint">仅监控公开仓库可改为 public_repo；含私有仓库需保留 repo。</div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="appVisible = false">取消</el-button>
      <el-button type="primary" :loading="savingApp" @click="saveApp">保存配置</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Download, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'
import ResourceView from '../components/ResourceView.vue'

const route = useRoute()
const router = useRouter()
const tableRef = ref<any>()
const statusLoading = ref(false)
const binding = ref(false)
const status = ref<any>(null)

const importVisible = ref(false)
const reposLoading = ref(false)
const importing = ref(false)
const githubRepos = ref<any[]>([])
const selected = ref<any[]>([])
const keyword = ref('')
const importInterval = ref(900)
const importPrerelease = ref(false)

const appVisible = ref(false)
const appInfo = ref<any>(null)
const savingApp = ref(false)
const appForm = reactive({ client_id: '', client_secret: '', scopes: '' })

const scopeText = computed(() => (status.value?.account?.scopes || status.value?.scopes || '—').replace(/,/g, ' '))
const importable = computed(() => githubRepos.value.filter((item) => !item.monitored))
const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return githubRepos.value
  return githubRepos.value.filter(
    (item) => item.full_name.toLowerCase().includes(text) || (item.description || '').toLowerCase().includes(text),
  )
})

const config = {
  kicker: 'RELEASE TRACKER',
  title: 'GitHub 仓库监控',
  description: '跟踪 Release 与版本更新，支持 Webhook 实时事件和定时轮询；绑定 GitHub 账号后可一键导入你的仓库',
  endpoint: '/github/repos',
  itemName: '仓库',
  nameKey: 'full_name',
  paged: false,
  actionWidth: 190,
  columns: [
    { key: 'full_name', label: '仓库', width: 180 },
    { key: 'description', label: '项目描述', width: 220 },
    { key: 'language', label: '语言', width: 90 },
    { key: 'stars', label: 'Stars', width: 80 },
    { key: 'last_release_tag', label: '最新版本', width: 115 },
    { key: 'last_checked_at', label: '上次检查', type: 'date', width: 160 },
    { key: 'owner_username', label: '添加者', width: 100 },
    { key: 'monitor_enabled', label: '监控状态', type: 'bool', width: 95 },
  ],
  createLabel: '添加仓库',
  extraCreateLabel: '从 GitHub 导入',
  extraCreateIcon: 'Download',
  onExtraCreate: () => openImport(),
  createFields: [
    { key: 'url', label: 'GitHub 仓库地址', placeholder: 'https://github.com/owner/repo' },
    { key: 'owner', label: '用户名 / Owner', placeholder: '与仓库名一起填写' },
    { key: 'name', label: '仓库名', placeholder: '与用户名一起填写' },
    { key: 'token', label: 'GitHub Token（可选）', type: 'password', placeholder: '访问私有仓库或提高限额' },
    { key: 'webhook_secret', label: 'Webhook Secret（可选）', type: 'password' },
    { key: 'poll_interval_seconds', label: '轮询间隔（秒）', type: 'number', default: 900, min: 60 },
    { key: 'monitor_enabled', label: '启用监控', type: 'switch', default: true },
    { key: 'notify_prerelease', label: '接收预发布版本', type: 'switch', default: false },
  ],
  editFields: [
    { key: 'token', label: 'GitHub Token', type: 'password', placeholder: '留空保持不变' },
    { key: 'webhook_secret', label: 'Webhook Secret', type: 'password', placeholder: '留空保持不变' },
    { key: 'poll_interval_seconds', label: '轮询间隔（秒）', type: 'number', min: 60 },
    { key: 'monitor_enabled', label: '启用监控', type: 'switch' },
    { key: 'notify_prerelease', label: '接收预发布版本', type: 'switch' },
  ],
  actions: [
    { label: '检查更新', suffix: 'check', method: 'POST', success: (d: any) => d.message || '检查完成' },
    { label: 'Release', type: 'info', handler: (r: any) => window.open(`https://github.com/${r.full_name}/releases`, '_blank', 'noopener') },
  ],
  deletePath: '/github/repos',
  secondaryAction: {
    label: '检查全部',
    path: '/github/repos/check-all',
    method: 'POST',
    success: (d: any) => `检查完成，共处理 ${Array.isArray(d) ? d.length : 0} 个仓库`,
  },
}

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

async function loadStatus() {
  statusLoading.value = true
  try {
    const { data } = await api.get('/github/oauth/status')
    status.value = data
  } finally {
    statusLoading.value = false
  }
}

function startBind() {
  binding.value = true
  const next = route.fullPath || '/github'
  window.location.href = `/api/github/oauth/start?next=${encodeURIComponent(next)}`
}

async function unbind() {
  try {
    await ElMessageBox.confirm('解除绑定后，已监控的仓库仍会保留，但私有仓库将无法再通过你的授权读取。确定继续？', '解除 GitHub 绑定', {
      type: 'warning',
    })
  } catch {
    return
  }
  await api.post('/github/oauth/disconnect')
  ElMessage.success('已解除 GitHub 绑定')
  await loadStatus()
}

async function openImport() {
  if (!status.value?.connected) {
    ElMessage.warning(status.value?.configured ? '请先绑定 GitHub 账号' : '请先让管理员配置 GitHub OAuth App')
    if (status.value?.can_configure && !status.value?.configured) await openAppDialog()
    return
  }
  importVisible.value = true
  await loadGithubRepos()
}

async function loadGithubRepos() {
  reposLoading.value = true
  try {
    const { data } = await api.get('/github/oauth/repos')
    githubRepos.value = data.items || []
  } finally {
    reposLoading.value = false
  }
}

function onSelection(rows: any[]) {
  selected.value = rows
}

async function doImport() {
  if (!selected.value.length) return
  importing.value = true
  try {
    const { data } = await api.post('/github/oauth/import', {
      full_names: selected.value.map((item) => item.full_name),
      poll_interval_seconds: importInterval.value,
      notify_prerelease: importPrerelease.value,
    })
    const imported = data.imported?.length || 0
    const skipped = data.skipped?.length || 0
    const failed = data.failed || []
    if (imported) ElMessage.success(`已导入 ${imported} 个仓库，历史版本已标记为已通知`)
    else if (skipped) ElMessage.info('所选仓库都已在监控列表中')
    if (failed.length) ElMessage.warning(`${failed.length} 个仓库导入失败：${failed[0].full_name}（${failed[0].error}）`)
    importVisible.value = false
    await Promise.all([tableRef.value?.load(), loadGithubRepos()])
  } finally {
    importing.value = false
  }
}

async function openAppDialog() {
  const { data } = await api.get('/github/oauth/app')
  appInfo.value = data
  appForm.client_id = ''
  appForm.client_secret = ''
  appForm.scopes = data.scopes || 'read:user repo'
  appVisible.value = true
}

async function saveApp() {
  if (!appForm.client_id.trim() && !appInfo.value?.configured) {
    ElMessage.warning('请填写 Client ID')
    return
  }
  savingApp.value = true
  try {
    await api.put('/github/oauth/app', {
      client_id: appForm.client_id.trim(),
      client_secret: appForm.client_secret.trim() || undefined,
      scopes: appForm.scopes.trim() || undefined,
    })
    ElMessage.success('OAuth App 配置已保存，现在可以绑定 GitHub 账号了')
    appVisible.value = false
    await loadStatus()
  } finally {
    savingApp.value = false
  }
}

async function copyCallback() {
  const value = appInfo.value?.redirect_uri || status.value?.redirect_uri || ''
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success('回调地址已复制')
  } catch {
    ElMessage.warning(`请手动复制：${value}`)
  }
}

onMounted(async () => {
  const result = route.query.github
  if (result === 'connected') {
    ElMessage.success(`GitHub 账号 @${route.query.login || ''} 绑定成功`)
    router.replace({ path: route.path })
  } else if (result === 'error') {
    ElMessage.error(String(route.query.reason || 'GitHub 授权失败，请重试'))
    router.replace({ path: route.path })
  }
  await loadStatus()
})
</script>

<style scoped>
.gh-bind{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:16px;padding:18px 20px;border-radius:14px;background:rgba(14,22,36,0.7);backdrop-filter:blur(16px);border:1px solid rgba(56,75,110,0.4);box-shadow:0 8px 30px rgba(0,0,0,0.4)}
.gh-left{display:flex;align-items:center;gap:15px;min-width:0}
.gh-mark{width:42px;height:42px;flex-shrink:0;border-radius:12px;display:grid;place-items:center;font-size:20px;color:#9aa6bb;background:rgba(28,36,50,0.6);border:1px solid rgba(56,75,110,0.5)}
.gh-mark.on{color:#00f2fe;background:rgba(0,242,254,0.12);border-color:rgba(0,242,254,0.5);box-shadow:0 0 16px rgba(0,242,254,0.25)}
.gh-copy{min-width:0}
.gh-copy .eyebrow{margin-bottom:5px;font-size:9.5px;color:#00f2fe}
.gh-copy strong{display:block;font-size:14px;color:#edf1f8;font-weight:600}
.gh-copy p{margin:4px 0 0;font-size:11px;line-height:1.65;color:#8798b4}
.gh-actions{display:flex;align-items:center;gap:10px;flex-shrink:0}
.muted{color:#8798b4;font-size:11px}
.import-toolbar{display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.import-foot{display:flex;align-items:center;gap:10px;margin-top:14px;flex-wrap:wrap}
.import-foot .grow{flex:1}
.repo-cell{display:flex;flex-direction:column;gap:3px}
.repo-cell b{font-size:12.5px;color:#e6ebf4}
.repo-cell small{font-size:10.5px;color:#788ca8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.callback-row{display:flex;align-items:center;gap:10px;margin:14px 0;padding:10px 14px;border:1px solid rgba(56,75,110,0.5);border-radius:9px;background:#0a0e18;flex-wrap:wrap}
.callback-row code{font:11px 'DM Mono',monospace;color:#00f2fe;word-break:break-all}
.steps{margin:6px 0 0;padding-left:17px;font-size:11px;line-height:1.85;color:#b4becf}
.app-form{margin-top:6px}
.hint{margin-top:5px;line-height:1.5}
@media(max-width:820px){
  .gh-bind{flex-direction:column;align-items:flex-start}
  .gh-actions{flex-wrap:wrap;width:100%}
}
</style>
