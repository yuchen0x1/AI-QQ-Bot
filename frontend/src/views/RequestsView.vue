<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">ACCESS REVIEW</div>
      <h1>申请审核</h1>
      <p>查看历史申请与处理结果；审批操作按机器人实际开放的接口能力提供。</p>
    </div>
    <div class="heading-actions">
      <el-button :loading="loading" @click="load()">
        <AppIcon name="refresh" :size="14" class="button-icon" />刷新
      </el-button>
    </div>
  </div>

  <section class="surface resource-surface request-surface" aria-labelledby="request-list-title">
    <div class="resource-toolbar request-toolbar">
      <div class="filter-group">
        <span class="filter-label"><AppIcon name="filter" :size="14" />筛选</span>
        <div class="filter-row">
          <el-select
            v-model="accountId"
            clearable
            placeholder="所有账号"
            aria-label="按接收账号筛选"
            @change="load(1)"
          >
            <el-option
              v-for="item in accounts"
              :key="item.id"
              :label="`${item.name} · ${item.qq_number || '未知QQ'}`"
              :value="item.id"
            />
          </el-select>
          <el-select
            v-model="requestType"
            clearable
            placeholder="所有申请类型"
            aria-label="按申请类型筛选"
            @change="load(1)"
          >
            <el-option label="加群申请 / 邀请" value="group" />
            <el-option label="好友申请" value="friend" />
          </el-select>
          <el-select v-model="status" aria-label="按审核状态筛选" @change="load(1)">
            <el-option label="待审核" value="pending" />
            <el-option label="已通过" value="approved" />
            <el-option label="已拒绝" value="rejected" />
            <el-option label="全部" value="" />
          </el-select>
          <el-button @click="load(1)">
            <AppIcon name="search" :size="14" class="button-icon" />查询
          </el-button>
        </div>
      </div>
      <span class="toolbar-count" aria-live="polite">
        <AppIcon name="inbox" :size="13" />
        {{ loading ? '查询中…' : `当前筛选 ${total} 条` }}
      </span>
    </div>

    <h2 id="request-list-title" class="sr-only">申请审核列表</h2>

    <el-alert
      v-if="loadError"
      type="error"
      :closable="false"
      show-icon
      class="request-alert"
      title="申请列表加载失败"
    >
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="danger" @click="load()">重试</el-button>
      </template>
    </el-alert>

    <el-alert
      v-if="permissionsReady && !canManage"
      type="info"
      :closable="false"
      show-icon
      class="request-alert"
      title="当前账号只有查看权限"
    >
      通过和拒绝按钮需要 <code>request:manage</code> 权限。你仍可以查看申请记录与已有处理结果。
    </el-alert>

    <el-table
      v-loading="loading"
      :data="rows"
      row-key="id"
      stripe
      class="request-table"
    >
      <el-table-column label="类型" width="128">
        <template #default="scope">
          <span class="type-badge" :class="typeMeta(scope.row).tone">
            <AppIcon :name="typeMeta(scope.row).icon" :size="12" />
            {{ typeMeta(scope.row).label }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="申请人 QQ" width="145">
        <template #default="scope">
          <div class="user-cell">
            <span class="user-mark"><AppIcon name="user" :size="13" /></span>
            <b>{{ scope.row.user_id }}</b>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="目标群号" width="125">
        <template #default="scope">{{ scope.row.group_id || '—' }}</template>
      </el-table-column>
      <el-table-column prop="account_name" label="接收账号" width="145" show-overflow-tooltip>
        <template #default="scope">{{ scope.row.account_name || '—' }}</template>
      </el-table-column>
      <el-table-column prop="comment" label="验证信息" min-width="210" show-overflow-tooltip>
        <template #default="scope">{{ scope.row.comment || '（未填写）' }}</template>
      </el-table-column>
      <el-table-column label="收到时间" width="170">
        <template #default="scope"><span class="time-text">{{ formatDate(scope.row.created_at) }}</span></template>
      </el-table-column>
      <el-table-column label="状态" width="105">
        <template #default="scope">
          <span class="request-status" :class="statusMeta(scope.row.status).tone">
            <AppIcon :name="statusMeta(scope.row.status).icon" :size="12" />
            {{ statusMeta(scope.row.status).label }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="处理人" width="110">
        <template #default="scope">
          <span :class="{ 'cell-muted': !scope.row.handled_by }">{{ scope.row.handled_by || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="decision_reason" label="审核备注" min-width="160" show-overflow-tooltip>
        <template #default="scope">
          <span :class="{ 'cell-muted': !scope.row.decision_reason }">{{ scope.row.decision_reason || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="145" fixed="right">
        <template #default="scope">
          <div v-if="scope.row.status === 'pending'" class="row-actions">
            <el-button
              link
              type="success"
              :disabled="!canManage || !supportsDecision(scope.row)"
              :title="decisionHint(scope.row)"
              @click="decide(scope.row, true)"
            >
              <AppIcon name="check" :size="13" class="button-icon" />通过
            </el-button>
            <el-button
              link
              type="danger"
              :disabled="!canManage || !supportsDecision(scope.row)"
              :title="decisionHint(scope.row)"
              @click="decide(scope.row, false)"
            >
              <AppIcon name="close" :size="13" class="button-icon" />拒绝
            </el-button>
          </div>
          <span v-else class="cell-muted">{{ scope.row.handled_by || '已处理' }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <div class="request-empty">
          <span class="empty-icon"><AppIcon :name="status === 'pending' ? 'inbox' : 'search'" :size="24" /></span>
          <div>
            <b>{{ loadError ? '暂时无法读取申请记录' : emptyTitle }}</b>
            <p>{{ emptyCopy }}</p>
          </div>
          <el-button v-if="loadError" @click="load()">
            <AppIcon name="refresh" :size="14" class="button-icon" />重新加载
          </el-button>
          <el-button v-else-if="status !== 'pending'" type="primary" plain @click="showPending">
            查看待审核申请
          </el-button>
        </div>
      </template>
    </el-table>

    <div class="pagination-wrap">
      <span>共 {{ total }} 条申请</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="sizes, prev, pager, next"
        @current-change="load"
        @size-change="load(1)"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'

type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const rows = ref<any[]>([]), accounts = ref<any[]>([]), loading = ref(false)
const page = ref(1), pageSize = ref(20), total = ref(0), loadError = ref('')
const accountId = ref<number>(), requestType = ref(''), status = ref('pending')
const userPermissions = ref<string[]>([]), permissionsReady = ref(false)

const canManage = computed(() => userPermissions.value.includes('*') || userPermissions.value.includes('request:manage'))
const emptyTitle = computed(() => status.value === 'pending'
  ? '当前没有待审核申请'
  : '当前筛选没有申请记录')
const emptyCopy = computed(() => loadError.value
  ? '请检查连接后重新加载，已有数据不会因为查询失败被清空。'
  : status.value === 'pending'
    ? '新的加群或好友申请会由在线机器人写入这里，并默认显示为待审核。产生新申请后刷新即可查看。'
    : '调整接收账号、申请类型或审核状态后重新查询；切回「待审核」可以查看仍需处理的申请。')

const supportsDecision = (row: any) => accounts.value.find(
  (account) => account.id === row.account_id,
)?.capabilities?.[row.request_type === 'group' ? 'set_group_add_request' : 'set_friend_add_request'] === true

function typeMeta(row: any): { label: string; tone: Tone; icon: string } {
  if (row.request_type === 'group' && row.sub_type === 'invite') {
    return { label: '邀请入群', tone: 'warning', icon: 'send' }
  }
  if (row.request_type === 'group') {
    return { label: '加群申请', tone: 'warning', icon: 'users' }
  }
  return { label: '好友申请', tone: 'info', icon: 'user' }
}

function statusMeta(value: string): { label: string; tone: Tone; icon: string } {
  if (value === 'approved') return { label: '已通过', tone: 'success', icon: 'check-circle' }
  if (value === 'rejected') return { label: '已拒绝', tone: 'danger', icon: 'alert' }
  if (value === 'pending') return { label: '待审核', tone: 'warning', icon: 'clock' }
  return { label: value || '未知', tone: 'neutral', icon: 'info' }
}

function decisionHint(row: any) {
  if (!canManage.value) return '当前账号没有申请审批权限'
  if (supportsDecision(row)) return '提交后将同步到 QQ 协议端'
  return '账号当前离线，或当前协议端不支持处理此类申请'
}

async function load(target?: number) {
  if (target) page.value = target
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get('/requests', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        account_id: accountId.value,
        request_type: requestType.value || undefined,
        status: status.value || undefined,
      },
    })
    rows.value = data.items || []
    total.value = data.total || 0
  } catch (err: any) {
    loadError.value = err.response?.data?.detail || '请求失败，请检查连接后重试'
  } finally {
    loading.value = false
  }
}

async function decide(row: any, approve: boolean) {
  let reason = ''
  let remark = ''
  try {
    const options: any = {
      inputType: 'textarea',
      inputValue: '',
      inputPlaceholder: approve ? '可选：填写审核备注' : '可选：填写拒绝原因',
      confirmButtonText: approve ? '确认通过' : '确认拒绝',
      cancelButtonText: '取消',
      type: approve ? 'info' : 'warning',
    }
    if (!approve) options.confirmButtonClass = 'el-button--danger'
    const { value } = await ElMessageBox.prompt(
      approve
        ? '确认通过这条申请吗？可填写审核备注，提交后会同步到 QQ。'
        : '拒绝后会通知申请人，请确认操作。可填写拒绝原因。',
      approve ? '确认通过申请' : '确认拒绝申请',
      options,
    )
    reason = value || ''
    remark = reason
  } catch {
    return
  }
  try {
    const { data } = await api.post(`/requests/${row.id}/decision`, { approve, reason, remark })
    Object.assign(row, data)
    ElMessage.success(approve ? '申请已通过' : '申请已拒绝')
  } catch {}
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

function showPending() {
  status.value = 'pending'
  load(1)
}

onMounted(async () => {
  const [accountResponse, userResponse] = await Promise.all([api.get('/accounts'), api.get('/auth/me')])
  accounts.value = accountResponse.data
  userPermissions.value = userResponse.data.permissions || []
  permissionsReady.value = true
  await load()
})
</script>

<style scoped>
.request-surface {
  overflow: hidden;
}

.request-toolbar {
  align-items: center;
  padding: 14px 18px;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.filter-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.filter-label .app-icon {
  color: var(--text-4);
}

.filter-row {
  min-width: 0;
}

.filter-row .el-select {
  width: 184px;
}

.toolbar-count {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  padding: 4px 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface);
  color: var(--text-3);
  font: 550 9px/1.4 var(--font-mono);
}

.toolbar-count .app-icon {
  color: var(--text-4);
}

.request-alert {
  margin: 14px 18px 0;
}

.request-alert code {
  padding: 1px 4px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--code-bg);
  color: var(--text-2);
  font: 500 10px/1.5 var(--font-mono);
}

.request-table {
  width: 100%;
}

.type-badge,
.request-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 7px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}

.type-badge.warning,
.request-status.warning {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}

.type-badge.info,
.request-status.info {
  border-color: var(--info-line);
  background: var(--info-soft);
  color: var(--info);
}

.type-badge.success,
.request-status.success {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.type-badge.danger,
.request-status.danger {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}

.type-badge.neutral,
.request-status.neutral {
  color: var(--text-3);
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.user-mark {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-2);
  color: var(--text-3);
}

.user-cell b {
  color: var(--text-2);
  font: 550 10.5px/1.4 var(--font-mono);
}

.time-text {
  color: var(--text-3);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.cell-muted {
  color: var(--text-4);
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.row-actions :deep(.el-button) {
  margin-left: 0;
}

.button-icon {
  margin-right: 3px;
}

.request-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 13px;
  min-height: 170px;
  padding: 24px;
  text-align: left;
}

.request-empty > div {
  max-width: 460px;
}

.request-empty .empty-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-2);
  color: var(--text-4);
}

.request-empty b {
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
}

.request-empty p {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.7;
}

.request-empty :deep(.el-button) {
  flex: none;
  margin-left: 3px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.request-toolbar :deep(.el-button:focus-visible),
.request-surface :deep(.el-button:focus-visible) {
  outline: 2px solid var(--brand-strong);
  outline-offset: 2px;
}

@media (max-width: 840px) {
  .request-toolbar {
    align-items: flex-start;
    width: 100%;
  }

  .filter-group {
    align-items: flex-start;
    flex-direction: column;
    width: 100%;
  }

  .filter-row {
    width: 100%;
  }

  .toolbar-count {
    margin-left: 0;
  }
}

@media (max-width: 700px) {
  .filter-row .el-select {
    width: 100%;
  }

  .request-alert {
    margin-inline: 14px;
  }

  .request-empty {
    align-items: flex-start;
    flex-direction: column;
  }

  .request-empty :deep(.el-button) {
    margin-left: 53px;
  }
}
</style>
