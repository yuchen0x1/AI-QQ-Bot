<template>
  <div class="plugin-workspace">
    <ResourceView ref="resourceRef" :config="config">
      <template #panel>
        <section class="runtime-banner surface" aria-labelledby="runtime-title">
          <div class="runtime-copy">
            <div class="runtime-kicker">
              <span class="runtime-dot"></span>
              EXTENSIONS RUNTIME
            </div>
            <h2 id="runtime-title">可组合的机器人能力</h2>
            <p>插件按声明的权限运行，支持热加载与账号 / 群绑定。所有配置均通过后端接口持久化，运行指标只反映当前后端进程。</p>
            <div class="runtime-meta">
              <span><AppIcon name="shield" :size="13" />按权限声明执行</span>
              <span><AppIcon name="zap" :size="13" />支持热加载与重载</span>
              <span><AppIcon name="layers" :size="13" />可绑定账号与群</span>
            </div>
          </div>
        </section>

        <div class="stat-grid runtime-stats" aria-label="插件运行时计数">
          <div class="stat-tile">
            <span class="stat-tile-icon brand"><AppIcon name="puzzle" :size="17" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">已发现插件</span>
              <strong class="stat-tile-value">{{ runtimeStats.total }}</strong>
              <span class="stat-tile-meta">当前插件列表中的全部条目</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon green"><AppIcon name="check-circle" :size="17" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">已启用</span>
              <strong class="stat-tile-value">{{ runtimeStats.enabled }}</strong>
              <span class="stat-tile-meta">启用开关已打开</span>
            </div>
          </div>
          <div class="stat-tile">
            <span class="stat-tile-icon cyan"><AppIcon name="activity" :size="17" /></span>
            <div class="stat-tile-copy">
              <span class="stat-tile-label">已加载</span>
              <strong class="stat-tile-value">{{ runtimeStats.loaded }}</strong>
              <span class="stat-tile-meta">运行时已就绪，可处理命令</span>
            </div>
          </div>
        </div>
      </template>
    </ResourceView>

    <el-dialog
      v-model="metricsDialog"
      :title="`${selectedPlugin?.name || '插件'} · 运行指标`"
      width="min(760px, calc(100vw - 28px))"
      class="metrics-dialog"
      destroy-on-close
    >
      <template #header>
        <div class="dialog-heading">
          <span class="dialog-icon"><AppIcon name="chart" :size="17" /></span>
          <div>
            <h3>{{ selectedPlugin?.name || '插件' }} · 运行指标</h3>
            <p>来自当前后端进程的调用、耗时与权限审计数据。</p>
          </div>
        </div>
      </template>

      <div v-if="metricsLoading" class="metrics-loading" aria-live="polite">
        <div class="loading-caption"><AppIcon name="loader" :size="14" class="spin-icon" />正在读取运行指标…</div>
        <el-skeleton :rows="6" animated />
      </div>

      <el-alert
        v-else-if="metricsError"
        type="error"
        :closable="false"
        show-icon
        title="运行指标加载失败"
      >
        <template #default>
          <span>{{ metricsError }}</span>
          <el-button link type="danger" @click="retryMetrics">重新加载</el-button>
        </template>
      </el-alert>

      <template v-else-if="metrics">
        <div class="metrics-summary-line">
          <span><AppIcon name="clock" :size="13" />最后运行：{{ formatDate(metrics.last_run_at) }}</span>
          <span><AppIcon name="info" :size="13" />进程内累计</span>
        </div>

        <div class="metrics-grid">
          <div class="metric-tile">
            <span class="metric-icon brand"><AppIcon name="activity" :size="16" /></span>
            <div><span>调用次数</span><strong>{{ metrics.invocations ?? 0 }}</strong></div>
          </div>
          <div class="metric-tile">
            <span class="metric-icon warning"><AppIcon name="alert" :size="16" /></span>
            <div><span>错误率</span><strong>{{ formatRate(metrics.error_rate) }}</strong></div>
          </div>
          <div class="metric-tile">
            <span class="metric-icon cyan"><AppIcon name="timer" :size="16" /></span>
            <div><span>平均耗时</span><strong>{{ formatDuration(metrics.avg_duration_ms) }}</strong></div>
          </div>
          <div class="metric-tile">
            <span class="metric-icon danger"><AppIcon name="shield" :size="16" /></span>
            <div><span>权限拒绝</span><strong>{{ metrics.permission_denied ?? 0 }}</strong></div>
          </div>
        </div>

        <el-alert
          v-if="metrics.last_error"
          type="error"
          :closable="false"
          show-icon
          title="最近一次错误"
          class="last-error"
        >
          <template #default>{{ metrics.last_error }} · {{ formatDate(metrics.last_error_at) }}</template>
        </el-alert>

        <section class="permission-section" aria-labelledby="permission-title">
          <div class="permission-heading">
            <div>
              <h4 id="permission-title">权限调用审计</h4>
              <p>最近 50 条由插件发起的权限检查记录。</p>
            </div>
            <span v-if="metrics.permission_checks?.length" class="audit-count">
              {{ metrics.permission_checks.length }} 条
            </span>
          </div>

          <div v-if="!metrics.permission_checks?.length" class="permission-empty">
            <span><AppIcon name="shield" :size="21" /></span>
            <div>
              <b>暂无权限调用记录</b>
              <p>插件执行受限能力后，这里会记录权限名称与允许 / 拒绝结果。</p>
            </div>
          </div>
          <el-table
            v-else
            :data="metrics.permission_checks"
            stripe
            max-height="260"
            class="permission-table"
          >
            <el-table-column label="时间" width="176">
              <template #default="scope">{{ formatDate(scope.row.time) }}</template>
            </el-table-column>
            <el-table-column prop="permission" label="权限" min-width="190" show-overflow-tooltip />
            <el-table-column label="结果" width="88">
              <template #default="scope">
                <span class="permission-result" :class="scope.row.allowed ? 'allowed' : 'denied'">
                  <AppIcon :name="scope.row.allowed ? 'check-circle' : 'shield'" :size="12" />
                  {{ scope.row.allowed ? '允许' : '拒绝' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import ResourceView from '../components/ResourceView.vue'
import { api } from '../api'

const resourceRef = ref()
const metricsDialog = ref(false), metricsLoading = ref(false), metrics = ref<any>(null)
const metricsError = ref(''), selectedPlugin = ref<any>(null)

const runtimeStats = computed(() => {
  const rows = resourceRef.value?.rows || []
  return {
    total: rows.length,
    enabled: rows.filter((item: any) => item.enabled).length,
    loaded: rows.filter((item: any) => item.load_status === 'loaded').length,
  }
})

function formatDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}
function formatRate(value: any) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}
function formatDuration(value: any) {
  return `${Number(value || 0).toFixed(1)} ms`
}

async function showMetrics(row: any) {
  selectedPlugin.value = row
  metrics.value = null
  metricsError.value = ''
  metricsDialog.value = true
  metricsLoading.value = true
  try {
    const { data } = await api.get(`/plugins/${row.id}/metrics`)
    metrics.value = data
  } catch (err: any) {
    metricsError.value = err.response?.data?.detail || '指标加载失败，请稍后重试'
    ElMessage.error(metricsError.value)
  } finally {
    metricsLoading.value = false
  }
}
function retryMetrics() {
  if (selectedPlugin.value) showMetrics(selectedPlugin.value)
}

const config = {
  kicker: 'EXTENSIONS',
  title: '插件管理',
  description: '管理隔离运行的扩展能力，并查看权限声明与账号 / 群绑定',
  endpoint: '/plugins',
  itemName: '插件',
  nameKey: 'name',
  paged: false,
  actionWidth: 220,
  columns: [
    { key: 'name', label: '插件名称', width: 165 },
    { key: 'plugin_id', label: '插件 ID', width: 150 },
    { key: 'version', label: '版本', width: 85 },
    { key: 'author', label: '作者', width: 110 },
    { key: 'description', label: '说明', width: 210 },
    { key: 'commands', label: '命令', width: 140 },
    { key: 'permissions', label: '权限声明', width: 175 },
    { key: 'binding_count', label: '绑定数', width: 80 },
    {
      key: 'load_status',
      label: '加载状态',
      type: 'status',
      width: 100,
      options: [
        { value: 'loaded', label: '已加载' },
        { value: 'disabled', label: '已禁用' },
        { value: 'error', label: '错误' },
      ],
    },
    { key: 'enabled', label: '启用', type: 'bool', width: 75 },
  ],
  createFields: [],
  editFields: [
    { key: 'enabled', label: '启用插件', type: 'switch' },
    { key: 'config', label: '插件配置 JSON', type: 'json', rows: 6 },
  ],
  actions: [
    { label: '指标', permission: 'plugin:view', handler: (row: any) => showMetrics(row), type: 'primary' },
    { label: '重新加载', suffix: 'reload', method: 'POST', type: 'warning' },
  ],
  secondaryAction: {
    label: '扫描插件目录',
    path: '/plugins/sync',
    method: 'POST',
    success: (data: any) => `已同步 ${Array.isArray(data) ? data.length : 0} 个插件`,
  },
}
</script>

<style scoped>
.plugin-workspace {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.runtime-banner {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 22px;
  overflow: hidden;
  padding: 22px 24px;
  border-radius: var(--radius-xl);
  background:
    radial-gradient(480px 180px at 4% 0%, var(--brand-soft), transparent 74%),
    radial-gradient(420px 180px at 94% 100%, var(--cyan-soft), transparent 72%),
    var(--surface);
}

.runtime-banner::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: linear-gradient(90deg, var(--surface), transparent 66%);
}

.runtime-copy {
  position: relative;
  z-index: 1;
  min-width: 0;
}

.runtime-kicker {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 9px;
  color: var(--brand-strong);
  font: 650 9.5px/1.4 var(--font-mono);
  letter-spacing: 0.16em;
}

.runtime-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 0 3px var(--success-soft);
}

.runtime-banner h2 {
  margin: 0 0 5px;
  color: var(--text);
  font-size: 20px;
  font-weight: 660;
  letter-spacing: -0.03em;
}

.runtime-banner p {
  max-width: 840px;
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.7;
}

.runtime-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 13px;
}

.runtime-meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-4);
  font-size: 9.5px;
}

.runtime-meta .app-icon {
  color: var(--brand-strong);
}

.runtime-stats {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 0;
}

.runtime-stats .stat-tile {
  min-height: 82px;
}

.runtime-stats .stat-tile-copy {
  gap: 2px;
}

.dialog-heading {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.dialog-icon {
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

.dialog-heading h3 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 14px;
  font-weight: 640;
}

.dialog-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.6;
}

.metrics-loading {
  padding: 4px 0;
}

.loading-caption {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 14px;
  color: var(--text-3);
  font-size: 10.5px;
}

.spin-icon {
  animation: plugin-spin 1.1s linear infinite;
}

.metrics-summary-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.metrics-summary-line span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-4);
  font-size: 9.5px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
  margin-bottom: 14px;
}

.metric-tile {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
}

.metric-icon {
  display: grid;
  place-items: center;
  width: 31px;
  height: 31px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-3);
}

.metric-icon.brand {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.metric-icon.warning {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}

.metric-icon.cyan {
  border-color: var(--cyan-line);
  background: var(--cyan-soft);
  color: var(--cyan);
}

.metric-icon.danger {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}

.metric-tile > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.metric-tile span:not(.metric-icon) {
  color: var(--text-3);
  font-size: 9.5px;
}

.metric-tile strong {
  overflow: hidden;
  color: var(--text);
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.last-error {
  margin: 0 0 14px;
}

.permission-section {
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.permission-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 10px;
}

.permission-heading h4 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 620;
}

.permission-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.6;
}

.audit-count {
  flex: none;
  padding: 3px 7px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font: 600 9px/1.4 var(--font-mono);
}

.permission-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 96px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
}

.permission-empty > span {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text-4);
}

.permission-empty b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 600;
}

.permission-empty p {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.6;
}

.permission-result {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 9.5px;
  font-weight: 600;
}

.permission-result.allowed {
  color: var(--success);
}

.permission-result.denied {
  color: var(--danger);
}

.permission-table {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
}

@keyframes plugin-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .runtime-banner {
    padding: 18px;
  }

  .runtime-stats {
    grid-template-columns: 1fr;
  }

  .runtime-stats .stat-tile {
    min-height: 74px;
  }
}

@media (max-width: 480px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }

  .dialog-heading h3 {
    font-size: 13px;
  }

  .metrics-summary-line {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
