<template>
  <router-view v-if="$route.path === '/login'" />
  <div v-else-if="$route.query.forbidden === '1'" class="forbidden-page">
    <el-result icon="warning" :title="t('forbidden.title')" :sub-title="t('forbidden.subtitle')">
      <template #extra><el-button type="primary" @click="$router.replace('/')">{{ t('forbidden.back') }}</el-button></template>
    </el-result>
  </div>
  <div v-else class="app-shell">
    <button v-if="mobileNavOpen" class="sidebar-scrim" type="button" :aria-label="t('shell.closeNav')" @click="mobileNavOpen = false"></button>

    <aside id="primary-navigation" class="sidebar" :class="{ collapsed: collapsed && !isMobile, 'mobile-open': mobileNavOpen }">
      <router-link class="brand" to="/" :aria-label="'QBOT AI ' + t('shell.console')">
        <span class="brand-mark"><AppIcon name="bot" :size="21" :stroke-width="1.8" /></span>
        <span v-if="!collapsed || isMobile" class="brand-copy">
          <strong>QBOT<span> AI</span></strong>
          <small>INTELLIGENT BOT OPS</small>
        </span>
      </router-link>

      <div class="nav-scroll">
        <div v-for="group in navGroups" :key="group.key" class="nav-group">
          <p v-if="!collapsed || isMobile" class="nav-group-label">{{ group.label }}</p>
          <el-tooltip
            v-for="item in group.items"
            :key="item.path"
            :content="item.title"
            placement="right"
            :show-after="220"
            :disabled="!collapsed || isMobile"
          >
            <router-link :to="item.path" class="nav-item">
              <AppIcon :name="item.icon" :size="17" />
              <span class="nav-item-label">{{ item.title }}</span>
            </router-link>
          </el-tooltip>
        </div>
      </div>

      <div class="sidebar-bottom">
        <el-tooltip :content="socketLabel" placement="right" :disabled="!collapsed || isMobile">
          <div class="side-live" :class="`socket-${socket.state.value}`" role="status" aria-live="polite" :aria-label="socketLabel">
            <i></i><span>{{ socketLabel }}</span>
          </div>
        </el-tooltip>
        <el-tooltip :content="collapsed ? t('shell.expand') : t('shell.collapse')" placement="right" :disabled="!collapsed || isMobile">
          <el-button text class="collapse-button" :aria-label="collapsed ? t('shell.expand') : t('shell.collapse')" @click="toggleCollapsed">
            <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="16" />
            <span v-if="!collapsed || isMobile">{{ t('shell.collapse') }}</span>
          </el-button>
        </el-tooltip>
      </div>
    </aside>

    <main class="main-shell">
      <header class="topbar">
        <div class="topbar-left">
          <el-button class="mobile-nav-toggle icon-button" text :aria-label="mobileNavOpen ? t('shell.closeNav') : t('shell.openNav')" aria-controls="primary-navigation" :aria-expanded="mobileNavOpen" @click="mobileNavOpen = !mobileNavOpen">
            <AppIcon :name="mobileNavOpen ? 'close' : 'menu'" :size="19" />
          </el-button>
          <div class="crumb">
            <span>{{ t('shell.console') }}</span>
            <span class="crumb-sep">/</span>
            <strong>{{ currentTitle }}</strong>
          </div>
        </div>

        <button class="command-trigger" type="button" :aria-label="t('shell.search')" @click="paletteOpen = true">
          <AppIcon name="search" :size="15" />
          <span>{{ t('shell.searchPlaceholder') }}</span>
          <kbd>{{ shortcutLabel }}</kbd>
        </button>

        <div class="top-actions">
          <div class="system-pill" :class="`socket-${socket.state.value}`" role="status" aria-live="polite">
            <span class="pulse-dot"></span><span>{{ socketLabel }}</span>
          </div>
          <el-button v-if="updateAvailable" type="warning" plain size="small" class="update-pill" @click="router.push('/settings#updates')">
            {{ t('shell.newVersion') }} {{ latestVersion }}
          </el-button>
          <el-tooltip :content="t('shell.refresh')" placement="bottom">
            <el-button class="icon-button" text :aria-label="t('shell.refresh')" @click="refreshPage">
              <AppIcon name="refresh" :size="16" />
            </el-button>
          </el-tooltip>
          <el-popover v-if="canViewLogs" placement="bottom-end" :width="372" trigger="click" popper-class="notification-popper" @show="loadNotifications">
            <template #reference>
              <div class="notification-wrap">
                <el-button class="icon-button" text :aria-label="t('shell.notifications')">
                  <AppIcon name="bell" :size="16" />
                </el-button>
                <span v-if="notificationCount" class="notification-dot">{{ notificationCount > 9 ? '9+' : notificationCount }}</span>
              </div>
            </template>
            <div class="notify-panel">
              <div class="notify-head">
                <div><strong>{{ t('shell.notifications') }}</strong><small>{{ t('shell.notificationsHint') }}</small></div>
                <el-button text size="small" :loading="notificationsLoading" @click="loadNotifications">{{ t('shell.refresh') }}</el-button>
              </div>
              <div v-if="notifications.length" class="notify-list">
                <button v-for="item in notifications" :key="item.id" type="button" class="notify-item" @click="openNotification(item)">
                  <span class="notify-dot" :class="item.level"></span>
                  <span class="notify-copy">
                    <b>{{ item.message }}</b>
                    <small>{{ item.categoryLabel }} · {{ formatTime(item.created_at) }}</small>
                  </span>
                  <AppIcon name="chevron-right" :size="14" />
                </button>
              </div>
              <div v-else class="notify-empty">
                <AppIcon name="check-circle" :size="22" />
                <span>{{ t('shell.noNotifications') }}</span>
              </div>
              <div class="notify-foot">
                <el-button text type="primary" size="small" @click="goLogs">{{ t('shell.viewAllLogs') }}<AppIcon name="arrow-right" :size="13" style="margin-left:5px" /></el-button>
              </div>
            </div>
          </el-popover>
          <el-tooltip :content="themeName === 'dark' ? t('shell.themeLight') : t('shell.themeDark')" placement="bottom">
            <el-button class="icon-button" text :aria-label="themeName === 'dark' ? t('shell.themeLight') : t('shell.themeDark')" @click="toggleTheme">
              <AppIcon :name="themeName === 'dark' ? 'sun' : 'moon'" :size="16" />
            </el-button>
          </el-tooltip>
          <label class="locale-picker">
            <span class="sr-only">{{ t('shell.locale') }}</span>
            <select :value="localeSetting" :aria-label="t('shell.locale')" @change="changeLocale">
              <option value="auto">{{ t('shell.auto') }}</option>
              <option value="zh-CN">{{ t('shell.chinese') }}</option>
              <option value="en-US">{{ t('shell.english') }}</option>
            </select>
          </label>
          <el-dropdown trigger="click" @command="handleUserCommand">
            <div class="user-chip" tabindex="0" role="button" :aria-label="username">
              <el-avatar :size="27" class="user-avatar">{{ username.slice(0, 1).toUpperCase() }}</el-avatar>
              <span class="user-name">{{ username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">
                  <AppIcon name="key" :size="15" />{{ t('shell.changePassword') }}
                </el-dropdown-item>
                <el-dropdown-item command="theme">
                  <AppIcon :name="themeName === 'dark' ? 'sun' : 'moon'" :size="15" />{{ themeName === 'dark' ? t('shell.themeLight') : t('shell.themeDark') }}
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>
                  <AppIcon name="logout" :size="15" />{{ t('shell.logout') }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <section class="page-wrap">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" :key="`${route.path}:${refreshKey}`" />
          </transition>
        </router-view>
      </section>

      <footer class="page-footer">
        <span>{{ panelTitle }} · v{{ appVersion }}</span>
        <span class="footer-realtime"><i :class="`socket-led ${socket.state.value}`"></i>{{ socketLabel }} · {{ t('shell.footer') }}</span>
      </footer>
    </main>

    <el-dialog v-model="guideVisible" :title="t('guide.title')" width="min(600px, calc(100vw - 28px))" :before-close="closeGuide" class="guide-dialog">
      <div class="dialog-prose">
        <p>{{ t('guide.body') }}</p>
      </div>
      <div class="guide-steps">
        <span><i>01</i>连接机器人</span>
        <span><i>02</i>配置 AI</span>
        <span><i>03</i>授权 GitHub</span>
        <span><i>04</i>验证通知</span>
      </div>
      <template #footer>
        <el-button @click="dismissGuide">{{ t('guide.later') }}</el-button>
        <el-button type="primary" @click="startGuide">{{ t('guide.start') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdDialogVisible" :title="t('password.title')" width="min(430px, calc(100vw - 28px))" destroy-on-close>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-position="top">
        <el-form-item :label="t('password.current')" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password :placeholder="t('password.currentPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('password.new')" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password :placeholder="t('password.newPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('password.confirm')" prop="confirm_password">
          <el-input v-model="pwdForm.confirm_password" type="password" show-password :placeholder="t('password.confirmPlaceholder')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialogVisible = false">{{ t('password.cancel') }}</el-button>
        <el-button type="primary" :loading="pwdSubmitting" @click="submitChangePassword">{{ t('password.submit') }}</el-button>
      </template>
    </el-dialog>

    <CommandPalette v-model="paletteOpen" :items="commandItems" @select="runCommand" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import AppIcon from './components/AppIcon.vue'
import CommandPalette, { type CommandItem } from './components/CommandPalette.vue'
import { api } from './api'
import { useStatusStore } from './stores/status'
import { localeSetting, setLocaleSetting, t } from './i18n'
import { themeName, toggleTheme } from './theme'
import { version as appVersion } from '../package.json'
import { readUpdateReminder, shouldRemindUpdate, subscribeUpdateReminder } from './updateReminder'

const route = useRoute()
const router = useRouter()
const status = useStatusStore()
const { state: socketState } = storeToRefs(status)
const socket = { state: socketState }

const guideVisible = ref(false)
const pwdDialogVisible = ref(false)
const pwdSubmitting = ref(false)
const pwdFormRef = ref<any>()
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })

const collapsed = ref(false)
try {
  collapsed.value = localStorage.getItem('qbot_sidebar_collapsed') === '1'
} catch { /* private mode */ }
const mobileNavOpen = ref(false)
const isMobile = ref(false)
const refreshKey = ref(0)
const username = ref('管理员')
const userPermissions = ref<string[]>([])
const updateAvailable = ref(false)
const latestVersion = ref('')
const panelTitle = ref('QBot AI 管理平台')
const paletteOpen = ref(false)
const notifications = ref<any[]>([])
const notificationsLoading = ref(false)

let mobileQuery: MediaQueryList | undefined
const updateViewport = (event?: MediaQueryListEvent) => {
  isMobile.value = event?.matches ?? mobileQuery?.matches ?? false
  if (!isMobile.value) mobileNavOpen.value = false
}

const socketLabel = computed(() => ({
  connecting: t('shell.connecting'),
  reconnecting: t('shell.reconnecting'),
  open: t('shell.realtime'),
  closed: t('shell.closed'),
  error: t('shell.error'),
} as Record<string, string>)[socketState.value] || t('shell.system'))

const shortcutLabel = computed(() => /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K')

type NavItem = { path: string; titleKey: string; icon: string; permission: string }
const NAV_GROUPS: { key: string; labelKey: string; items: NavItem[] }[] = [
  {
    key: 'overview',
    labelKey: 'nav.group.overview',
    items: [{ path: '/', titleKey: 'nav.dashboard', icon: 'dashboard', permission: 'account:view' }],
  },
  {
    key: 'operations',
    labelKey: 'nav.group.operations',
    items: [
      { path: '/accounts', titleKey: 'nav.accounts', icon: 'bot', permission: 'account:view' },
      { path: '/groups', titleKey: 'nav.groups', icon: 'users', permission: 'group:view' },
      { path: '/requests', titleKey: 'nav.requests', icon: 'inbox', permission: 'request:view' },
      { path: '/messages', titleKey: 'nav.messages', icon: 'chat', permission: 'message:view' },
    ],
  },
  {
    key: 'intelligence',
    labelKey: 'nav.group.intelligence',
    items: [
      { path: '/ai', titleKey: 'nav.ai', icon: 'sparkles', permission: 'ai:view' },
      { path: '/github', titleKey: 'nav.github', icon: 'branch', permission: 'github:view' },
      { path: '/push-rules', titleKey: 'nav.pushRules', icon: 'send', permission: 'push:view' },
      { path: '/push-records', titleKey: 'nav.pushRecords', icon: 'history', permission: 'push:view' },
      { path: '/tasks', titleKey: 'nav.tasks', icon: 'timer', permission: 'task:view' },
    ],
  },
  {
    key: 'platform',
    labelKey: 'nav.group.platform',
    items: [
      { path: '/email', titleKey: 'nav.email', icon: 'mail', permission: 'system:manage' },
      { path: '/plugins', titleKey: 'nav.plugins', icon: 'puzzle', permission: 'plugin:view' },
      { path: '/logs', titleKey: 'nav.logs', icon: 'logs', permission: 'log:view' },
      { path: '/system', titleKey: 'nav.system', icon: 'activity', permission: 'system:view' },
      { path: '/settings', titleKey: 'nav.settings', icon: 'settings', permission: '' },
    ],
  },
  {
    key: 'support',
    labelKey: 'nav.group.support',
    items: [{ path: '/help', titleKey: 'nav.help', icon: 'book', permission: '' }],
  },
]

const can = (permission: string) => !permission || userPermissions.value.includes('*') || userPermissions.value.includes(permission)

const navGroups = computed(() => NAV_GROUPS
  .map((group) => ({
    ...group,
    label: t(group.labelKey),
    items: group.items.filter((item) => can(item.permission)).map((item) => ({ ...item, title: t(item.titleKey) })),
  }))
  .filter((group) => group.items.length))

const currentTitle = computed(() => {
  for (const group of NAV_GROUPS) {
    const match = group.items.find((item) => item.path === route.path)
    if (match) return t(match.titleKey)
  }
  return String(route.meta.title || t('nav.dashboard'))
})

const canViewLogs = computed(() => can('log:view'))
const notificationCount = computed(() => notifications.value.length)

const commandItems = computed<CommandItem[]>(() => {
  const items: CommandItem[] = []
  for (const group of navGroups.value) {
    for (const item of group.items) {
      items.push({
        id: `nav:${item.path}`,
        title: item.title,
        description: `${group.label} · ${item.path}`,
        icon: item.icon,
        group: t('shell.commandNavigate'),
        meta: '↵',
        keywords: item.path,
      })
    }
  }
  items.push({
    id: 'action:refresh',
    title: t('shell.refresh'),
    description: t('shell.refreshDesc'),
    icon: 'refresh',
    group: t('shell.commandActions'),
  })
  items.push({
    id: 'action:theme',
    title: themeName.value === 'dark' ? t('shell.themeLight') : t('shell.themeDark'),
    description: t('shell.themeDesc'),
    icon: themeName.value === 'dark' ? 'sun' : 'moon',
    group: t('shell.commandActions'),
  })
  if (updateAvailable.value) {
    items.push({
      id: 'action:update',
      title: `${t('shell.newVersion')} ${latestVersion.value}`,
      description: t('shell.updateDesc'),
      icon: 'zap',
      group: t('shell.commandActions'),
      meta: 'U',
    })
  }
  items.push({
    id: 'action:logout',
    title: t('shell.logout'),
    description: t('shell.logoutDesc'),
    icon: 'logout',
    group: t('shell.commandActions'),
  })
  return items
})

async function rememberGuide() {
  try { await api.put('/onboarding', { seen: true, step: 0 }) } catch { /* non-blocking */ }
}
async function dismissGuide() { await rememberGuide(); guideVisible.value = false }
async function closeGuide(done: () => void) { await rememberGuide(); done() }
async function startGuide() { await dismissGuide(); router.push('/help') }

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem('qbot_sidebar_collapsed', collapsed.value ? '1' : '0') } catch { /* private mode */ }
}

function refreshPage() {
  refreshKey.value++
  ElMessage.success(t('shell.refreshed'))
}

function changeLocale(event: Event) {
  setLocaleSetting((event.target as HTMLSelectElement).value)
}

function formatTime(value: string) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const CATEGORY_LABEL: Record<string, string> = {
  system: '系统', account: '账号', ai: 'AI', github: 'GitHub', push: '推送',
  task: '任务', plugin: '插件', email: '邮件', auth: '认证', qqbot: 'QQ 机器人',
}

async function loadNotifications() {
  if (!canViewLogs.value || notificationsLoading.value) return
  notificationsLoading.value = true
  try {
    const [errors, warnings] = await Promise.all([
      api.get('/logs', { params: { level: 'ERROR', page: 1, page_size: 4 } }),
      api.get('/logs', { params: { level: 'WARNING', page: 1, page_size: 4 } }),
    ])
    const rows = [...(errors.data.items || []), ...(warnings.data.items || [])]
      .map((row: any) => ({
        id: `log:${row.id}`,
        level: String(row.level || 'info').toLowerCase(),
        message: row.message,
        categoryLabel: CATEGORY_LABEL[row.category] || row.category || '系统',
        created_at: row.created_at,
      }))
      .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 6)
    if (updateAvailable.value) {
      rows.unshift({
        id: 'update',
        level: 'warning',
        message: `${t('shell.newVersion')} v${latestVersion.value} ${t('shell.available')}`,
        categoryLabel: '更新',
        created_at: '',
      })
    }
    notifications.value = rows
  } catch {
    /* keep the previous list */
  } finally {
    notificationsLoading.value = false
  }
}

function openNotification(item: any) {
  if (item.id === 'update') router.push('/settings#updates')
  else router.push('/logs')
}

function goLogs() { router.push('/logs') }

let releaseStatus: (() => void) | undefined
function startStatus() {
  if (route.path === '/login' || releaseStatus) return
  releaseStatus = status.acquire()
}
function stopStatus() {
  releaseStatus?.()
  releaseStatus = undefined
  status.stop()
}

async function loadProfile() {
  try {
    const { data } = await api.get('/auth/me')
    username.value = data.username || '管理员'
    userPermissions.value = data.permissions || []
    const guide = await api.get('/onboarding')
    guideVisible.value = !guide.data.progress?.seen && route.path !== '/help'
  } catch { /* route guard handles auth */ }
}

let updateTimer: ReturnType<typeof setTimeout> | undefined
let updateSession = 0
let updateCandidate: { version: string; available: boolean; interval: number } | undefined
let releaseUpdateReminder: (() => void) | undefined
let notifyTimer: ReturnType<typeof setInterval> | undefined
function refreshUpdateReminder() {
  const candidate = updateCandidate
  updateAvailable.value = route.path !== '/login' && Boolean(candidate && shouldRemindUpdate(
    candidate.version, candidate.available, candidate.interval, readUpdateReminder(),
  ))
}
function stopUpdateChecks() {
  updateSession++
  clearTimeout(updateTimer)
  updateCandidate = undefined
  updateAvailable.value = false
}
async function checkForUpdateSilently() {
  if (route.path === '/login' || !userPermissions.value.some((p) => p === '*' || p === 'system:view')) return
  clearTimeout(updateTimer)
  const session = ++updateSession
  let interval = 5
  try {
    const { data } = await api.get('/system/update')
    if (session !== updateSession) return
    if (Number.isFinite(Number(data.check_interval_minutes))) interval = Math.max(0, Number(data.check_interval_minutes))
    latestVersion.value = String(data?.latest_version || '')
    updateCandidate = { version: latestVersion.value, available: Boolean(data?.update_available), interval }
    refreshUpdateReminder()
  } catch { /* offline */ }
  if (session === updateSession && interval > 0) {
    updateTimer = setTimeout(checkForUpdateSilently, Math.min(interval * 60_000, 2_147_483_647))
  }
}

const pwdRules = computed(() => ({
  old_password: [{ required: true, message: t('password.requiredCurrent'), trigger: 'blur' }],
  new_password: [
    { required: true, message: t('password.requiredNew'), trigger: 'blur' },
    { min: 8, message: t('password.minLength'), trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: t('password.requiredConfirm'), trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (value !== pwdForm.value.new_password) callback(new Error(t('password.mismatch')))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}))

async function submitChangePassword() {
  if (!pwdFormRef.value) return
  await pwdFormRef.value.validate(async (valid: boolean) => {
    if (!valid) return
    pwdSubmitting.value = true
    try {
      const { data } = await api.post('/auth/password', {
        old_password: pwdForm.value.old_password,
        new_password: pwdForm.value.new_password,
      })
      ElMessage.success(data.detail || t('password.success'))
      pwdDialogVisible.value = false
    } catch (err: any) {
      ElMessage.error(err.response?.data?.detail || t('password.failure'))
    } finally {
      pwdSubmitting.value = false
    }
  })
}

async function handleUserCommand(command: string) {
  if (command === 'logout') {
    try { await api.post('/auth/logout') } catch { /* already signed out */ }
    userPermissions.value = []
    stopStatus()
    router.push('/login')
  }
  if (command === 'password') {
    pwdForm.value = { old_password: '', new_password: '', confirm_password: '' }
    pwdDialogVisible.value = true
  }
  if (command === 'theme') toggleTheme()
}

function runCommand(item: CommandItem) {
  if (item.id.startsWith('nav:')) {
    router.push(item.id.slice(4))
    return
  }
  if (item.id === 'action:refresh') refreshPage()
  if (item.id === 'action:theme') toggleTheme()
  if (item.id === 'action:update') router.push('/settings#updates')
  if (item.id === 'action:logout') void handleUserCommand('logout')
}

function onGlobalKey(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    paletteOpen.value = !paletteOpen.value
  }
}

onMounted(async () => {
  mobileQuery = window.matchMedia('(max-width: 1024px)')
  updateViewport()
  mobileQuery.addEventListener('change', updateViewport)
  window.addEventListener('keydown', onGlobalKey)
  releaseUpdateReminder = subscribeUpdateReminder(refreshUpdateReminder)
  api.get('/system/config').then(({ data }) => {
    if (data?.panel_title) {
      panelTitle.value = String(data.panel_title)
      document.title = panelTitle.value
    }
  }).catch(() => {})
  await loadProfile()
  startStatus()
  void checkForUpdateSilently()
  void loadNotifications()
  notifyTimer = setInterval(loadNotifications, 60_000)
})

onBeforeUnmount(() => {
  mobileQuery?.removeEventListener('change', updateViewport)
  window.removeEventListener('keydown', onGlobalKey)
  if (notifyTimer) clearInterval(notifyTimer)
  releaseUpdateReminder?.()
  stopStatus()
  stopUpdateChecks()
})

watch(() => route.path, async (path, previousPath) => {
  mobileNavOpen.value = false
  paletteOpen.value = false
  if (path === '/login') {
    userPermissions.value = []
    stopStatus()
    stopUpdateChecks()
    return
  }
  if (previousPath === '/login' || !userPermissions.value.length) await loadProfile()
  if (previousPath === '/login') {
    startStatus()
    void checkForUpdateSilently()
  }
  void loadNotifications()
})
</script>

<style>
.forbidden-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.update-pill.el-button {
  height: 28px;
  font-size: 10.5px;
}

.dialog-prose p {
  margin: 0;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.9;
}
.guide-steps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 18px;
}
.guide-steps span {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 10.5px;
}
.guide-steps i {
  color: var(--brand-strong);
  font: 650 9px var(--font-mono);
  font-style: normal;
  letter-spacing: 0.1em;
}

.notification-popper.el-popper {
  padding: 0 !important;
  border-radius: 14px;
  overflow: hidden;
}
.notify-panel {
  padding: 4px;
}
.notify-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 12px 10px;
  border-bottom: 1px solid var(--line);
}
.notify-head > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.notify-head strong {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 650;
}
.notify-head small {
  color: var(--text-4);
  font-size: 9.5px;
}
.notify-list {
  display: flex;
  flex-direction: column;
  padding: 4px;
  max-height: 330px;
  overflow-y: auto;
}
.notify-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  text-align: left;
  cursor: pointer;
}
.notify-item:hover {
  background: var(--surface-2);
}
.notify-item > .app-icon {
  margin-left: auto;
  color: var(--text-4);
}
.notify-dot {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  flex: none;
  border-radius: 50%;
  background: var(--info);
}
.notify-dot.error { background: var(--danger); }
.notify-dot.warning { background: var(--warning); }
.notify-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.notify-copy b {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  color: var(--text-2);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.5;
}
.notify-copy small {
  color: var(--text-4);
  font-size: 9px;
}
.notify-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 30px 16px;
  color: var(--text-4);
  font-size: 11px;
}
.notify-empty .app-icon {
  color: var(--success);
}
.notify-foot {
  display: flex;
  justify-content: flex-end;
  padding: 6px 8px 8px;
  border-top: 1px solid var(--line);
}

@media (max-width: 600px) {
  .guide-steps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
