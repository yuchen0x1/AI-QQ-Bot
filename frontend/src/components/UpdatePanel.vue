<template>
  <section id="updates" class="surface settings-panel update-panel" aria-label="在线更新">
    <div class="surface-head"><div><h3>在线更新</h3><p>发现新版本后可立即升级。服务器会自动下载、校验、备份、安装并重启服务。</p></div><el-tag :type="active ? 'warning' : updateAvailable ? 'warning' : 'success'" effect="dark">{{ statusLabel }}</el-tag></div>
    <div class="update-summary"><div><span>当前版本</span><b>v{{ info.current_version || '—' }}</b></div><div><span>最新版本</span><b>v{{ info.latest_version || '—' }}</b></div><div><span>渠道</span><b>{{ info.channel || 'stable' }}</b></div></div>
    <div class="update-actions">
      <el-button v-if="updateAvailable" type="primary" :loading="starting" :disabled="active || job?.status === 'attention' || !info.installable" @click="install">{{ active ? '正在升级' : '立即升级' }}</el-button>
      <el-button :loading="checking" :disabled="active" @click="check(true)">检查更新</el-button>
      <el-link v-if="info.release_url" :href="info.release_url" target="_blank" type="primary">查看发布说明</el-link>
      <span v-if="info.published_at" class="subtext">发布时间：{{ new Date(info.published_at).toLocaleString('zh-CN') }}</span>
    </div>
    <el-alert v-if="info.error" :title="info.error" type="warning" :closable="false" show-icon />
    <el-alert v-if="updateAvailable && !info.installable && !active" class="update-notice" :title="info.installer?.reason || '此版本的自动升级包尚未就绪，请稍后检查。'" type="info" :closable="false" show-icon />
    <div v-if="job" class="install-progress" role="status" aria-live="polite">
      <div class="progress-heading"><b>{{ reconnecting ? '服务正在重启，正在等待恢复…' : job.message }}</b><span>v{{ job.version }}</span></div>
      <el-progress :percentage="job.progress || 0" :status="progressStatus" :stroke-width="10" />
      <p v-if="active">升级任务在服务器后台继续运行。服务恢复后，这一页会自动刷新到新版本。</p>
      <p v-if="job.status === 'succeeded'">新版本已启动并通过检查。</p>
      <el-alert v-if="job.error" :title="job.error" :type="job.status === 'rolled_back' ? 'warning' : 'error'" :closable="false" show-icon />
      <p v-if="job.status === 'rolled_back'">已恢复升级前的版本和数据，可以修复问题后重试。</p>
    </div>
    <div v-if="info.release_notes" class="release-notes"><div class="subtext">更新日志</div><pre>{{ info.release_notes }}</pre></div>
    <el-table v-if="info.assets?.length" :data="info.assets" stripe class="asset-table"><el-table-column prop="name" label="发布文件" min-width="220" /><el-table-column label="大小" width="110"><template #default="s">{{ formatBytes(s.row.size) }}</template></el-table-column><el-table-column label="SHA-256" min-width="220"><template #default="s">{{ s.row.sha256 || '发布页未提供' }}</template></el-table-column><el-table-column label="下载" width="90"><template #default="s"><el-link :href="s.row.download_url" target="_blank" type="primary">打开</el-link></template></el-table-column></el-table>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const info = ref<any>({}), job = ref<any>(null), checking = ref(false), starting = ref(false), reconnecting = ref(false)
const updateAvailable = computed(() => Boolean(info.value.update_available))
const active = computed(() => ['queued', 'running'].includes(job.value?.status))
const statusLabel = computed(() => active.value ? '升级中' : checking.value ? '检查中…' : updateAvailable.value ? '发现新版本' : info.value.ok ? '已是最新版本' : '等待检查')
const progressStatus = computed(() => job.value?.status === 'succeeded' ? 'success' : ['failed', 'rolled_back', 'attention'].includes(job.value?.status) ? 'exception' : undefined)
let timer: ReturnType<typeof setTimeout> | undefined, disposed = false
const pendingKey = 'qbot_upgrade_pending'
function clearPending() { localStorage.removeItem(pendingKey); localStorage.removeItem('qbot_upgrade_pending_since') }
function schedule() { if (!disposed) timer = setTimeout(poll, 2000) }
async function check(notify = false) {
  checking.value = true
  try { const { data } = await api.get('/system/update'); info.value = data; if (data.installer?.job) job.value = data.installer.job; if (notify && data.ok) ElMessage.info(data.update_available ? `发现新版本 v${data.latest_version}` : '当前已是最新版本') }
  catch { info.value.error = '暂时无法读取版本信息，请稍后重试' }
  finally { checking.value = false }
}
async function poll() {
  try {
    const token = localStorage.getItem('qbot_token')
    const response = await fetch('/api/system/update/install', { headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: 'no-store', signal: AbortSignal.timeout(8000) })
    if (response.status === 401) { reconnecting.value = false; info.value.error = '登录已过期，请重新登录后查看升级结果'; return }
    if (!response.ok) throw new Error('waiting')
    const data = await response.json()
    if (disposed) return
    reconnecting.value = false
    if (data.job) job.value = data.job
    if (active.value) { schedule(); return }
    const pending = localStorage.getItem(pendingKey)
    if (job.value && !active.value) {
      const finishedHere = pending === job.value.id
      clearPending()
      if (job.value.status === 'succeeded' && finishedHere && localStorage.getItem('qbot_upgrade_reloaded') !== job.value.id) {
        localStorage.setItem('qbot_upgrade_reloaded', job.value.id)
        ElMessage.success('升级成功，正在刷新到新版本')
        timer = setTimeout(() => location.reload(), 1500)
        return
      }
      await check(false)
    }
  } catch {
    if (active.value || localStorage.getItem(pendingKey)) { reconnecting.value = true; schedule() }
  }
}
async function install() {
  if (active.value || starting.value || !info.value.installable) return
  starting.value = true
  const id = localStorage.getItem(pendingKey) || crypto.randomUUID()
  localStorage.setItem(pendingKey, id); localStorage.setItem('qbot_upgrade_pending_since', String(Date.now()))
  try {
    const { data } = await api.post('/system/update/install', { version: info.value.latest_version, request_id: id })
    job.value = data.job
    if (timer) clearTimeout(timer)
    await poll()
  } catch (error: any) {
    if (error.response && error.response.status < 500) { clearPending(); info.value.error = error.response.data?.detail || '升级请求未被接受' }
    else { reconnecting.value = true; schedule() }
  } finally { starting.value = false }
}
function formatBytes(value: number) { if (!value) return '—'; const units = ['B', 'KB', 'MB', 'GB']; let n = value, i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }; return `${n.toFixed(i ? 1 : 0)} ${units[i]}` }
onMounted(async () => { await check(); await poll() })
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>
<style scoped>
.update-panel{grid-column:1/-1;padding:18px;min-width:0}.surface-head{gap:16px}.update-summary{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.update-summary>div{min-width:130px;padding:10px 12px;border:1px solid #29364c;border-radius:8px;background:#111927}.update-summary span,.update-summary b{display:block}.update-summary span,.subtext{color:#8fa1bb;font-size:12px}.update-summary b{margin-top:4px;color:#dce7f7;font-size:16px}.update-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.update-notice{margin-top:16px}.install-progress{margin-top:22px;padding:20px;border:1px solid #455782;border-radius:10px;background:#111b2d}.progress-heading{display:flex;justify-content:space-between;gap:16px;margin-bottom:18px;color:#c5def3}.install-progress p{font-size:13px;line-height:1.8;color:#a9bad2}.release-notes{margin-top:20px}.release-notes pre{max-height:260px;overflow:auto;padding:14px;border:1px solid #29364c;border-radius:8px;background:#0d141f;color:#b7c8df;font:12px/1.8 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap}.asset-table{margin-top:18px}.update-panel :deep(.el-alert){margin-top:14px;background:#17243a;color:#b8cce4}@media(max-width:650px){.update-summary>div{min-width:110px;flex:1}.install-progress{padding:14px}.surface-head{align-items:flex-start}}
</style>
