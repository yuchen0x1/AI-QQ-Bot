<template>
  <router-view v-if="$route.path === '/login'" />
  <el-result v-else-if="$route.query.forbidden === '1'" icon="warning" :title="t('forbidden.title')" :sub-title="t('forbidden.subtitle')">
    <template #extra><el-button type="primary" @click="$router.replace('/')">{{ t('forbidden.back') }}</el-button></template>
  </el-result>
  <div v-else class="app-shell">
    <button v-if="mobileNavOpen" class="sidebar-scrim" type="button" :aria-label="t('shell.closeNav')" @click="mobileNavOpen = false"></button>
    <aside id="primary-navigation" class="sidebar" :class="{ collapsed: collapsed && !isMobile, 'mobile-open': mobileNavOpen }">
      <div class="brand"><div class="brand-mark"><el-icon><Promotion /></el-icon></div><div v-if="!collapsed || isMobile" class="brand-copy"><strong>QBOT<span> AI</span></strong><small>CONTROL CENTER</small></div></div>
      <div v-if="!collapsed || isMobile" class="nav-caption">{{ t('nav.workspace') }}</div>
      <el-menu :default-active="$route.path" router :collapse="collapsed" class="side-menu">
        <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path" v-show="!item.permission || userPermissions.includes('*') || userPermissions.includes(item.permission)">
          <el-icon><component :is="item.icon" /></el-icon><template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-bottom"><div class="side-live" role="status" aria-live="polite" :aria-label="socketLabel" :class="`socket-${socket.state.value}`"><i></i><span v-if="!collapsed || isMobile">{{ socketLabel }}</span></div><el-button text class="collapse-button" :aria-label="collapsed ? t('shell.expand') : t('shell.collapse')" @click="collapsed = !collapsed"><el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon><span v-if="!collapsed">{{ t('shell.collapse') }}</span></el-button></div>
    </aside>
    <main class="main-shell">
      <header class="topbar">
        <el-button class="mobile-nav-toggle" circle text :aria-label="mobileNavOpen ? t('shell.closeNav') : t('shell.openNav')" aria-controls="primary-navigation" :aria-expanded="mobileNavOpen" @click="mobileNavOpen = !mobileNavOpen"><el-icon><Menu /></el-icon></el-button>
        <div class="crumb"><span>{{ t('shell.console') }}</span><el-icon><ArrowRight /></el-icon><strong>{{ currentTitle }}</strong></div>
        <div class="top-actions"><div class="system-pill" :class="`socket-${socket.state.value}`"><span class="pulse-dot"></span>{{ socketLabel }}</div><el-button v-if="updateAvailable" type="warning" text @click="router.push('/settings')">{{ t('shell.newVersion') }} {{ latestVersion }}</el-button><el-tooltip :content="t('shell.refresh')"><el-button circle text @click="refreshKey++"><el-icon><Refresh /></el-icon></el-button></el-tooltip><label class="locale-picker"><span class="sr-only">{{ t('shell.locale') }}</span><select :value="localeSetting" :aria-label="t('shell.locale')" @change="changeLocale"><option value="auto">{{ t('shell.auto') }}</option><option value="zh-CN">{{ t('shell.chinese') }}</option><option value="en-US">{{ t('shell.english') }}</option></select></label><el-dropdown trigger="click" @command="handleUserCommand"><div class="user-chip"><el-avatar :size="32" class="user-avatar">{{ username.slice(0,1).toUpperCase() }}</el-avatar><span class="user-name">{{ username }}</span><el-icon><ArrowDown /></el-icon></div><template #dropdown><el-dropdown-menu><el-dropdown-item command="password">{{ t('shell.changePassword') }}</el-dropdown-item><el-dropdown-item command="logout" divided>{{ t('shell.logout') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>
      <section class="page-wrap" :key="refreshKey"><router-view /></section>
      <footer class="page-footer"><span>{{ panelTitle }}</span><span class="footer-realtime"><i :class="`socket-led ${socket.state.value}`"></i>{{ socketLabel }} · {{ t('shell.footer') }}</span></footer>
    </main>

    <!-- 修改密码对话框 -->
    <el-dialog v-model="guideVisible" :title="t('guide.title')" width="min(560px, calc(100vw - 28px))" :before-close="closeGuide">
      <p style="line-height:1.9;color:#b6c8e0">{{ t('guide.body') }}</p>
      <p style="line-height:1.9;color:#92accb">{{ t('nav.help') }}</p>
      <template #footer><el-button @click="dismissGuide">{{ t('guide.later') }}</el-button><el-button type="primary" @click="startGuide">{{ t('guide.start') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="pwdDialogVisible" :title="t('password.title')" width="420px" destroy-on-close>
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
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api'
import { storeToRefs } from 'pinia'
import { useStatusStore } from './stores/status'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowRight, Expand, Fold, Menu, Promotion, Refresh } from '@element-plus/icons-vue'
import { localeSetting, setLocaleSetting, t } from './i18n'
const route = useRoute(), router = useRouter()
const guideVisible = ref(false)
async function rememberGuide() { try { await api.put('/onboarding', { seen: true, step: 0 }) } catch {} }
async function dismissGuide() { await rememberGuide(); guideVisible.value = false }
async function closeGuide(done: () => void) { await rememberGuide(); done() }
async function startGuide() { await dismissGuide(); router.push('/help') }
const collapsed = ref(false), mobileNavOpen = ref(false), isMobile = ref(false), refreshKey = ref(0), username = ref('管理员'), userPermissions = ref<string[]>([]), updateAvailable = ref(false), latestVersion = ref('')
// 页脚品牌名取自系统设置 panel_title，与 document.title 保持一致。
const panelTitle = ref('QBot AI 管理平台')
let mobileQuery: MediaQueryList | undefined
const updateViewport = (event?: MediaQueryListEvent) => { isMobile.value = event?.matches ?? mobileQuery?.matches ?? false }
const status = useStatusStore()
const { state: socketState } = storeToRefs(status)
const socket = { state: socketState, reconnect: status.reconnect }
const socketLabel = computed(() => ({ connecting: t('shell.connecting'), reconnecting: t('shell.reconnecting'), open: t('shell.realtime'), closed: t('shell.closed'), error: t('shell.error') } as Record<string, string>)[socketState.value] || t('shell.system'))
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
const navOrder = ['/', '/accounts', '/groups', '/requests', '/messages', '/ai', '/github', '/push-rules', '/push-records', '/tasks', '/email', '/plugins', '/logs', '/system', '/settings', '/help']
const routeTitleKeys: Record<string, string> = {
  '/': 'nav.dashboard', '/accounts': 'nav.accounts', '/groups': 'nav.groups', '/requests': 'nav.requests',
  '/messages': 'nav.messages', '/ai': 'nav.ai', '/github': 'nav.github', '/push-rules': 'nav.pushRules',
  '/push-records': 'nav.pushRecords', '/tasks': 'nav.tasks', '/email': 'nav.email', '/plugins': 'nav.plugins',
  '/logs': 'nav.logs', '/system': 'nav.system', '/settings': 'nav.settings', '/help': 'nav.help',
}
const navItems = computed(() => router.getRoutes().filter(r => r.meta.title && r.path !== '/login').sort((a,b) => navOrder.indexOf(a.path) - navOrder.indexOf(b.path)).map(r => ({ path: r.path, title: t(routeTitleKeys[r.path] || String(r.meta.title)), icon: String(r.meta.icon || 'Menu'), permission: typeof r.meta.permission === 'string' ? r.meta.permission : '' })))
const currentTitle = computed(() => t(routeTitleKeys[route.path] || String(route.meta.title || 'nav.dashboard')))

function changeLocale(event: Event) {
  setLocaleSetting((event.target as HTMLSelectElement).value)
}

// 修改密码状态
const pwdDialogVisible = ref(false)
const pwdSubmitting = ref(false)
const pwdFormRef = ref<any>()
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })
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
        if (value !== pwdForm.value.new_password) {
          callback(new Error(t('password.mismatch')))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}))

async function loadProfile() {
  try {
    const { data } = await api.get('/auth/me')
    username.value = data.username || '管理员'
    userPermissions.value = data.permissions || []
    const guide = await api.get('/onboarding')
    guideVisible.value = !guide.data.progress?.seen && route.path !== '/help'
  } catch {}
}
async function checkForUpdateSilently() {
  if (route.path === '/login') return
  const last = Number(localStorage.getItem('qbot_update_checked_at') || 0)
  const interval = 6 * 60 * 60 * 1000
  if (last && Date.now() - last < interval) return
  localStorage.setItem('qbot_update_checked_at', String(Date.now()))
  try {
    const { data } = await api.get('/system/update')
    updateAvailable.value = Boolean(data?.update_available)
    latestVersion.value = String(data?.latest_version || '')
  } catch {}
}
onMounted(async () => {
  mobileQuery = window.matchMedia('(max-width: 768px)')
  updateViewport()
  mobileQuery.addEventListener('change', updateViewport)
  api.get('/system/config').then(({ data }) => {
    if (data?.panel_title) panelTitle.value = String(data.panel_title)
  }).catch(() => {})
  await loadProfile()
  await checkForUpdateSilently()
  startStatus()
})
onBeforeUnmount(() => {
  mobileQuery?.removeEventListener('change', updateViewport)
  stopStatus()
})
watch(() => route.path, (path, previousPath) => {
  mobileNavOpen.value = false
  if (path === '/login') { userPermissions.value = []; stopStatus(); return }
  if (previousPath === '/login' || !userPermissions.value.length) loadProfile()
  if (previousPath === '/login') { startStatus(); checkForUpdateSilently() }
})

async function handleUserCommand(command: string) {
  if (command === 'logout') {
    try { await api.post('/auth/logout') } catch {}
    userPermissions.value = []
    stopStatus()
    router.push('/login')
  }
  if (command === 'password') {
    pwdForm.value = { old_password: '', new_password: '', confirm_password: '' }
    pwdDialogVisible.value = true
  }
}

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
</script>
