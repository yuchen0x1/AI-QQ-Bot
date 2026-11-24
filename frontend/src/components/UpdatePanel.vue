<template>
  <section id="updates" data-settings-section class="settings-section surface update-section" aria-label="在线更新">
    <div class="section-heading">
      <span class="section-icon"><AppIcon name="zap" :size="17" /></span>
      <div>
        <h2>在线更新</h2>
        <p>从 GitHub Releases 检查新版本，服务器会自动下载、校验、备份、安装并重启服务。</p>
      </div>
      <el-tag :type="statusTone" size="small">{{ statusLabel }}</el-tag>
    </div>

    <div class="version-grid">
      <div class="version-card current">
        <span class="version-label">当前版本</span>
        <b>v{{ info.current_version || '—' }}</b>
        <small>运行中的控制中心</small>
      </div>
      <div class="version-card latest">
        <span class="version-label">最新版本</span>
        <b>v{{ info.latest_version || '—' }}</b>
        <small>{{ info.published_at ? `发布于 ${formatDate(info.published_at)}` : '等待检查结果' }}</small>
      </div>
      <div class="version-card channel">
        <span class="version-label">更新通道</span>
        <b>{{ info.channel || 'stable' }}</b>
        <small :class="updateAvailable ? 'up' : ''">{{ updateAvailable ? '有新版本可用' : '当前为最新' }}</small>
      </div>
      <div class="version-card check">
        <span class="version-label">上次检查</span>
        <b>{{ checkedAt || '—' }}</b>
        <small>{{ checking ? '正在读取发布信息…' : '版本信息来自 GitHub Releases' }}</small>
      </div>
    </div>

    <div class="update-actions">
      <el-button v-if="updateAvailable" type="primary" :loading="starting" :disabled="active || job?.status === 'attention' || !info.installable" @click="install">
        <AppIcon name="zap" :size="14" style="margin-right:5px" />{{ active ? '正在升级' : `升级到 v${info.latest_version}` }}
      </el-button>
      <el-button v-if="updateAvailable && !active && !deferred" @click="deferUpdate">稍后提醒</el-button>
      <el-button :loading="checking" :disabled="active" @click="check(true)">
        <AppIcon name="refresh" :size="14" style="margin-right:5px" />检查更新
      </el-button>
      <el-link v-if="info.release_url" :href="info.release_url" target="_blank" type="primary">
        查看发布页<AppIcon name="external" :size="12" style="margin-left:4px" />
      </el-link>
      <span v-if="info.installer?.reason && updateAvailable && !info.installable" class="subtext">{{ info.installer.reason }}</span>
    </div>

    <el-alert v-if="info.error" :title="info.error" type="warning" :closable="false" show-icon class="update-alert" />
    <el-alert v-if="updateAvailable && !info.installable && !active" class="update-alert" :title="info.installer?.reason || '此版本的自动升级包尚未就绪，请稍后重试。'" type="info" :closable="false" show-icon />

    <div v-if="job" class="install-progress" role="status" aria-live="polite">
      <div class="progress-heading">
        <div>
          <span class="progress-kicker">{{ active ? 'UPGRADE IN PROGRESS' : 'UPGRADE RESULT' }}</span>
          <b>{{ reconnecting ? '服务正在重启，等待连接恢复…' : job.message }}</b>
        </div>
        <span class="progress-version">v{{ job.version }}</span>
      </div>
      <el-progress :percentage="Number(job.progress || 0)" :status="progressStatus" :stroke-width="7" :show-text="false" />
      <div class="progress-meta">
        <span>{{ job.status === 'succeeded' ? '升级完成' : active ? '服务器后台正在执行升级任务' : '任务已结束' }}</span>
        <span>{{ Number(job.progress || 0) }}%</span>
      </div>
      <ol class="update-pipeline">
        <li v-for="(stage, index) in updateStages" :key="stage.key" :class="stageState(index)">
          <span class="stage-dot">
            <AppIcon v-if="stageState(index) === 'done'" name="check" :size="11" />
            <i v-else-if="stageState(index) === 'active'" class="stage-pulse"></i>
            <span v-else>{{ index + 1 }}</span>
          </span>
          <div><b>{{ stage.label }}</b><small>{{ stage.hint }}</small></div>
        </li>
      </ol>
      <p v-if="active" class="progress-note">升级任务在服务器后台继续运行。服务恢复后，此页面会自动刷新到新版本。</p>
      <el-alert v-if="job.status === 'succeeded'" type="success" :closable="false" show-icon title="新版本已启动并通过健康检查。" />
      <el-alert v-if="job.status === 'rolled_back'" type="warning" :closable="false" show-icon title="升级失败，服务器已恢复升级前的版本和数据，可以修复问题后重试。" />
      <el-alert v-if="job.error" :title="job.error" :type="job.status === 'rolled_back' ? 'warning' : 'error'" :closable="false" show-icon class="update-alert" />
    </div>

    <div v-if="info.release_notes" class="release-notes">
      <div class="release-head">
        <div><h3>更新日志</h3><p>v{{ info.latest_version || info.current_version }}</p></div>
        <el-button v-if="releaseLines.length > 14" text size="small" @click="notesExpanded = !notesExpanded">
          {{ notesExpanded ? '收起' : '展开完整日志' }}
          <AppIcon :name="notesExpanded ? 'chevron-left' : 'chevron-right'" :size="13" style="margin-left:4px" />
        </el-button>
      </div>
      <div class="release-body" :class="{ collapsed: !notesExpanded && releaseLines.length > 14 }">
        <template v-for="(line, index) in releaseLines" :key="index">
          <p v-if="!line.trim()" class="release-gap"></p>
          <p v-else-if="/^#{1,4}\s/.test(line)" class="release-heading">{{ line.replace(/^#{1,4}\s/, '') }}</p>
          <p v-else-if="/^[-*]\s/.test(line)" class="release-bullet">{{ line.replace(/^[-*]\s/, '') }}</p>
          <p v-else class="release-text">{{ line }}</p>
        </template>
      </div>
    </div>

    <div v-if="info.assets?.length" class="asset-block">
      <div class="release-head"><div><h3>发布文件</h3><p>自动升级将校验以下资源</p></div></div>
      <div class="table-scroll">
        <el-table :data="info.assets" stripe>
          <el-table-column prop="name" label="文件" min-width="230" />
          <el-table-column label="大小" width="110"><template #default="scope">{{ formatBytes(scope.row.size) }}</template></el-table-column>
          <el-table-column label="SHA-256" min-width="220"><template #default="scope"><span class="mono asset-hash">{{ scope.row.sha256 || '发布页未提供' }}</span></template></el-table-column>
          <el-table-column label="下载" width="80" align="right"><template #default="scope"><el-link :href="scope.row.download_url" target="_blank" type="primary">打开</el-link></template></el-table-column>
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from './AppIcon.vue'
import { api } from '../api'

const info = ref<any>({})
const job = ref<any>(null)
const checking = ref(false)
const starting = ref(false)
const reconnecting = ref(false)
const checkedAt = ref('')
const notesExpanded = ref(false)
const updateAvailable = computed(() => Boolean(info.value.update_available))
const deferredVersion = ref(localStorage.getItem('qbot_deferred_update'))
const deferred = computed(() => deferredVersion.value === info.value.latest_version)
const active = computed(() => ['queued', 'running'].includes(job.value?.status))

const statusLabel = computed(() => {
  if (active.value) return '升级中'
  if (checking.value) return '检查中'
  if (job.value?.status === 'succeeded') return '升级成功'
  if (job.value?.status === 'failed') return '升级失败'
  if (job.value?.status === 'rolled_back') return '已回滚'
  if (job.value?.status === 'attention') return '需人工处理'
  if (updateAvailable.value) return '发现新版本'
  if (info.value.ok) return '已是最新'
  return '等待检查'
})

const statusTone = computed(() => {
  if (active.value) return 'warning'
  if (job.value?.status === 'succeeded') return 'success'
  if (['failed', 'rolled_back', 'attention'].includes(job.value?.status)) return 'danger'
  if (updateAvailable.value) return 'primary'
  return 'info'
})

const progressStatus = computed(() => job.value?.status === 'succeeded'
  ? 'success'
  : ['failed', 'rolled_back', 'attention'].includes(job.value?.status) ? 'exception' : undefined)

const updateStages = [
  { key: 'check', label: '检查版本', hint: '读取发布信息' },
  { key: 'download', label: '下载安装包', hint: '获取升级资源' },
  { key: 'verify', label: '校验完整性', hint: '验证签名与摘要' },
  { key: 'backup', label: '备份与准备', hint: '保护现有数据' },
  { key: 'install', label: '安装新版本', hint: '替换程序文件' },
  { key: 'restart', label: '重启服务', hint: '等待进程恢复' },
  { key: 'verify_run', label: '运行验证', hint: '健康检查通过' },
]

const stageIndex = computed(() => {
  const message = String(job.value?.message || '')
  if (/重新连接|重启|恢复/.test(message)) return 5
  if (/健康|验证运行|启动成功|检查通过/.test(message)) return 6
  if (/安装|解压|替换|升级中/.test(message)) return 4
  if (/备份|快照/.test(message)) return 3
  if (/校验|摘要|签名|sha/i.test(message)) return 2
  if (/下载|获取/.test(message)) return 1
  if (/检查|发现|版本/.test(message)) return 0
  return Math.min(updateStages.length - 1, Math.floor(Number(job.value?.progress || 0) / 15))
})

const releaseLines = computed(() => String(info.value.release_notes || '').split(/\r?\n/))

function stageState(index: number) {
  const status = job.value?.status
  if (status === 'succeeded' || status === 'rolled_back') return 'done'
  if (status === 'failed') return index < stageIndex.value ? 'done' : index === stageIndex.value ? 'failed' : 'pending'
  if (index < stageIndex.value) return 'done'
  if (index === stageIndex.value) return active.value || status === 'attention' ? 'active' : 'done'
  return 'pending'
}

let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const pendingKey = 'qbot_upgrade_pending'

function deferUpdate(event: MouseEvent) {
  deferredVersion.value = info.value.latest_version
  localStorage.setItem('qbot_deferred_update', info.value.latest_version)
  event.target?.dispatchEvent(new Event('qbot-update-deferred', { bubbles: true }))
}

function clearPending() {
  localStorage.removeItem(pendingKey)
  localStorage.removeItem('qbot_upgrade_pending_since')
}

function schedule() {
  if (!disposed) timer = setTimeout(poll, 2000)
}

async function check(notify = false) {
  checking.value = true
  try {
    const { data } = await api.get('/system/update')
    info.value = data
    checkedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    if (data.installer?.job) job.value = data.installer.job
    if (notify && data.ok) ElMessage.info(data.update_available ? `发现新版本 v${data.latest_version}` : '当前已是最新版本')
  } catch {
    info.value.error = '暂时无法读取版本信息，请检查服务器网络后重试'
  } finally {
    checking.value = false
  }
}

async function poll() {
  try {
    const response = await fetch('/api/system/update/install', {
      credentials: 'include',
      cache: 'no-store',
      signal: AbortSignal.timeout(8000),
    })
    if (response.status === 401) {
      reconnecting.value = false
      info.value.error = '登录已过期，请重新登录后查看升级结果'
      return
    }
    if (!response.ok) throw new Error('waiting')
    const data = await response.json()
    if (disposed) return
    reconnecting.value = false
    if (data.job) job.value = data.job
    if (active.value) {
      schedule()
      return
    }
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
    if (active.value || localStorage.getItem(pendingKey)) {
      reconnecting.value = true
      schedule()
    }
  }
}

async function install() {
  if (active.value || starting.value || !info.value.installable) return
  starting.value = true
  const version = String(info.value.latest_version)
  try {
    await ElMessageBox.confirm(`确认升级到 v${version}？安装期间服务将短暂中断。`, '安装服务器更新', {
      confirmButtonText: '开始升级',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    starting.value = false
    return
  }
  if (disposed || active.value) {
    starting.value = false
    return
  }
  const id = localStorage.getItem(pendingKey) || crypto.randomUUID()
  localStorage.setItem(pendingKey, id)
  localStorage.setItem('qbot_upgrade_pending_since', String(Date.now()))
  try {
    const { data } = await api.post('/system/update/install', { version, request_id: id })
    job.value = data.job
    if (timer) clearTimeout(timer)
    await poll()
  } catch (error: any) {
    if (error.response && error.response.status < 500) {
      clearPending()
      info.value.error = error.response.data?.detail || '升级请求未被接受'
    } else {
      reconnecting.value = true
      schedule()
    }
  } finally {
    starting.value = false
  }
}

function formatBytes(value: number) {
  if (!value) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index++
  }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

onMounted(async () => {
  await check()
  await poll()
})

onBeforeUnmount(() => {
  disposed = true
  if (timer) clearTimeout(timer)
})
</script>

<style scoped>
.update-section {
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
.version-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.version-card {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface-2);
}
.version-card.current {
  background:
    radial-gradient(240px 120px at 0% 0%, var(--brand-soft), transparent 70%),
    var(--surface-2);
  border-color: var(--brand-line);
}
.version-label {
  color: var(--text-4);
  font-size: 9px;
  letter-spacing: 0.04em;
}
.version-card b {
  overflow: hidden;
  color: var(--text);
  font-size: 18px;
  font-weight: 650;
  letter-spacing: -0.03em;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.version-card.check b {
  font-size: 15px;
}
.version-card small {
  color: var(--text-4);
  font-size: 9px;
  line-height: 1.45;
}
.version-card small.up {
  color: var(--warning);
}
.update-actions {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  margin-top: 14px;
}
.update-alert {
  margin-top: 12px;
}
.install-progress {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  background:
    radial-gradient(460px 180px at 0% 0%, var(--brand-soft), transparent 70%),
    var(--surface-inset);
}
.progress-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.progress-heading > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.progress-kicker {
  color: var(--brand-strong);
  font: 650 8.5px var(--font-mono);
  letter-spacing: 0.15em;
}
.progress-heading b {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 600;
}
.progress-version {
  flex: none;
  color: var(--text-3);
  font: 550 11px var(--font-mono);
}
.progress-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  color: var(--text-4);
  font-size: 9px;
}
.update-pipeline {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
  margin: 18px 0 0;
  padding: 0;
  list-style: none;
}
.update-pipeline li {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  min-width: 0;
}
.update-pipeline li.done {
  border-color: var(--success-line);
  background: var(--success-soft);
}
.update-pipeline li.active {
  border-color: var(--brand-line);
  background: var(--brand-soft);
}
.update-pipeline li.failed {
  border-color: var(--danger-line);
  background: var(--danger-soft);
}
.stage-dot {
  display: grid;
  place-items: center;
  width: 19px;
  height: 19px;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-4);
  font: 600 8.5px var(--font-mono);
}
.update-pipeline li.done .stage-dot {
  color: var(--success);
  border-color: var(--success-line);
  background: var(--surface);
}
.update-pipeline li.active .stage-dot {
  border-color: var(--brand);
  background: var(--surface);
}
.stage-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand);
  animation: stage-pulse 1.2s ease-in-out infinite;
}
.update-pipeline li.failed .stage-dot {
  color: var(--danger);
  border-color: var(--danger-line);
}
.update-pipeline li > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.update-pipeline b {
  overflow: hidden;
  color: var(--text-2);
  font-size: 9.5px;
  font-weight: 550;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.update-pipeline small {
  overflow: hidden;
  color: var(--text-4);
  font-size: 8.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.progress-note {
  margin: 14px 0 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.65;
}
.install-progress .el-alert {
  margin-top: 10px;
}
.release-notes {
  margin-top: 20px;
  border-top: 1px solid var(--line);
  padding-top: 16px;
}
.release-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.release-head h3 {
  margin: 0 0 2px;
  color: var(--text);
  font-size: 12px;
  font-weight: 620;
}
.release-head p {
  margin: 0;
  color: var(--text-4);
  font-size: 9.5px;
}
.release-body {
  position: relative;
  max-height: 360px;
  overflow-y: auto;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-inset);
}
.release-body.collapsed {
  max-height: 210px;
  overflow: hidden;
}
.release-body.collapsed::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 56px;
  background: linear-gradient(transparent, var(--surface-inset));
  pointer-events: none;
}
.release-gap {
  height: 6px;
  margin: 0;
}
.release-heading {
  margin: 12px 0 6px;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 650;
}
.release-heading:first-child {
  margin-top: 0;
}
.release-bullet,
.release-text {
  position: relative;
  margin: 0 0 4px;
  color: var(--text-2);
  font-size: 10.5px;
  line-height: 1.7;
}
.release-bullet {
  padding-left: 13px;
}
.release-bullet::before {
  content: "";
  position: absolute;
  left: 2px;
  top: 7px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--brand);
}
.asset-block {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
.asset-hash {
  color: var(--text-4);
  font-size: 9px;
}
.table-scroll {
  overflow-x: auto;
}
@keyframes stage-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.6); opacity: 0.45; }
}
@media (max-width: 1100px) {
  .version-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .update-pipeline {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .version-grid {
    grid-template-columns: 1fr;
  }
  .update-pipeline {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
