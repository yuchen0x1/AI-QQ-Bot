<template>
  <router-view v-if="$route.path === '/login'" />
  <el-result v-else-if="$route.query.forbidden === '1'" icon="warning" title="没有访问权限" sub-title="当前账号无权查看此页面">
    <template #extra><el-button type="primary" @click="$router.replace('/')">返回仪表盘</el-button></template>
  </el-result>
  <div v-else class="app-shell">
    <button v-if="mobileNavOpen" class="sidebar-scrim" type="button" aria-label="关闭导航菜单" @click="mobileNavOpen = false"></button>
    <aside id="primary-navigation" class="sidebar" :class="{ collapsed: collapsed && !isMobile, 'mobile-open': mobileNavOpen }">
      <div class="brand"><div class="brand-mark"><el-icon><Promotion /></el-icon></div><div v-if="!collapsed || isMobile" class="brand-copy"><strong>QBOT<span> AI</span></strong><small>CONTROL CENTER</small></div></div>
      <div v-if="!collapsed || isMobile" class="nav-caption">工作空间</div>
      <el-menu :default-active="$route.path" router :collapse="collapsed" class="side-menu">
        <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path" v-show="!item.permission || userPermissions.includes('*') || userPermissions.includes(item.permission)">
          <el-icon><component :is="item.icon" /></el-icon><template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-bottom"><div class="side-live" role="status" aria-live="polite" :aria-label="socketLabel" :class="`socket-${socket.state.value}`"><i></i><span v-if="!collapsed || isMobile">{{ socketLabel }}</span></div><el-button text class="collapse-button" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'" @click="collapsed = !collapsed"><el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon><span v-if="!collapsed">收起侧栏</span></el-button></div>
    </aside>
    <main class="main-shell">
      <header class="topbar">
        <el-button class="mobile-nav-toggle" circle text :aria-label="mobileNavOpen ? '关闭导航菜单' : '打开导航菜单'" aria-controls="primary-navigation" :aria-expanded="mobileNavOpen" @click="mobileNavOpen = !mobileNavOpen"><el-icon><Menu /></el-icon></el-button>
        <div class="crumb"><span>控制台</span><el-icon><ArrowRight /></el-icon><strong>{{ currentTitle }}</strong></div>
        <div class="top-actions"><div class="system-pill" :class="`socket-${socket.state.value}`"><span class="pulse-dot"></span>{{ socketLabel }}</div><el-button v-if="updateAvailable" type="warning" text @click="router.push('/settings')">新版本 {{ latestVersion }}</el-button><el-tooltip content="刷新当前页面"><el-button circle text @click="refreshKey++"><el-icon><Refresh /></el-icon></el-button></el-tooltip><el-dropdown trigger="click" @command="handleUserCommand"><div class="user-chip"><el-avatar :size="32" class="user-avatar">{{ username.slice(0,1).toUpperCase() }}</el-avatar><span class="user-name">{{ username }}</span><el-icon><ArrowDown /></el-icon></div><template #dropdown><el-dropdown-menu><el-dropdown-item command="password">修改密码</el-dropdown-item><el-dropdown-item command="logout" divided>退出登录</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>
      <section class="page-wrap" :key="refreshKey"><router-view /></section>
      <footer class="page-footer"><span>{{ panelTitle }}</span><span class="footer-realtime"><i :class="`socket-led ${socket.state.value}`"></i>{{ socketLabel }} · 多账号 · 可扩展 · 安全可控</span></footer>
    </main>

    <!-- 修改密码对话框 -->
    <el-dialog v-model="guideVisible" title="第一次使用，从这里开始" width="min(560px, calc(100vw - 28px))" :before-close="closeGuide">
      <p style="line-height:1.9;color:#b6c8e0">按顺序连接机器人、配置 AI 模型、授权 GitHub、绑定通知群并开启主动推送，再验证通知和失败邮件。每一步都有操作说明和真实状态检查。</p>
      <p style="line-height:1.9;color:#92accb">以后可以随时从左侧「新手指引与文档」重新打开教学。</p>
      <template #footer><el-button @click="dismissGuide">稍后设置</el-button><el-button type="primary" @click="startGuide">开始分步设置</el-button></template>
    </el-dialog>
    <el-dialog v-model="pwdDialogVisible" title="修改登录密码" width="420px" destroy-on-close>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-position="top">
        <el-form-item label="当前密码" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="请输入当前密码" />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 8 位新密码" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input v-model="pwdForm.confirm_password" type="password" show-password placeholder="请再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSubmitting" @click="submitChangePassword">确认修改</el-button>
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
const socketLabel = computed(() => ({ connecting: '实时连接中', open: '实时同步', closed: '连接已断开', error: '实时连接异常' } as Record<string, string>)[socketState.value] || '系统状态')
const navOrder = ['/', '/accounts', '/groups', '/requests', '/messages', '/ai', '/github', '/push-rules', '/push-records', '/tasks', '/email', '/plugins', '/logs', '/system', '/settings', '/help']
const navItems = computed(() => router.getRoutes().filter(r => r.meta.title && r.path !== '/login').sort((a,b) => navOrder.indexOf(a.path) - navOrder.indexOf(b.path)).map(r => ({ path: r.path, title: String(r.meta.title), icon: String(r.meta.icon || 'Menu'), permission: typeof r.meta.permission === 'string' ? r.meta.permission : '' })))
const currentTitle = computed(() => String(route.meta.title || '仪表盘'))

// 修改密码状态
const pwdDialogVisible = ref(false)
const pwdSubmitting = ref(false)
const pwdFormRef = ref<any>()
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const pwdRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码长度至少 8 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (value !== pwdForm.value.new_password) {
          callback(new Error('两次输入的新密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

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
  status.acquire()
})
onBeforeUnmount(() => mobileQuery?.removeEventListener('change', updateViewport))
watch(() => route.path, (path, previousPath) => {
  mobileNavOpen.value = false
  if (path === '/login') { userPermissions.value = []; return }
  if (previousPath === '/login' || !userPermissions.value.length) loadProfile()
  if (previousPath === '/login') status.reconnect()
  if (previousPath === '/login') checkForUpdateSilently()
})

async function handleUserCommand(command: string) {
  if (command === 'logout') {
    try { await api.post('/auth/logout') } catch {}
    localStorage.removeItem('qbot_token')
    userPermissions.value = []
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
      if (data.access_token) localStorage.setItem('qbot_token', data.access_token)
      ElMessage.success(data.detail || '密码已修改，请妥善保存')
      pwdDialogVisible.value = false
    } catch (err: any) {
      ElMessage.error(err.response?.data?.detail || '修改密码失败')
    } finally {
      pwdSubmitting.value = false
    }
  })
}
</script>
