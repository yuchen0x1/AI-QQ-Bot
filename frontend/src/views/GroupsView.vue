<template>
  <div class="groups-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">COMMUNITY OPERATIONS</div>
        <h1>群聊管理</h1>
        <p>管理各 QQ 账号关联群聊、成员、群聊策略和群管理操作；官方机器人仅提供平台映射 ID。</p>
      </div>
      <div class="heading-actions">
        <el-button :loading="loading" @click="load()">
          <AppIcon name="refresh" :size="14" class="button-icon" />刷新
        </el-button>
        <el-button v-if="can('group:manage') && accounts.some(account => supports(account.id, 'get_group_list'))" type="primary" @click="syncDialog = true">
          <AppIcon name="users" :size="14" class="button-icon" />同步群列表
        </el-button>
      </div>
    </div>

    <div class="group-context-note">
      <span class="group-context-icon"><AppIcon name="info" :size="16" /></span>
      <div>
        <b>官方机器人群聊说明</b>
        <p>
          官方平台不提供真实 QQ 群号、全量群列表与部分群管理接口。群聊会在机器人首次收到群内 @ 消息后建档，本页展示平台映射 ID；禁言、踢人、改群名等能力以服务端返回的协议能力为准。
        </p>
      </div>
    </div>

    <section class="surface resource-surface group-resource-surface">
      <div class="resource-toolbar">
        <div class="filter-row group-filter-row">
          <el-input
            v-model="keyword"
            class="group-keyword"
            clearable
            placeholder="搜索群名 / 群号"
            @keyup.enter="load(1)"
            @clear="load(1)"
          >
            <template #prefix><AppIcon name="search" :size="14" /></template>
          </el-input>
          <el-select
            v-model="accountFilter"
            class="group-account-filter"
            clearable
            placeholder="筛选 QQ 账号"
            @change="load(1)"
          >
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="`${account.name} · ${account.qq_number || account.app_id || '未登录'}`"
              :value="account.id"
            />
          </el-select>
          <el-button type="primary" @click="load(1)">
            <AppIcon name="search" :size="14" class="button-icon" />查询
          </el-button>
          <el-button v-if="hasGroupFilters" text type="primary" @click="clearGroupFilters">
            <AppIcon name="filter" :size="14" class="button-icon" />清除筛选
          </el-button>
        </div>

        <div class="group-toolbar-actions">
          <span v-if="!loading" class="group-result-count">共 {{ total }} 个群聊</span>
          <el-button :loading="loading" @click="load()">
            <AppIcon name="refresh" :size="14" class="button-icon" />刷新
          </el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="groups"
        row-key="id"
        stripe
        class="group-table"
      >
        <el-table-column label="群聊" min-width="320">
          <template #default="scope">
            <div class="group-identity">
              <span class="group-avatar" :class="groupTone(scope.row)">
                {{ groupInitial(scope.row) }}
              </span>
              <div class="group-identity-copy">
                <b>{{ groupTitle(scope.row) }}</b>
                <div class="group-id-line">
                  <span class="group-id-chip">{{ groupNumberText(scope.row) }}</span>
                  <span
                    class="group-id-note"
                    title="官方机器人不显示真实 QQ 群号；此 ID 用于推送规则与平台内部映射"
                  >
                    平台映射 ID
                  </span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="绑定账号" min-width="160">
          <template #default="scope">
            <div class="group-account-cell">
              <AppIcon name="bot" :size="14" />
              <span>{{ scope.row.account_name || '未绑定账号' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="成员" width="112">
          <template #default="scope">
            <div class="group-member-count">
              <b>{{ formatNumber(scope.row.member_count) }}</b>
              <small v-if="scope.row.max_member_count">
                上限 {{ formatNumber(scope.row.max_member_count) }}
              </small>
              <small v-else>平台未提供上限</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="策略" min-width="205">
          <template #default="scope">
            <div class="group-badges">
              <span
                class="group-badge"
                :class="scope.row.settings?.ai_enabled ? 'is-on' : 'is-off'"
              >
                <AppIcon name="sparkles" :size="11" />
                AI {{ scope.row.settings?.ai_enabled ? '启用' : '关闭' }}
              </span>
              <span
                class="group-badge"
                :class="`mode-${scope.row.settings?.moderation_mode || 'off'}`"
              >
                <AppIcon name="shield" :size="11" />
                审核 {{ modeLabel(scope.row.settings?.moderation_mode) }}
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="最后同步" width="170">
          <template #default="scope">
            <span :class="{ 'group-muted': !scope.row.last_synced_at }">
              {{ scope.row.last_synced_at ? formatDate(scope.row.last_synced_at) : '尚未同步' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="238" fixed="right">
          <template #default="scope">
            <div class="row-actions group-actions">
              <el-button link type="primary" @click="openMembers(scope.row)">成员</el-button>
              <el-button v-if="can('group:manage')" link type="primary" @click="openSettings(scope.row)">策略</el-button>
              <el-dropdown
                v-if="can('group:manage') && groupActions.some(action => supports(scope.row.account_id, action.capability))"
                trigger="click"
                @command="(command: string) => groupAction(command, scope.row)"
              >
                <el-button link type="warning" aria-label="打开群管理操作">
                  管理操作
                  <el-icon class="dropdown-arrow"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <template v-for="action in groupActions" :key="action.key">
                      <el-dropdown-item v-if="supports(scope.row.account_id, action.capability)" :command="action.key">{{ action.label }}</el-dropdown-item>
                    </template>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="empty-inline group-empty">
            <span class="group-empty-icon"><AppIcon name="users" :size="25" /></span>
            <strong>{{ hasGroupFilters ? '没有匹配的群聊' : '还没有已建档的群聊' }}</strong>
            <span>
              把机器人拉进群并在群里 @ 它发一条消息，群会自动建档。官方机器人没有全量群列表接口，也不显示真实 QQ 群号；这里是平台映射 ID，推送时可在「推送规则」里下拉选择。
            </span>
            <div class="group-empty-actions">
              <el-button v-if="hasGroupFilters" @click="clearGroupFilters">
                <AppIcon name="filter" :size="14" class="button-icon" />清除筛选
              </el-button>
              <el-button v-if="can('group:manage') && accounts.some(account => supports(account.id, 'get_group_list'))" type="primary" @click="syncDialog = true">
                <AppIcon name="users" :size="14" class="button-icon" />同步群列表
              </el-button>
            </div>
          </div>
        </template>
      </el-table>

      <div class="pagination-wrap">
        <span>共 {{ total }} 个群聊</span>
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

    <el-dialog
      v-model="membersDialog"
      :title="`群成员 · ${activeGroup?.name || activeGroup?.group_number || ''}`"
      width="min(1040px, calc(100vw - 28px))"
      class="groups-dialog members-dialog"
    >
      <template #header>
        <div class="dialog-heading">
          <span class="dialog-heading-icon"><AppIcon name="users" :size="17" /></span>
          <div>
            <h3>群成员 · {{ activeGroup ? groupTitle(activeGroup) : '' }}</h3>
            <p>
              <span class="group-id-chip">{{ activeGroup ? groupNumberText(activeGroup) : '—' }}</span>
              <span>平台映射 ID</span>
              <span class="dialog-dot">·</span>
              <span>{{ memberTotal }} 位成员</span>
            </p>
          </div>
        </div>
      </template>

      <div class="member-toolbar">
        <el-input
          v-model="memberKeyword"
          class="member-search"
          clearable
          placeholder="搜索昵称或 QQ 号"
          @keyup.enter="loadMembers(1)"
          @clear="loadMembers(1)"
        >
          <template #prefix><AppIcon name="search" :size="14" /></template>
        </el-input>
        <div class="member-toolbar-actions">
          <el-button @click="loadMembers(1)">
            <AppIcon name="search" :size="14" class="button-icon" />查询
          </el-button>
          <el-button v-if="can('group:manage') && supports(activeGroup?.account_id, 'get_group_member_list')" type="primary" :loading="membersLoading" @click="syncMembers">
            <AppIcon name="refresh" :size="14" class="button-icon" />同步成员
          </el-button>
        </div>
      </div>

      <div class="dialog-table-wrap">
        <el-table v-loading="membersLoading" :data="members" row-key="id" stripe>
          <el-table-column label="成员" min-width="230">
            <template #default="scope">
              <div class="member-identity">
                <span class="member-avatar">{{ memberInitial(scope.row) }}</span>
                <div>
                  <b>{{ memberDisplayName(scope.row) }}</b>
                  <small class="mono">QQ {{ scope.row.user_id }}</small>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="群名片" min-width="135">
            <template #default="scope">{{ scope.row.card || '—' }}</template>
          </el-table-column>
          <el-table-column label="身份" width="102">
            <template #default="scope">
              <el-tag :type="roleTagType(scope.row.role)" effect="dark" class="member-role-tag">
                <AppIcon :name="roleIcon(scope.row.role)" :size="11" class="tag-icon" />
                {{ roleLabel(scope.row.role) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="活跃" min-width="155">
            <template #default="scope">
              <div class="member-activity">
                <b>{{ formatNumber(scope.row.message_count) }} 条消息</b>
                <small>{{ scope.row.last_active_at ? formatDate(scope.row.last_active_at) : '暂无活跃记录' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="警告" width="82">
            <template #default="scope">
              <span class="warning-count" :class="{ 'has-warning': Number(scope.row.warn_count) > 0 }">
                {{ scope.row.warn_count ?? 0 }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="170">
            <template #default="scope">
              <div class="member-statuses">
                <span
                  v-for="status in memberStatuses(scope.row)"
                  :key="status.label"
                  class="member-status"
                  :class="`tone-${status.tone}`"
                  :title="status.title"
                >
                  <AppIcon :name="status.icon" :size="11" />
                  {{ status.label }}
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="122" fixed="right">
            <template #default="scope">
              <el-dropdown
                v-if="can('group:manage')"
                trigger="click"
                @command="(command: string) => memberAction(command, scope.row)"
              >
                <el-button link type="primary" aria-label="打开成员管理操作">
                  管理
                  <el-icon class="dropdown-arrow"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <template v-for="action in memberActions" :key="action.key">
                      <el-dropdown-item v-if="supports(activeGroup?.account_id, action.capability)" :command="action.key">{{ action.label }}</el-dropdown-item>
                    </template>
                    <el-dropdown-item command="blacklist">切换黑名单</el-dropdown-item>
                    <el-dropdown-item command="whitelist">切换白名单</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-table-column>

          <template #empty>
            <div class="empty-inline group-empty member-empty">
              <span class="group-empty-icon"><AppIcon name="user" :size="23" /></span>
              <strong>{{ memberKeyword.trim() ? '没有匹配的成员' : '尚未同步群成员' }}</strong>
              <span>
                点击「同步成员」从当前账号拉取平台已感知的群成员；官方平台不保证提供完整成员列表。
              </span>
              <div class="group-empty-actions">
                <el-button v-if="memberKeyword.trim()" @click="clearMemberSearch">
                  <AppIcon name="close" :size="14" class="button-icon" />清除搜索
                </el-button>
                <el-button v-if="can('group:manage') && supports(activeGroup?.account_id, 'get_group_member_list')" type="primary" @click="syncMembers">
                  <AppIcon name="refresh" :size="14" class="button-icon" />同步成员
                </el-button>
              </div>
            </div>
          </template>
        </el-table>
      </div>

      <div class="pagination-wrap dialog-pagination">
        <span>共 {{ memberTotal }} 位成员</span>
        <el-pagination
          v-model:current-page="memberPage"
          v-model:page-size="memberPageSize"
          :total="memberTotal"
          :page-sizes="[20, 50, 100]"
          layout="sizes, prev, pager, next"
          @current-change="loadMembers"
          @size-change="loadMembers(1)"
        />
      </div>
    </el-dialog>

    <el-dialog
      v-model="settingsDialog"
      title="群聊独立策略"
      width="min(760px, calc(100vw - 28px))"
      class="groups-dialog settings-dialog"
    >
      <template #header>
        <div class="dialog-heading">
          <span class="dialog-heading-icon"><AppIcon name="settings" :size="17" /></span>
          <div>
            <h3>群聊独立策略 · {{ activeGroup ? groupTitle(activeGroup) : '' }}</h3>
            <p>此配置仅作用于当前群聊，保存后立即通过接口持久化。</p>
          </div>
        </div>
      </template>

      <el-form :model="settings" label-position="top" class="group-settings-form">
        <section class="settings-block">
          <div class="settings-block-head">
            <span><AppIcon name="sparkles" :size="15" /></span>
            <div><h4>AI 回复</h4><p>控制是否启用群聊 AI、触发方式与上下文范围。</p></div>
          </div>
          <div class="settings-grid">
            <el-form-item label="启用群聊 AI">
              <el-switch v-model="settings.ai_enabled" aria-label="启用群聊 AI" />
            </el-form-item>
            <el-form-item label="必须 @机器人 才回复">
              <el-switch v-model="settings.require_at_for_ai" aria-label="必须 @机器人 才回复" />
            </el-form-item>
            <el-form-item label="AI 模型 ID">
              <el-input-number
                v-model="settings.ai_model_id"
                :min="1"
                placeholder="留空使用默认模型"
              />
            </el-form-item>
            <el-form-item label="上下文消息条数">
              <el-input-number v-model="settings.ai_context_limit" :min="1" :max="50" />
            </el-form-item>
          </div>
          <el-form-item label="群聊专属提示词">
            <el-input
              v-model="settings.ai_prompt"
              type="textarea"
              :rows="3"
              resize="vertical"
              placeholder="可定义该群 AI 的角色与行为"
            />
          </el-form-item>
        </section>

        <section class="settings-block">
          <div class="settings-block-head">
            <span><AppIcon name="shield" :size="15" /></span>
            <div><h4>内容审核</h4><p>设置自动管理模式、频率限制与群聊违禁词。</p></div>
          </div>
          <div class="settings-grid">
            <el-form-item label="自动管理模式">
              <el-select v-model="settings.moderation_mode">
                <el-option label="关闭" value="off" />
                <el-option label="普通" value="normal" />
                <el-option label="严格" value="strict" />
              </el-select>
            </el-form-item>
            <el-form-item label="每分钟频率限制">
              <el-input-number v-model="settings.rate_limit_per_minute" :min="0" :max="500" />
            </el-form-item>
          </div>
          <el-form-item label="违禁关键词（JSON 数组）">
            <el-input
              v-model="bannedWordsText"
              type="textarea"
              :rows="2"
              resize="vertical"
              placeholder='["广告词","敏感词"]'
            />
          </el-form-item>
        </section>

        <section class="settings-block">
          <div class="settings-block-head">
            <span><AppIcon name="chat" :size="15" /></span>
            <div><h4>入群欢迎</h4><p>成员加入群聊时自动发送的欢迎消息。</p></div>
          </div>
          <div class="settings-grid settings-grid-single">
            <el-form-item label="启用入群欢迎">
              <el-switch v-model="settings.welcome_enabled" aria-label="启用入群欢迎" />
            </el-form-item>
          </div>
          <el-form-item label="入群欢迎模板">
            <el-input
              v-model="settings.welcome_template"
              type="textarea"
              :rows="2"
              resize="vertical"
            />
          </el-form-item>
        </section>
      </el-form>

      <template #footer>
        <el-button @click="settingsDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveSettings">
          <AppIcon name="check" :size="14" class="button-icon" />保存策略
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="syncDialog"
      title="同步群聊列表"
      width="min(480px, calc(100vw - 28px))"
      class="groups-dialog sync-dialog"
    >
      <template #header>
        <div class="dialog-heading">
          <span class="dialog-heading-icon"><AppIcon name="refresh" :size="17" /></span>
          <div>
            <h3>同步群聊列表</h3>
            <p>从在线账号同步平台已感知的群聊。</p>
          </div>
        </div>
      </template>

      <div class="sync-note">
        <AppIcon name="info" :size="15" />
        <span>
          官方机器人没有全量群列表接口；同步只会拉取平台已感知的群聊，未出现的群请先在群内 @ 机器人一次。
        </span>
      </div>

      <el-form label-position="top">
        <el-form-item label="选择 QQ 账号">
          <el-select v-model="syncAccountId" placeholder="请选择在线账号">
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="`${account.name} · ${account.qq_number || account.app_id || '未登录'} · ${account.runtime_state === 'online' ? '在线' : '离线'}`"
              :value="account.id"
              :disabled="!supports(account.id, 'get_group_list')"
            />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="syncDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="syncing"
          :disabled="!syncAccountId"
          @click="syncGroups"
        >
          <AppIcon name="refresh" :size="14" class="button-icon" />开始同步
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { api } from '../api'
import { groupTitle, groupNumberText } from '../groupDisplay'
import AppIcon from '../components/AppIcon.vue'
import { usePermissions } from '../composables/usePermissions'
const { can } = usePermissions()

const groups = ref<any[]>([])
const accounts = ref<any[]>([])
const members = ref<any[]>([])
const loading = ref(false)
const membersLoading = ref(false)
const saving = ref(false)
const syncing = ref(false)
const membersDialog = ref(false)
const settingsDialog = ref(false)
const syncDialog = ref(false)
const activeGroup = ref<any>()
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const memberPage = ref(1)
const memberPageSize = ref(20)
const memberTotal = ref(0)
const memberKeyword = ref('')
const keyword = ref('')
const accountFilter = ref<number>()
const syncAccountId = ref<number>()
const bannedWordsText = ref('')
const settings = reactive<any>({})
const groupActions = [
  { key: 'ban_all', label: '开启全体禁言', capability: 'set_group_whole_ban' },
  { key: 'unban_all', label: '解除全体禁言', capability: 'set_group_whole_ban' },
  { key: 'set_announcement', label: '发布群公告', capability: 'set_group_announce' },
  { key: 'set_group_name', label: '修改群名称', capability: 'set_group_name' },
  { key: 'sync', label: '同步群成员', capability: 'get_group_member_list' },
]
const memberActions = [
  { key: 'mute', label: '禁言 10 分钟', capability: 'set_group_ban' },
  { key: 'unmute', label: '解除禁言', capability: 'set_group_ban' },
  { key: 'set_card', label: '设置群名片', capability: 'set_group_card' },
  { key: 'set_admin', label: '设置管理员', capability: 'set_group_admin' },
  { key: 'unset_admin', label: '取消管理员', capability: 'set_group_admin' },
  { key: 'kick', label: '踢出成员', capability: 'set_group_kick' },
]
function supports(accountId: number | undefined, capability: string) {
  const account = accounts.value.find(account => account.id === accountId)
  return Boolean(account?.runtime_state === 'online' && account.capabilities?.[capability])
}

const hasGroupFilters = computed(() => Boolean(keyword.value.trim() || accountFilter.value))

async function load(target?: number) {
  if (target) page.value = target
  loading.value = true
  try {
    const { data } = await api.get('/groups', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        keyword: keyword.value || undefined,
        account_id: accountFilter.value || undefined,
      },
    })
    groups.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

async function loadMembers(target?: number) {
  if (target) memberPage.value = target
  if (!activeGroup.value) return
  membersLoading.value = true
  try {
    const { data } = await api.get(`/groups/${activeGroup.value.id}/members`, {
      params: {
        page: memberPage.value,
        page_size: memberPageSize.value,
        keyword: memberKeyword.value || undefined,
      },
    })
    members.value = data.items || []
    memberTotal.value = data.total || 0
  } finally {
    membersLoading.value = false
  }
}

function clearGroupFilters() {
  keyword.value = ''
  accountFilter.value = undefined
  load(1)
}

function clearMemberSearch() {
  memberKeyword.value = ''
  loadMembers(1)
}

async function openMembers(group: any) {
  activeGroup.value = group
  membersDialog.value = true
  memberPage.value = 1
  await loadMembers()
}

function openSettings(group: any) {
  activeGroup.value = group
  Object.assign(settings, {
    ai_enabled: false,
    ai_model_id: null,
    ai_prompt: '',
    require_at_for_ai: true,
    ai_context_limit: 12,
    welcome_enabled: false,
    welcome_template: '',
    member_change_notify: true,
    moderation_mode: 'off',
    banned_words: [],
    rate_limit_per_minute: 30,
    max_repeat_chars: 4,
    auto_warn_threshold: 3,
    auto_mute_seconds: 600,
    auto_kick: false,
    announcement: '',
    ...(group.settings || {}),
  })
  bannedWordsText.value = JSON.stringify(settings.banned_words || [], null, 2)
  settingsDialog.value = true
}

async function saveSettings() {
  if (!can('group:manage')) return
  let banned: any
  try {
    banned = JSON.parse(bannedWordsText.value || '[]')
    if (!Array.isArray(banned)) throw new Error()
  } catch {
    ElMessage.error('违禁关键词必须是合法 JSON 数组')
    return
  }
  saving.value = true
  try {
    await api.put(`/groups/${activeGroup.value.id}/settings`, {
      ...settings,
      banned_words: banned,
    })
    ElMessage.success('群聊策略已保存')
    settingsDialog.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function syncMembers() {
  if (!activeGroup.value || !can('group:manage') || !supports(activeGroup.value.account_id, 'get_group_member_list')) return
  membersLoading.value = true
  try {
    const { data } = await api.post(`/groups/${activeGroup.value.id}/sync`)
    ElMessage.success(data.detail || '同步完成')
    await loadMembers()
  } finally {
    membersLoading.value = false
  }
}

async function syncGroups() {
  if (!can('group:manage') || !supports(syncAccountId.value, 'get_group_list')) return
  syncing.value = true
  try {
    const { data } = await api.post(`/groups/sync/${syncAccountId.value}`)
    ElMessage.success(data.detail || '同步完成')
    syncDialog.value = false
    await load()
  } finally {
    syncing.value = false
  }
}

async function groupAction(action: string, group: any) {
  if (!can('group:manage') || !supports(group.account_id, groupActions.find(item => item.key === action)?.capability || '')) return
  if (action === 'sync') {
    activeGroup.value = group
    await syncMembers()
    return
  }
  if (action === 'set_announcement' || action === 'set_group_name') {
    try {
      const { value } = await ElMessageBox.prompt(
        action === 'set_announcement' ? '输入群公告内容' : '输入新的群名称',
        action === 'set_announcement' ? '发布群公告' : '修改群名称',
        {
          inputType: action === 'set_announcement' ? 'textarea' : 'text',
          inputPlaceholder: action === 'set_announcement' ? '群公告' : '群名称',
        },
      )
      await api.post(`/groups/${group.id}/action`, { action, value })
      ElMessage.success(action === 'set_announcement' ? '群公告已发布' : '群名称已更新')
      await load()
    } catch {
      /* cancelled */
    }
    return
  }
  try {
    await ElMessageBox.confirm(
      action === 'ban_all' ? '开启全体禁言？' : '解除全体禁言？',
      '确认操作',
      { type: 'warning' },
    )
    const { data } = await api.post(`/groups/${group.id}/action`, { action })
    ElMessage.success(data.message || '操作已完成')
  } catch {
    /* cancelled */
  }
}

async function memberAction(action: string, member: any) {
  if (!can('group:manage')) return
  const group = activeGroup.value
  if (!['blacklist', 'whitelist'].includes(action) && !supports(group?.account_id, memberActions.find(item => item.key === action)?.capability || '')) return
  if (action === 'blacklist' || action === 'whitelist') {
    const body = action === 'blacklist'
      ? { is_blacklisted: !member.is_blacklisted }
      : { is_whitelisted: !member.is_whitelisted }
    const { data } = await api.post(`/groups/${group.id}/members/${member.user_id}/flags`, body)
    ElMessage.success('成员标记已更新')
    Object.assign(member, data)
    return
  }

  let value: any
  const body: any = { action, user_id: member.user_id }
  if (action === 'mute') body.duration_seconds = 600
  if (action === 'set_card') {
    try {
      const result = await ElMessageBox.prompt('输入新的群名片', '设置群名片', {
        inputValue: member.card || member.nickname || '',
      })
      value = result.value
    } catch {
      return
    }
    body.value = value
  }
  if (action === 'kick') {
    try {
      await ElMessageBox.confirm(
        `确定将 ${member.nickname || member.user_id} 移出群聊？`,
        '确认踢人',
        { type: 'warning' },
      )
    } catch {
      return
    }
  }
  if (action === 'set_admin' || action === 'unset_admin') {
    try {
      await ElMessageBox.confirm(
        action === 'set_admin' ? '确认设置该成员为管理员？' : '确认取消该成员管理员？',
        '确认操作',
        { type: 'warning' },
      )
    } catch {
      return
    }
  }
  try {
    const { data } = await api.post(`/groups/${group.id}/action`, body)
    ElMessage.success(data.message || '操作已完成')
    if (action === 'kick') await loadMembers()
  } catch {
    /* cancelled or handled by the API interceptor */
  }
}

function groupInitial(group: any) {
  const title = String(groupTitle(group) || '#').trim()
  return title.slice(0, 1).toUpperCase() || '#'
}

function groupTone(group: any) {
  return `tone-${Math.abs(Number(group?.id || 0)) % 4}`
}

function memberInitial(member: any) {
  const name = String(memberDisplayName(member) || '#').trim()
  return name.slice(0, 1).toUpperCase() || '#'
}

function memberDisplayName(member: any) {
  return member.card || member.nickname || `成员 ${member.user_id}`
}

function isMuted(member: any) {
  return Boolean(member.muted_until && new Date(member.muted_until).getTime() > Date.now())
}

function memberStatuses(member: any) {
  const statuses: Array<{ label: string; tone: string; icon: string; title?: string }> = []
  if (member.is_blacklisted) {
    statuses.push({ label: '黑名单', tone: 'danger', icon: 'shield' })
  }
  if (member.is_whitelisted) {
    statuses.push({ label: '白名单', tone: 'success', icon: 'check-circle' })
  }
  if (isMuted(member)) {
    statuses.push({
      label: '禁言中',
      tone: 'warning',
      icon: 'timer',
      title: `禁言至 ${formatDate(member.muted_until)}`,
    })
  }
  if (!statuses.length) {
    statuses.push({ label: '正常', tone: 'neutral', icon: 'check' })
  }
  return statuses
}

function roleLabel(value: string) {
  return ({ owner: '群主', admin: '管理员', member: '成员' } as Record<string, string>)[value] || value
}

function roleTagType(value: string): any {
  return ({ owner: 'warning', admin: 'primary', member: 'info' } as Record<string, string>)[value] || 'info'
}

function roleIcon(value: string) {
  return ({ owner: 'star', admin: 'shield', member: 'user' } as Record<string, string>)[value] || 'user'
}

function modeLabel(value?: string) {
  return ({ off: '关闭', normal: '普通', strict: '严格' } as Record<string, string>)[value || 'off'] || '关闭'
}

function formatNumber(value: number | string | null | undefined) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

onMounted(async () => {
  const [accountResponse] = await Promise.all([api.get('/accounts'), load()])
  accounts.value = accountResponse.data
  syncAccountId.value = accounts.value.find((account: any) => account.runtime_state === 'online')?.id
})
</script>

<style scoped>
.groups-page {
  min-width: 0;
}

.button-icon {
  margin-right: 5px;
}

.group-context-note {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid var(--brand-line);
  border-radius: var(--radius-md);
  background:
    linear-gradient(110deg, color-mix(in srgb, var(--brand-soft) 58%, transparent), transparent 72%),
    var(--surface);
  box-shadow: var(--shadow-xs);
}

.group-context-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.group-context-note b {
  display: block;
  margin-bottom: 2px;
  color: var(--text);
  font-size: 11px;
  font-weight: 620;
}

.group-context-note p {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.group-resource-surface {
  border-radius: var(--radius-lg);
}

.group-resource-surface:hover {
  border-color: var(--line-strong);
}

.resource-toolbar {
  background: color-mix(in srgb, var(--surface-2) 62%, transparent);
}

.group-filter-row {
  gap: 8px;
}

.group-keyword {
  width: 260px;
}

.group-account-filter {
  width: 220px;
}

.group-toolbar-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.group-result-count {
  color: var(--text-3);
  font: 550 10px/1 var(--font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.group-table :deep(.el-table__fixed-right) {
  box-shadow: -14px 0 26px color-mix(in srgb, var(--canvas) 18%, transparent);
}

.group-identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.group-avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 13px;
  font-weight: 700;
}

.group-avatar.tone-1 {
  border-color: var(--cyan-line);
  background: var(--cyan-soft);
  color: var(--cyan);
}

.group-avatar.tone-2 {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.group-avatar.tone-3 {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}

.group-identity-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.group-identity-copy > b {
  overflow: hidden;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-id-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.group-id-chip {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface-inset);
  color: var(--text-3);
  font: 500 9.5px/1.4 var(--font-mono);
  overflow-wrap: anywhere;
}

.group-id-note {
  color: var(--text-4);
  font-size: 9px;
}

.group-account-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--text-2);
  font-size: 10.5px;
}

.group-account-cell .app-icon {
  color: var(--text-4);
}

.group-member-count {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-member-count b {
  color: var(--text);
  font-size: 12px;
  font-weight: 620;
  font-variant-numeric: tabular-nums;
}

.group-member-count small {
  color: var(--text-4);
  font-size: 9px;
}

.group-badges {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.group-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 7px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 550;
  white-space: nowrap;
}

.group-badge.is-on {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.group-badge.is-off {
  color: var(--text-4);
}

.group-badge.mode-normal {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}

.group-badge.mode-strict {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.group-muted {
  color: var(--text-4);
}

.row-actions {
  align-items: center;
  justify-content: flex-start;
  gap: 3px 9px;
  flex-wrap: wrap;
  white-space: normal;
}

.group-actions :deep(.el-button) {
  margin-left: 0;
  padding-inline: 0;
}

.dropdown-arrow {
  margin-left: 3px;
  font-size: 11px;
}

.group-empty {
  min-height: 210px;
  gap: 9px;
  max-width: 680px;
  margin: 0 auto;
}

.group-empty-icon {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border: 1px solid var(--brand-line);
  border-radius: 13px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.group-empty strong {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 620;
}

.group-empty > span:not(.group-empty-icon) {
  max-width: 620px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.7;
}

.group-empty-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pagination-wrap {
  background: color-mix(in srgb, var(--surface-2) 42%, transparent);
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.pagination-wrap :deep(.el-pagination) {
  max-width: 100%;
  flex-wrap: wrap;
  row-gap: 6px;
}

:global(.groups-dialog) {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 28px);
  max-height: calc(100dvh - 28px);
  margin: 14px auto !important;
}

:global(.groups-dialog .el-dialog__header) {
  padding: 20px 24px 0;
}

:global(.groups-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 24px 8px;
}

:global(.groups-dialog .el-dialog__footer) {
  flex: none;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 45%, transparent);
}

.dialog-heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding-right: 34px;
  min-width: 0;
}

.dialog-heading-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.dialog-heading > div {
  min-width: 0;
}

.dialog-heading h3 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 14px;
  font-weight: 650;
  letter-spacing: -0.015em;
  overflow-wrap: anywhere;
}

.dialog-heading p {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.55;
}

.dialog-dot {
  color: var(--text-4);
}

.member-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.member-search {
  width: 280px;
}

.member-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dialog-table-wrap {
  min-width: 0;
  overflow: hidden;
}

.member-identity {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.member-avatar {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 650;
}

.member-identity > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.member-identity b {
  overflow: hidden;
  color: var(--text);
  font-size: 11px;
  font-weight: 580;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-identity small {
  color: var(--text-4);
  font-size: 9px;
}

.member-role-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tag-icon {
  margin-right: 1px;
}

.member-activity {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.member-activity b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 550;
  font-variant-numeric: tabular-nums;
}

.member-activity small {
  color: var(--text-4);
  font-size: 9px;
}

.warning-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 20px;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font: 600 9.5px/1 var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.warning-count.has-warning {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}

.member-statuses {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.member-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 20px;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9px;
  font-weight: 550;
  white-space: nowrap;
}

.member-status.tone-danger {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}

.member-status.tone-warning {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}

.member-status.tone-success {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.member-status.tone-neutral {
  color: var(--text-4);
}

.member-empty {
  min-height: 190px;
}

.dialog-pagination {
  margin: 10px -24px -8px;
  border-top: 1px solid var(--line);
}

.group-settings-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.settings-block {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--surface-2) 58%, transparent);
}

.settings-block-head {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 12px;
}

.settings-block-head > span {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.settings-block-head h4 {
  margin: 0 0 2px;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 620;
}

.settings-block-head p {
  margin: 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.55;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

.settings-grid-single {
  grid-template-columns: 1fr;
}

.group-settings-form :deep(.el-form-item) {
  min-width: 0;
  margin-bottom: 14px;
}

.group-settings-form :deep(.el-form-item__label) {
  color: var(--text-3);
  font-size: 10px;
  font-weight: 560;
}

.group-settings-form :deep(.el-select),
.group-settings-form :deep(.el-input-number) {
  width: 100%;
}

.group-settings-form :deep(.el-textarea__inner) {
  line-height: 1.65;
}

.sync-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 14px;
  padding: 10px 11px;
  border: 1px solid var(--info-line);
  border-radius: var(--radius-sm);
  background: var(--info-soft);
  color: var(--info);
  font-size: 10px;
  line-height: 1.65;
}

.sync-note .app-icon {
  margin-top: 1px;
  flex: none;
}

.sync-dialog :deep(.el-select) {
  width: 100%;
}

@media (max-width: 840px) {
  .resource-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .group-filter-row {
    width: 100%;
  }

  .group-keyword,
  .group-account-filter {
    width: 100%;
  }

  .group-toolbar-actions {
    justify-content: space-between;
    width: 100%;
  }
}

@media (max-width: 700px) {
  .group-context-note {
    gap: 9px;
    padding: 11px 12px;
  }

  .member-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .member-search {
    width: 100%;
  }

  .member-toolbar-actions {
    width: 100%;
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }

  .dialog-pagination {
    margin-inline: -18px;
  }

  .group-empty {
    padding-inline: 14px;
  }
}

@media (max-width: 600px) {
  .pagination-wrap {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
