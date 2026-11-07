<template>
  <router-view v-if="$route.path === '/login'" />
  <el-result v-else-if="$route.query.forbidden === '1'" icon="warning" title="没有访问权限" sub-title="当前账号无权查看此页面">
    <template #extra><el-button type="primary" @click="$router.replace('/')">返回仪表盘</el-button></template>
  </el-result>
  <div v-else class="app-shell">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand"><div class="brand-mark"><el-icon><Promotion /></el-icon></div><div v-if="!collapsed" class="brand-copy"><strong>QBOT<span> AI</span></strong><small>CONTROL CENTER</small></div></div>
      <div v-if="!collapsed" class="nav-caption">工作空间</div>
      <el-menu :default-active="$route.path" router :collapse="collapsed" class="side-menu">
        <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path" v-show="!item.permission || userPermissions.includes('*') || userPermissions.includes(item.permission)">
          <el-icon><component :is="item.icon" /></el-icon><template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-bottom"><div class="side-live"><i></i><span v-if="!collapsed">平台运行中</span><el-icon v-else><CircleCheck /></el-icon></div><el-button text class="collapse-button" @click="collapsed = !collapsed"><el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon><span v-if="!collapsed">收起侧栏</span></el-button></div>
    </aside>
    <main class="main-shell">
      <header class="topbar">
        <div class="crumb"><span>控制台</span><el-icon><ArrowRight /></el-icon><strong>{{ currentTitle }}</strong></div>
        <div class="top-actions"><div class="system-pill" :class="`socket-${socket.state.value}`"><span class="pulse-dot"></span>{{ socketLabel }}</div><el-tooltip content="刷新当前页面"><el-button circle text @click="refreshKey++"><el-icon><Refresh /></el-icon></el-button></el-tooltip><el-dropdown trigger="click" @command="handleUserCommand"><div class="user-chip"><el-avatar :size="32" class="user-avatar">{{ username.slice(0,1).toUpperCase() }}</el-avatar><span class="user-name">{{ username }}</span><el-icon><ArrowDown /></el-icon></div><template #dropdown><el-dropdown-menu><el-dropdown-item command="password">修改密码</el-dropdown-item><el-dropdown-item command="logout" divided>退出登录</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>
      <section class="page-wrap" :key="refreshKey"><router-view /></section>
      <footer class="page-footer"><span>QBot AI 管理平台</span><span class="footer-realtime"><i :class="`socket-led ${socket.state.value}`"></i>{{ socketLabel }} · 多账号 · 可扩展 · 安全可控</span></footer>
    </main>

    <!-- 修改密码对话框 -->
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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, useRealtimeSocket } from './api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowRight, CircleCheck, Expand, Fold, Promotion, Refresh } from '@element-plus/icons-vue'
const route = useRoute(), router = useRouter()
const collapsed = ref(false), refreshKey = ref(0), username = ref('管理员'), userPermissions = ref<string[]>([])
const socket = useRealtimeSocket('/ws/status')
const socketLabel = computed(() => ({ connecting: '实时连接中', open: '实时同步', closed: '连接已断开', error: '实时连接异常' } as Record<string, string>)[socket.state.value] || '系统状态')
const navOrder = ['/', '/accounts', '/groups', '/requests', '/messages', '/ai', '/github', '/push-rules', '/push-records', '/tasks', '/plugins', '/logs', '/system', '/settings']
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
  } catch {}
}
onMounted(async () => { await loadProfile(); socket.reconnect() })
watch(() => route.path, (path, previousPath) => {
  if (path === '/login') { socket.close(); userPermissions.value = []; return }
  if (previousPath === '/login' || !userPermissions.value.length) loadProfile()
  if (previousPath === '/login' || socket.state.value === 'closed' || socket.state.value === 'error') socket.reconnect()
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
