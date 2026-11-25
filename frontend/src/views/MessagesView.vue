<template>
  <div class="messages-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">
          MESSAGE WORKSPACE
          <span class="realtime-badge">
            <i :class="`socket-led ${realtime.state.value}`"></i>{{ realtimeLabel }}
          </span>
        </div>
        <h1>消息工作台</h1>
        <p>按账号与会话浏览真实消息记录，支持方向筛选、关键词检索和指定目标发送消息。</p>
      </div>
      <div class="heading-actions">
        <el-button v-if="realtime.state.value !== 'open'" text type="primary" @click="realtime.reconnect">
          <AppIcon name="refresh" :size="14" class="btn-icon" />重新连接
        </el-button>
        <el-button v-if="can('message:send')" type="primary" @click="openSend">
          <AppIcon name="send" :size="14" class="btn-icon" />发送消息
        </el-button>
      </div>
    </div>

    <section class="surface message-shell" aria-label="消息工作台">
      <div class="workspace-statusbar">
        <div class="live-state" :class="realtime.state.value" role="status" aria-live="polite">
          <i :class="`socket-led ${realtime.state.value}`"></i>
          <div>
            <b>{{ realtimeLabel }}</b>
            <small>{{ lastContentSync ? `消息同步于 ${new Date(lastContentSync).toLocaleTimeString('zh-CN')}` : '消息内容等待首次读取' }} · {{ realtime.state.value === 'open' ? '状态推送在线' : '状态可能延迟' }}</small>
          </div>
        </div>
        <div v-if="realtime.lastMessage.value" class="live-metrics">
          <span><AppIcon name="wifi" :size="12" />在线账号 <b>{{ realtime.lastMessage.value.online ?? 0 }}</b></span>
          <span><AppIcon name="users" :size="12" />运行实例 <b>{{ realtime.lastMessage.value.total_runtime ?? accounts.length }}</b></span>
          <span><AppIcon name="chat" :size="12" />今日消息 <b>{{ formatCount(realtime.lastMessage.value.messages_today ?? 0) }}</b></span>
        </div>
        <span v-else class="live-waiting"><AppIcon name="clock" :size="12" />等待实时状态数据…</span>
      </div>

      <div class="message-workspace">
        <div class="directory-panels">
          <aside class="message-panel account-panel" aria-label="账号列表">
            <div class="panel-title">
              <div>
                <span>ACCOUNTS</span>
                <b>账号</b>
              </div>
              <small>{{ accounts.length }} 个</small>
            </div>
            <div class="panel-body">
              <button
                type="button"
                class="message-nav-item"
                :class="{ active: !filters.account_id }"
                @click="selectAccount(null)"
              >
                <span class="nav-avatar all"><AppIcon name="users" :size="14" /></span>
                <span class="nav-copy">
                  <b>全部账号</b>
                  <small>查看所有账号的消息</small>
                </span>
                <span class="presence neutral">全部</span>
              </button>
              <div v-if="!accounts.length" class="panel-empty">
                <AppIcon name="bot" :size="21" />
                <b>还没有 QQ 账号</b>
                <span>添加并连接账号后，消息和群聊会出现在这里。</span>
                <el-button link type="primary" @click="$router.push('/accounts')">前往账号管理</el-button>
              </div>
              <button
                v-for="account in accounts"
                :key="account.id"
                type="button"
                class="message-nav-item"
                :class="{ active: filters.account_id === account.id }"
                @click="selectAccount(account.id)"
              >
                <span class="nav-avatar">{{ accountInitial(account) }}</span>
                <span class="nav-copy">
                  <b :title="account.name">{{ account.name }}</b>
                  <small :title="accountMeta(account)">{{ accountMeta(account) }}</small>
                </span>
                <span class="presence" :class="accountStatusTone(account.id)">
                  <AppIcon :name="accountStatusIcon(account.id)" :size="11" />
                  {{ accountStatus(account.id) }}
                </span>
              </button>
            </div>
          </aside>

          <aside class="message-panel group-panel" aria-label="群聊列表">
            <div class="panel-title">
              <div>
                <span>CONVERSATIONS</span>
                <b>会话</b>
              </div>
              <small>{{ filters.account_id ? historyDirectory.total.value : '—' }}</small>
            </div>
            <div class="panel-body">
              <el-input v-if="filters.account_id" v-model="historyGroupQuery" clearable placeholder="搜索群别名 / 内部 ID" aria-label="搜索历史会话群聊" @input="searchHistoryGroups" />
              <button
                type="button"
                class="message-nav-item"
                :class="{ active: !filters.qq_group }"
                @click="selectGroup(null)"
              >
                <span class="nav-avatar all">#</span>
                <span class="nav-copy">
                  <b>全部会话</b>
                  <small>{{ filters.account_id ? accountName(filters.account_id) + ' 的全部消息' : '选择账号后查看群聊' }}</small>
                </span>
              </button>
              <div v-if="!filters.account_id" class="panel-empty">
                <AppIcon name="inbox" :size="21" />
                <b>先选择左侧账号</b>
                <span>群聊列表会按所选账号加载。</span>
              </div>
              <div v-else-if="groupsLoading" class="panel-empty">
                <AppIcon name="loader" :size="19" class="spinning" />
                <b>正在加载群聊</b>
                <span>正在从服务端读取该账号的群列表。</span>
              </div>
              <div v-else-if="!accountGroups.length" class="panel-empty">
                <AppIcon name="users" :size="21" />
                <b>该账号暂无群聊数据</b>
                <span>请先在群聊管理同步群列表，或检查账号连接状态。</span>
                <el-button link type="primary" @click="$router.push('/groups')">前往群聊管理</el-button>
              </div>
              <button
                v-for="group in accountGroups"
                :key="group.id"
                type="button"
                class="message-nav-item"
                :class="{ active: filters.qq_group === group.group_number }"
                @click="selectGroup(group.group_number)"
              >
                <span class="nav-avatar group">#</span>
                <span class="nav-copy">
                  <b :title="groupTitle(group)">{{ groupTitle(group) }}</b>
                  <small>{{ groupNumberText(group) }} · {{ groupMemberLabel(group) }}</small>
                </span>
                <AppIcon v-if="filters.qq_group === group.group_number" name="check" :size="12" class="nav-check" />
              </button>
              <el-button v-if="accountGroups.length < historyDirectory.total.value" text :loading="groupsLoading" @click="historyDirectory.more">加载更多群聊</el-button>
              <el-button v-if="historyDirectory.error.value" text type="danger" @click="loadGroups(filters.account_id)">{{ historyDirectory.error.value }}，重试</el-button>
            </div>
          </aside>
        </div>

        <main class="message-thread" aria-label="消息内容">
          <header class="thread-header">
            <div class="thread-heading">
              <span class="thread-icon"><AppIcon name="chat" :size="16" /></span>
              <div>
                <h2 :title="threadTitle">{{ threadTitle }}</h2>
                <p>{{ threadSubtitle }}</p>
              </div>
            </div>
            <div class="thread-actions">
              <el-radio-group v-model="viewMode" size="small" aria-label="消息展示方式">
                <el-radio-button value="table">
                  <span class="view-option"><AppIcon name="logs" :size="12" />表格</span>
                </el-radio-button>
                <el-radio-button value="chat">
                  <span class="view-option"><AppIcon name="chat" :size="12" />会话</span>
                </el-radio-button>
              </el-radio-group>
              <el-button text :loading="loading" @click="load()">
                <AppIcon name="refresh" :size="13" class="btn-icon" />刷新
              </el-button>
            </div>
          </header>

          <div class="thread-toolbar">
            <div class="filter-row message-filters">
              <el-select
                v-model="filters.account_id"
                clearable
                placeholder="全部账号"
                class="w-account"
                aria-label="按账号筛选"
                @change="onAccountChange"
              >
                <el-option
                  v-for="account in accounts"
                  :key="account.id"
                  :label="`${account.name}${account.qq_number ? ' · ' + account.qq_number : ''}`"
                  :value="account.id"
                />
              </el-select>
              <el-select
                v-model="filters.qq_group"
                clearable
                filterable
                remote
                :remote-method="searchHistoryGroups"
                placeholder="全部群聊"
                class="w-group"
                aria-label="按群聊筛选"
                :disabled="!filters.account_id"
                :loading="groupsLoading"
                @change="load(1)"
              >
                <el-option
                  v-for="group in accountGroups"
                  :key="group.id"
                  :label="`${groupTitle(group)} · ${groupNumberText(group)}`"
                  :value="group.group_number"
                />
                <template #footer><el-button v-if="accountGroups.length < historyDirectory.total.value" text :loading="groupsLoading" @click.stop="historyDirectory.more">加载更多群聊</el-button></template>
              </el-select>
              <el-select
                v-model="filters.direction"
                clearable
                placeholder="消息方向"
                class="w-dir"
                aria-label="按消息方向筛选"
                @change="load(1)"
              >
                <el-option label="收到" value="in" />
                <el-option label="发出" value="out" />
              </el-select>
              <el-input
                v-model="keyword"
                clearable
                class="keyword-input"
                placeholder="搜索消息内容"
                aria-label="搜索消息内容"
                @keyup.enter="load(1)"
                @clear="load(1)"
              >
                <template #prefix><AppIcon name="search" :size="14" /></template>
              </el-input>
              <el-button type="primary" plain class="filter-submit" @click="load(1)">
                <AppIcon name="search" :size="13" class="btn-icon" />查询
              </el-button>
            </div>
          </div>

          <el-alert
            v-if="unread > 0"
            class="message-error"
            type="info"
            :closable="false"
            :title="`${unread} 条新消息`"
          >
            <template #default><el-button link type="primary" @click="load(1)">查看最新消息</el-button></template>
          </el-alert>

          <el-alert
            v-if="filters.account_id && !groupsLoading && accountGroups.length === 0"
            class="group-alert"
            type="info"
            :closable="false"
            show-icon
            title="该账号还没有群聊数据"
          >
            <template #default>
              <span>请先在群聊管理点击“同步群列表”从协议端拉取群信息，或检查账号是否已成功连接。</span>
              <el-button link type="primary" @click="$router.push('/groups')">前往群聊管理</el-button>
            </template>
          </el-alert>

          <el-alert
            v-if="loadError"
            class="message-error"
            type="error"
            :closable="false"
            show-icon
            title="消息加载失败"
          >
            <template #default>
              <span>{{ loadError }}</span>
              <el-button link type="danger" @click="load()">重试</el-button>
            </template>
          </el-alert>

          <div ref="threadBody" class="thread-body">
            <div v-if="viewMode === 'table'" class="table-wrap">
              <el-table
                v-loading="loading"
                :data="rows"
                row-key="id"
                stripe
                class="message-table"
                empty-text="暂无匹配消息，试试调整筛选条件"
              >
                <el-table-column prop="created_at" label="时间" width="166">
                  <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
                </el-table-column>
                <el-table-column label="账号" width="124">
                  <template #default="{ row }">
                    <span class="table-account" :title="accountLabel(row.account_id)">{{ accountLabel(row.account_id) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="群聊 / 私聊" width="164">
                  <template #default="{ row }">
                    <span :title="row.qq_group ? messageGroupLabel(row) : '私聊'">
                      {{ row.qq_group ? messageGroupLabel(row) : '私聊' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="方向" width="96">
                  <template #default="{ row }">
                    <span class="direction-badge" :class="row.direction === 'in' ? 'in' : 'out'">
                      <AppIcon :name="row.direction === 'in' ? 'download' : 'upload'" :size="11" />
                      {{ row.direction === 'in' ? '收到' : '发出' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="发送者" width="132">
                  <template #default="{ row }">
                    <span :title="row.sender_name || '未知发送者'">{{ row.sender_name || '—' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="消息内容" min-width="280" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="table-message">{{ row.content || '—' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="拦截" width="92">
                  <template #default="{ row }">
                    <span v-if="row.blocked" class="blocked-badge">
                      <AppIcon name="alert" :size="11" />已拦截
                    </span>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div v-else class="chat-feed-view" v-loading="loading">
              <div v-if="!rows.length && !loading" class="feed-empty">
                <AppIcon name="inbox" :size="27" />
                <b>暂无消息记录</b>
                <span>调整账号、群聊或关键词筛选，也可以直接发送一条真实消息。</span>
                <el-button v-if="can('message:send')" size="small" type="primary" plain @click="openSend">
                  <AppIcon name="send" :size="12" class="btn-icon" />发送消息
                </el-button>
              </div>
              <article
                v-for="item in rows"
                :key="item.id"
                class="feed-item"
                :class="[item.direction, { blocked: item.blocked }]"
              >
                <span class="feed-avatar">
                  <AppIcon :name="item.direction === 'out' ? 'bot' : 'user'" :size="14" />
                </span>
                <div class="feed-bubble-wrap">
                  <div class="feed-header">
                    <span class="feed-author">{{ item.sender_name || (item.direction === 'out' ? '机器人回复' : '用户') }}</span>
                    <span class="feed-target">{{ item.qq_group ? messageGroupLabel(item) : '私聊' }}</span>
                    <span class="feed-direction">
                      <AppIcon :name="item.direction === 'in' ? 'download' : 'upload'" :size="10" />
                      {{ item.direction === 'in' ? '收到' : '发出' }}
                    </span>
                    <span class="feed-time">{{ formatDate(item.created_at) }}</span>
                    <span v-if="item.blocked" class="blocked-badge">
                      <AppIcon name="alert" :size="11" />已拦截
                    </span>
                  </div>
                  <div class="feed-content">{{ item.content || '—' }}</div>
                  <p v-if="item.blocked && item.block_reason" class="blocked-reason">
                    <AppIcon name="shield" :size="11" />{{ item.block_reason }}
                  </p>
                </div>
              </article>
            </div>
          </div>

          <div class="pagination-wrap thread-pagination">
            <span>共 {{ formatCount(total) }} 条消息 · 第 {{ page }} 页</span>
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
        </main>
      </div>
    </section>

    <el-dialog v-model="sendDialog" title="发送消息" width="min(560px, calc(100vw - 28px))" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="send-form">
        <el-form-item label="发送账号" prop="account_id">
          <el-select
            v-model="form.account_id"
            placeholder="选择 QQ 账号"
            style="width: 100%"
            @change="onSendAccountChange"
          >
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="accountOptionLabel(account)"
              :value="account.id"
              :disabled="!sendableAccount(account)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="发送目标" prop="target">
          <el-radio-group v-model="targetType" aria-label="选择发送目标类型">
            <el-radio-button value="group">QQ 群</el-radio-button>
            <el-radio-button value="private">私聊用户</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="targetType === 'group'" label="选择群聊" prop="target">
          <el-select
            v-model="form.target"
            filterable
            remote
            :remote-method="searchSendGroups"
            placeholder="先选账号，再选择群聊"
            :loading="sendDirectory.loading.value"
            :disabled="!form.account_id"
            style="width: 100%"
          >
            <el-option
              v-for="group in sendDirectory.items.value"
              :key="group.id"
              :label="`${groupTitle(group)} · ${groupNumberText(group)}`"
              :value="String(group.group_number)"
            />
            <template #footer><el-button v-if="sendDirectory.items.value.length < sendDirectory.total.value" text :loading="sendDirectory.loading.value" @click.stop="sendDirectory.more">加载更多群聊</el-button></template>
          </el-select>
          <el-button v-if="sendDirectory.error.value" link type="danger" @click="searchSendGroups('')">加载失败，重试</el-button>
        </el-form-item>
        <el-form-item v-else label="已登记私聊联系人（内部映射 ID）" prop="target">
          <el-select v-model="form.target" filterable remote :remote-method="searchContacts" :loading="contactsDirectory.loading.value" :disabled="!form.account_id" placeholder="选择已与该机器人私聊的联系人" style="width: 100%">
            <el-option v-for="contact in contactsDirectory.items.value" :key="contact.id" :label="`${contact.display_name || '私聊联系人'} · 内部映射 ID ${contact.id}`" :value="String(contact.id)" />
            <template #footer><el-button v-if="contactsDirectory.items.value.length < contactsDirectory.total.value" text @click.stop="contactsDirectory.more">加载更多联系人</el-button></template>
          </el-select>
          <el-button v-if="contactsDirectory.error.value" link type="danger" @click="searchContacts('')">加载失败，重试</el-button>
        </el-form-item>
        <el-form-item label="消息内容" prop="content">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="5"
            resize="none"
            maxlength="4000"
            show-word-limit
            placeholder="输入要发送的消息"
          />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="消息会通过所选账号的协议端真实发送，并写入消息记录。"
      />
      <template #footer>
        <el-button @click="sendDialog = false">取消</el-button>
        <el-button type="primary" :loading="sending" :disabled="!canSend" @click="send">
          <AppIcon name="send" :size="14" class="btn-icon" />发送
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import { groupTitle, groupNumberText } from '../groupDisplay'
import { useStatusStore } from '../stores/status'
import { usePermissions } from '../composables/usePermissions'
import { useAccountDirectory } from '../composables/useAccountDirectory'

const status = useStatusStore()
const { state: socketState, payload: socketPayload } = storeToRefs(status)
const realtime = { state: socketState, lastMessage: socketPayload, reconnect: status.reconnect }
const { can } = usePermissions()

const rows = ref<any[]>([])
const accounts = ref<any[]>([])
const groupPage = async (id: number, page: number, keyword: string) => (await api.get('/groups', { params: { account_id: id, page, page_size: 50, keyword: keyword || undefined } })).data
const historyDirectory = useAccountDirectory<any>(groupPage)
const sendDirectory = useAccountDirectory<any>(groupPage)
const contactsDirectory = useAccountDirectory<any>(async (id, page, keyword) => (await api.get('/messages/contacts', { params: { account_id: id, page, page_size: 50, keyword: keyword || undefined } })).data)
const accountGroups = historyDirectory.items
const groupsLoading = historyDirectory.loading
const historyGroupQuery = ref('')
const threadBody = ref<HTMLElement>()
const unread = ref(0)
const lastContentSync = ref<number | null>(null)
let requestSequence = 0
let latestMessageId = 0
let activeScope = ''
let polling = false
let pollTimer: ReturnType<typeof setInterval> | undefined
const loading = ref(false)
const sending = ref(false)
const sendDialog = ref(false)
const formRef = ref<any>()
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const keyword = ref('')
const targetType = ref<'group' | 'private'>('group')
const viewMode = ref<'table' | 'chat'>('table')
const loadError = ref('')
const filters = reactive({
  account_id: null as number | null,
  qq_group: null as number | null,
  direction: '',
})
const form = reactive({
  account_id: null as number | null,
  target: '',
  content: '',
})
const rules = {
  account_id: [{ required: true, message: '请选择账号', trigger: 'change' }],
  target: [{ required: true, message: '请选择或输入目标', trigger: 'change' }],
  content: [{ required: true, message: '请输入消息内容', trigger: 'blur' }],
}

const realtimeLabel = computed(() => ({
  open: '状态连接在线',
  connecting: '连接中',
  reconnecting: '重连中',
  closed: '连接已断开',
  error: '连接异常',
} as Record<string, string>)[realtime.state.value] || '等待连接')
const canSend = computed(() => can('message:send') && Boolean(form.account_id && sendableAccount(accounts.value.find(account => account.id === form.account_id), targetType.value)))

const selectedAccount = computed(() => accounts.value.find(account => account.id === filters.account_id) || null)
const selectedGroup = computed(() => accountGroups.value.find(group => group.group_number === filters.qq_group) || null)
const threadTitle = computed(() => {
  if (selectedGroup.value) return groupTitle(selectedGroup.value)
  if (selectedAccount.value) return selectedAccount.value.name
  return '全部消息'
})
const threadSubtitle = computed(() => {
  const scope: string[] = []
  if (selectedAccount.value) scope.push(selectedAccount.value.name)
  if (selectedGroup.value) scope.push(groupNumberText(selectedGroup.value))
  if (filters.direction) scope.push(filters.direction === 'in' ? '收到' : '发出')
  if (keyword.value.trim()) scope.push(`关键词“${keyword.value.trim()}”`)
  const prefix = scope.length ? `${scope.join(' · ')} · ` : ''
  return `${prefix}共 ${formatCount(total.value)} 条结果`
})

function errorText(error: any) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : '请求失败，请检查后端连接后重试'
}

function formatCount(value: number | string | null | undefined) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function accountLabel(id: number) {
  const account = accounts.value.find(item => item.id === id)
  return account ? account.name : `账号 ${id}`
}

function accountName(id: number) {
  return accounts.value.find(item => item.id === id)?.name || `账号 ${id}`
}

function accountInitial(account: any) {
  return String(account.name || 'Q').slice(0, 1).toUpperCase()
}

function accountMeta(account: any) {
  const groupCount = Number(account.group_count || 0)
  const groupText = groupCount > 0 ? `${groupCount} 个群` : '暂无群数据'
  return `${account.qq_number || '未绑定 QQ'} · ${groupText}`
}

function accountOptionLabel(account: any) {
  const number = account.qq_number ? ` · ${account.qq_number}` : ''
  const runtime = accountState(account.id) === 'online' ? '在线' : '离线'
  return `${account.name}${number} · ${runtime}`
}

function sendableAccount(account: any, type = targetType.value) {
  const key = type === 'private' ? 'send_private_message' : 'send_group_message'
  return Boolean(account && accountState(account.id) === 'online' && account.capabilities?.[key])
}

function liveAccountState(id: number) {
  return realtime.lastMessage.value?.accounts?.find(account => account.id === id)?.state
}

function accountState(id: number) {
  const account = accounts.value.find(item => item.id === id)
  return liveAccountState(id) || account?.runtime_state || 'stopped'
}

function accountStatus(id: number) {
  return ({
    online: '在线',
    starting: '启动中',
    stopping: '停止中',
    error: '异常',
    stopped: '离线',
  } as Record<string, string>)[accountState(id)] || '离线'
}

function accountStatusTone(id: number) {
  const state = accountState(id)
  if (state === 'online') return 'online'
  if (state === 'error') return 'error'
  if (state === 'starting' || state === 'stopping') return 'pending'
  return 'offline'
}

function accountStatusIcon(id: number) {
  const state = accountState(id)
  if (state === 'online') return 'wifi'
  if (state === 'error') return 'alert'
  if (state === 'starting' || state === 'stopping') return 'loader'
  return 'server-off'
}

function groupMemberLabel(group: any) {
  return Number(group.member_count) > 0 ? `${group.member_count} 人` : '人数未知'
}

function messageGroupLabel(item: any) {
  return item.group_display_name || (item.group_display_number ? `QQ群 ${item.group_display_number}` : '未标注群号')
}

async function selectAccount(id: number | null) {
  filters.account_id = id
  filters.qq_group = null
  await Promise.all([loadGroups(id), load(1)])
}

async function selectGroup(group: number | null) {
  filters.qq_group = group
  await load(1)
}

async function loadGroups(accountId: number | null) {
  historyGroupQuery.value = ''
  await historyDirectory.load(accountId)
}

const searchHistoryGroups = (query: string) => historyDirectory.load(filters.account_id, query)
const searchSendGroups = (query: string) => sendDirectory.load(form.account_id, query)
const searchContacts = (query: string) => contactsDirectory.load(form.account_id, query)

async function onAccountChange() {
  filters.qq_group = null
  await Promise.all([loadGroups(filters.account_id), load(1)])
}

function onSendAccountChange() {
  form.target = ''
  void sendDirectory.load(form.account_id)
  void contactsDirectory.load(form.account_id)
}

function messageParams() {
  return { keyword: keyword.value || undefined, direction: filters.direction || undefined, account_id: filters.account_id || undefined, qq_group: filters.qq_group || undefined }
}

async function load(targetPage?: number) {
  const sequence = ++requestSequence
  if (targetPage) page.value = targetPage
  unread.value = 0
  const scope = JSON.stringify(messageParams())
  if (scope !== activeScope) { latestMessageId = 0; activeScope = scope }
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get('/messages', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        ...messageParams(),
      },
    })
    if (sequence !== requestSequence) return
    rows.value = data.items || []
    total.value = data.total || 0
    latestMessageId = Math.max(latestMessageId, ...rows.value.map(row => row.id), 0)
    lastContentSync.value = Date.now()
  } catch (error) {
    if (sequence === requestSequence) loadError.value = errorText(error)
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function refreshIncremental() {
  if (polling || loading.value || document.hidden) return
  polling = true
  const sequence = requestSequence
  const cursor = latestMessageId
  try {
    const { data } = await api.get('/messages', { params: { ...messageParams(), after_id: cursor, page_size: 200, page: 1 } })
    if (sequence !== requestSequence) return
    const incoming = data.items || []
    if (incoming.length) {
      latestMessageId = Math.max(cursor, ...incoming.map((item: any) => item.id))
      unread.value += incoming.length
      total.value += incoming.length
      if (page.value === 1) {
        const top = threadBody.value?.scrollTop || 0
        const height = threadBody.value?.scrollHeight || 0
        rows.value = [...new Map([...incoming, ...rows.value].map(item => [item.id, item])).values()].sort((a, b) => b.id - a.id).slice(0, pageSize.value)
        await nextTick()
        if (threadBody.value && top > 0) threadBody.value.scrollTop = top + Math.max(0, threadBody.value.scrollHeight - height)
      }
    }
    lastContentSync.value = Date.now()
  } catch {
    // Keep visible history and its cursor; the next poll retries the same batch.
  } finally {
    polling = false
  }
}

function openSend() {
  if (!can('message:send')) return
  sendDialog.value = true
  if (!form.account_id && accounts.value.length === 1) {
    form.account_id = accounts.value[0].id
    onSendAccountChange()
  }
}

async function send() {
  if (!canSend.value || sending.value) return
  await formRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    sending.value = true
    try {
      const payload: any = { account_id: form.account_id, content: form.content }
      payload[targetType.value === 'group' ? 'qq_group' : 'user_id'] = Number(form.target)
      const { data } = await api.post('/messages/send', payload)
      ElMessage.success(data.message || '消息已发送')
      sendDialog.value = false
      form.target = ''
      form.content = ''
      await load(1)
    } finally {
      sending.value = false
    }
  })
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

onMounted(async () => {
  status.acquire()
  pollTimer = setInterval(refreshIncremental, 5000)
  try {
    const [accountResponse] = await Promise.all([api.get('/accounts'), load()])
    accounts.value = accountResponse.data
  } catch {
    /* 失败信息由全局请求拦截器展示，页面保留重试入口 */
  }
})
watch(targetType, () => { form.target = '' })
watch(socketState, (value, previous) => {
  if (value === 'open' && previous !== 'open') {
    void api.get('/accounts').then(response => { accounts.value = response.data })
    void refreshIncremental()
  }
})
onBeforeUnmount(() => { requestSequence += 1; if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.messages-page {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.btn-icon {
  margin-right: 5px;
}
.message-shell {
  min-width: 0;
  padding: 0;
  overflow: hidden;
}
.workspace-statusbar {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
}
.live-state {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
}
.live-state > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
}
.live-state b {
  color: var(--text-2);
  font-size: 10px;
  font-weight: 600;
}
.live-state small {
  color: var(--text-4);
  font-size: 8.5px;
}
.live-state.open b {
  color: var(--success);
}
.live-state.error b,
.live-state.closed b {
  color: var(--danger);
}
.live-state.connecting b,
.live-state.reconnecting b {
  color: var(--warning);
}
.live-metrics {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-left: auto;
}
.live-metrics span,
.live-waiting {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-4);
  font-size: 9.5px;
  white-space: nowrap;
}
.live-metrics b {
  color: var(--text-2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.live-waiting {
  margin-left: auto;
}
.message-workspace {
  display: grid;
  grid-template-columns: minmax(0, 430px) minmax(0, 1fr);
  min-width: 0;
  height: clamp(600px, calc(100vh - 258px), 880px);
  min-height: 560px;
}
.directory-panels {
  display: grid;
  grid-template-columns: minmax(160px, 0.8fr) minmax(210px, 1fr);
  min-width: 0;
  min-height: 0;
  border-right: 1px solid var(--line);
}
.message-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  background: var(--surface-2);
}
.account-panel {
  border-right: 1px solid var(--line);
}
.panel-title {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 54px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line-soft);
}
.panel-title > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.panel-title span {
  color: var(--text-4);
  font: 600 7.5px/1.3 var(--font-mono);
  letter-spacing: 0.12em;
}
.panel-title b {
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
}
.panel-title small {
  color: var(--text-4);
  font-size: 9px;
  white-space: nowrap;
}
.panel-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: 7px;
}
.message-nav-item {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: var(--text-2);
  text-align: left;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease), border-color var(--duration-fast) var(--ease);
}
.message-nav-item:hover {
  border-color: var(--line);
  background: var(--surface-3);
}
.message-nav-item.active {
  border-color: var(--brand-line);
  background: var(--brand-soft);
}
.nav-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  flex: none;
  place-items: center;
  border: 1px solid var(--cyan-line);
  border-radius: 8px;
  background: var(--cyan-soft);
  color: var(--cyan);
  font: 600 10px var(--font-mono);
}
.nav-avatar.all {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.nav-avatar.group {
  border-color: var(--line);
  background: var(--surface);
  color: var(--text-3);
}
.nav-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.nav-copy b,
.nav-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nav-copy b {
  color: var(--text-2);
  font-size: 10px;
  font-weight: 550;
}
.nav-copy small {
  color: var(--text-4);
  font-size: 8.5px;
}
.message-nav-item.active .nav-copy b {
  color: var(--text);
  font-weight: 600;
}
.presence {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 3px;
  color: var(--text-4);
  font-size: 8px;
  white-space: nowrap;
}
.presence.online {
  color: var(--success);
}
.presence.error {
  color: var(--danger);
}
.presence.pending {
  color: var(--warning);
}
.presence.pending .app-icon {
  animation: spin 1s linear infinite;
}
.nav-check {
  flex: none;
  color: var(--brand-strong);
}
.panel-empty {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 5px;
  padding: 20px 10px;
  color: var(--text-4);
  text-align: center;
}
.panel-empty .app-icon {
  color: var(--text-4);
}
.panel-empty b {
  color: var(--text-3);
  font-size: 10px;
  font-weight: 600;
}
.panel-empty span {
  color: var(--text-4);
  font-size: 8.5px;
  line-height: 1.55;
}
.panel-empty .el-button {
  margin-top: 2px;
  font-size: 9px;
}
.message-thread {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  background: var(--surface);
}
.thread-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}
.thread-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
}
.thread-icon {
  display: grid;
  width: 32px;
  height: 32px;
  flex: none;
  place-items: center;
  border: 1px solid var(--brand-line);
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.thread-heading > div {
  min-width: 0;
}
.thread-heading h2 {
  overflow: hidden;
  margin: 0 0 2px;
  color: var(--text);
  font-size: 12px;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-heading p {
  overflow: hidden;
  margin: 0;
  color: var(--text-4);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.view-option {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.thread-toolbar {
  flex: none;
  padding: 11px 16px;
  border-bottom: 1px solid var(--line-soft);
  background: color-mix(in srgb, var(--surface-2) 46%, transparent);
}
.message-filters {
  width: 100%;
  align-items: center;
}
.w-account {
  width: 170px;
}
.w-group {
  width: 200px;
}
.w-dir {
  width: 112px;
}
.keyword-input {
  width: auto;
  min-width: 170px;
  flex: 1;
}
.filter-submit {
  flex: none;
}
.group-alert,
.message-error {
  flex: none;
  margin: 10px 16px 0;
}
.group-alert :deep(.el-alert__content),
.message-error :deep(.el-alert__content) {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.thread-body {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
}
.table-wrap {
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow: auto;
}
.message-table {
  min-width: 940px;
}
.table-account,
.table-message {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.table-account {
  color: var(--text-2);
}
.table-message {
  color: var(--text-2);
}
.direction-badge,
.blocked-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 22px;
  padding: 0 7px;
  border: 1px solid var(--line);
  border-radius: 99px;
  font-size: 8.5px;
  font-weight: 550;
  white-space: nowrap;
}
.direction-badge.in {
  border-color: var(--cyan-line);
  background: var(--cyan-soft);
  color: var(--cyan);
}
.direction-badge.out {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.blocked-badge {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}
.chat-feed-view {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 15px;
  overflow-y: auto;
  padding: 18px;
  background: var(--surface-inset);
}
.feed-empty {
  display: flex;
  min-height: 360px;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--text-4);
  text-align: center;
}
.feed-empty .app-icon {
  color: var(--text-4);
}
.feed-empty b {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}
.feed-empty span {
  max-width: 400px;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.65;
}
.feed-item {
  display: flex;
  width: fit-content;
  max-width: min(84%, 760px);
  align-items: flex-start;
  gap: 9px;
}
.feed-item.out {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.feed-avatar {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  border: 1px solid var(--cyan-line);
  border-radius: 9px;
  background: var(--cyan-soft);
  color: var(--cyan);
}
.feed-item.out .feed-avatar {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.feed-bubble-wrap {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.feed-item.out .feed-bubble-wrap {
  align-items: flex-end;
}
.feed-header {
  display: flex;
  max-width: 100%;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  color: var(--text-4);
  font-size: 8.5px;
}
.feed-author {
  color: var(--text-2);
  font-weight: 600;
}
.feed-target,
.feed-direction {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface-2);
  color: var(--text-3);
}
.feed-time {
  color: var(--text-4);
}
.feed-content {
  max-width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 4px 11px 11px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 11px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.feed-item.out .feed-content {
  border-color: var(--brand-line);
  border-radius: 11px 4px 11px 11px;
  background: var(--brand-soft);
  color: var(--text);
}
.feed-item.blocked .feed-content {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--text);
}
.blocked-reason {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin: 0;
  color: var(--danger);
  font-size: 8.5px;
  line-height: 1.5;
}
.feed-item.out .blocked-reason {
  text-align: right;
}
.thread-pagination {
  flex: none;
  padding: 11px 16px;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 42%, transparent);
}
.send-form :deep(.el-form-item:last-child) {
  margin-bottom: 12px;
}
.spinning {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1200px) {
  .message-workspace {
    grid-template-columns: minmax(0, 360px) minmax(0, 1fr);
  }
  .directory-panels {
    grid-template-columns: 145px minmax(0, 1fr);
  }
  .presence {
    display: none;
  }
  .w-account {
    width: 150px;
  }
  .w-group {
    width: 170px;
  }
}
@media (max-width: 900px) {
  .message-workspace {
    display: flex;
    height: auto;
    min-height: 0;
    flex-direction: column;
  }
  .directory-panels {
    display: flex;
    min-height: 0;
    overflow-x: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
    scroll-snap-type: x proximity;
  }
  .message-panel {
    flex: 0 0 min(330px, 84vw);
    max-height: 276px;
    scroll-snap-align: start;
  }
  .account-panel {
    border-right: 1px solid var(--line);
  }
  .panel-body {
    max-height: 222px;
  }
  .presence {
    display: inline-flex;
  }
  .message-thread {
    min-height: 580px;
  }
  .thread-body {
    min-height: 390px;
  }
  .chat-feed-view {
    min-height: 390px;
  }
  .live-metrics {
    margin-left: 0;
  }
}
@media (max-width: 700px) {
  .workspace-statusbar {
    align-items: flex-start;
    flex-wrap: wrap;
    padding: 10px 12px;
  }
  .live-metrics,
  .live-waiting {
    width: 100%;
    margin-left: 0;
  }
  .live-metrics {
    gap: 8px 12px;
  }
  .thread-header {
    align-items: flex-start;
    flex-direction: column;
    padding: 12px;
  }
  .thread-actions {
    width: 100%;
    justify-content: space-between;
  }
  .thread-toolbar {
    padding: 10px 12px;
  }
  .message-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 7px;
  }
  .message-filters .el-select,
  .message-filters .el-input {
    width: 100%;
  }
  .keyword-input {
    grid-column: 1 / -1;
    min-width: 0;
  }
  .filter-submit {
    grid-column: 1 / -1;
    width: 100%;
  }
  .group-alert,
  .message-error {
    margin: 9px 12px 0;
  }
  .chat-feed-view {
    padding: 12px;
  }
  .feed-item {
    max-width: 92%;
  }
  .thread-pagination {
    padding: 10px 12px;
    align-items: flex-start;
    flex-direction: column;
  }
  .thread-pagination :deep(.el-pagination) {
    flex-wrap: wrap;
    row-gap: 6px;
  }
}
@media (max-width: 520px) {
  .page-heading .heading-actions {
    width: 100%;
  }
  .page-heading .heading-actions .el-button {
    flex: 1;
    margin-left: 0;
  }
  .message-panel {
    flex-basis: min(292px, 88vw);
  }
  .thread-body {
    min-height: 460px;
  }
  .feed-header {
    gap: 4px;
  }
  .feed-target,
  .feed-direction {
    max-width: 100%;
  }
  .send-form :deep(.el-radio-group) {
    display: flex;
  }
  .send-form :deep(.el-radio-button) {
    flex: 1;
  }
  .send-form :deep(.el-radio-button__inner) {
    width: 100%;
    padding-inline: 8px;
  }
}
</style>
