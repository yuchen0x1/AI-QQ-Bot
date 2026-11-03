import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    { path: '/', component: () => import('../views/DashboardView.vue'), meta: { title: '仪表盘', icon: 'DataBoard' } },
    { path: '/accounts', component: () => import('../views/AccountsView.vue'), meta: { title: 'QQ 账号管理', icon: 'Avatar' } },
    { path: '/groups', component: () => import('../views/GroupsView.vue'), meta: { title: '群聊管理', icon: 'ChatDotRound', permission: 'group:view' } },
    { path: '/requests', component: () => import('../views/RequestsView.vue'), meta: { title: '申请审核', icon: 'Tickets', permission: 'request:view' } },
    { path: '/messages', component: () => import('../views/MessagesView.vue'), meta: { title: '消息管理', icon: 'ChatLineSquare' } },
    { path: '/ai', component: () => import('../views/AIView.vue'), meta: { title: 'AI 模型中心', icon: 'Cpu' } },
    { path: '/github', component: () => import('../views/GitHubView.vue'), meta: { title: 'GitHub 仓库监控', icon: 'Connection' } },
    { path: '/push-rules', component: () => import('../views/PushRulesView.vue'), meta: { title: '推送规则', icon: 'Promotion' } },
    { path: '/push-records', component: () => import('../views/PushRecordsView.vue'), meta: { title: '推送记录', icon: 'Tickets' } },
    { path: '/tasks', component: () => import('../views/TasksView.vue'), meta: { title: '自动化任务', icon: 'Timer' } },
    { path: '/plugins', component: () => import('../views/PluginsView.vue'), meta: { title: '插件管理', icon: 'Grid' } },
    { path: '/logs', component: () => import('../views/LogsView.vue'), meta: { title: '系统日志', icon: 'Document' } },
    { path: '/system', component: () => import('../views/SystemView.vue'), meta: { title: '系统监控', icon: 'Monitor' } },
    { path: '/settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置', icon: 'Setting' } },
  ],
})

router.beforeEach(async (to) => {
  const token = localStorage.getItem('qbot_token')
  if (!to.meta.public && !token) return { path: '/login', query: { next: to.fullPath } }
  if (to.path === '/login' && token) return '/'
  if (!to.meta.permission || to.meta.public || !token) return true

  try {
    const response = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } })
    if (response.status === 401) {
      localStorage.removeItem('qbot_token')
      return { path: '/login', query: { next: to.fullPath } }
    }
    if (!response.ok) return { path: '/', query: { forbidden: '1' } }
    const user = await response.json()
    const permissions: string[] = user.permissions || []
    if (permissions.includes('*') || permissions.includes(String(to.meta.permission))) return true
    return { path: '/', query: { forbidden: '1' } }
  } catch {
    return { path: '/', query: { forbidden: '1' } }
  }
})
export default router
