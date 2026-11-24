import { ref } from 'vue'

export type Locale = 'zh-CN' | 'en-US'
export type LocaleSetting = 'auto' | Locale

const STORAGE_KEY = 'qbot_locale'
const fallbackLocale: Locale = 'zh-CN'

const messages: Record<Locale, Record<string, string>> = {
  'zh-CN': {
    'nav.workspace': '工作空间',
    'nav.group.overview': '总览',
    'nav.group.operations': '运营',
    'nav.group.intelligence': '智能与自动化',
    'nav.group.platform': '平台',
    'nav.group.support': '支持',
    'nav.dashboard': '仪表盘',
    'nav.accounts': 'QQ 账号管理',
    'nav.groups': '群聊管理',
    'nav.requests': '申请审核',
    'nav.messages': '消息管理',
    'nav.ai': 'AI 模型中心',
    'nav.github': 'GitHub 仓库监控',
    'nav.pushRules': '推送规则',
    'nav.pushRecords': '推送记录',
    'nav.tasks': '自动化任务',
    'nav.plugins': '插件管理',
    'nav.logs': '系统日志',
    'nav.system': '系统监控',
    'nav.settings': '系统设置',
    'nav.email': '邮件告警',
    'nav.help': '新手指引与文档',
    'shell.console': '控制台',
    'shell.realtime': '实时同步',
    'shell.connecting': '实时连接中',
    'shell.reconnecting': '重连中…',
    'shell.closed': '连接已断开',
    'shell.error': '实时连接异常',
    'shell.system': '系统状态',
    'shell.refresh': '刷新当前页面',
    'shell.refreshed': '页面数据已重新载入',
    'shell.search': '打开快捷命令',
    'shell.searchPlaceholder': '搜索页面、操作…',
    'shell.commandNavigate': '页面导航',
    'shell.commandActions': '快捷操作',
    'shell.refreshDesc': '重新载入当前页面的数据',
    'shell.themeDesc': '在深色与浅色主题之间切换',
    'shell.updateDesc': '前往系统设置查看在线更新',
    'shell.logoutDesc': '结束当前会话并返回登录页',
    'shell.notifications': '通知中心',
    'shell.notificationsHint': '来自系统日志的异常与告警',
    'shell.noNotifications': '没有未读异常',
    'shell.viewAllLogs': '查看全部日志',
    'shell.available': '可以升级',
    'shell.themeLight': '切换到浅色模式',
    'shell.themeDark': '切换到深色模式',
    'shell.newVersion': '新版本',
    'shell.changePassword': '修改密码',
    'shell.logout': '退出登录',
    'shell.collapse': '收起侧栏',
    'shell.expand': '展开侧栏',
    'shell.openNav': '打开导航菜单',
    'shell.closeNav': '关闭导航菜单',
    'shell.locale': '界面语言',
    'shell.auto': '自动（跟随系统）',
    'shell.chinese': '简体中文',
    'shell.english': 'English',
    'shell.footer': '多账号 · 可扩展 · 安全可控',
    'guide.title': '第一次使用，从这里开始',
    'guide.body': '按顺序连接机器人、配置 AI 模型、授权 GitHub、绑定通知群并开启主动推送，再验证通知和失败邮件。每一步都有操作说明和真实状态检查。',
    'guide.later': '稍后设置',
    'guide.start': '开始分步设置',
    'password.title': '修改登录密码',
    'password.current': '当前密码',
    'password.new': '新密码',
    'password.confirm': '确认新密码',
    'password.currentPlaceholder': '请输入当前密码',
    'password.newPlaceholder': '至少 8 位新密码',
    'password.confirmPlaceholder': '请再次输入新密码',
    'password.cancel': '取消',
    'password.submit': '确认修改',
    'password.requiredCurrent': '请输入当前密码',
    'password.requiredNew': '请输入新密码',
    'password.minLength': '密码长度至少 8 位',
    'password.requiredConfirm': '请确认新密码',
    'password.mismatch': '两次输入的新密码不一致',
    'password.success': '密码已修改，请妥善保存',
    'password.failure': '修改密码失败',
    'forbidden.title': '没有访问权限',
    'forbidden.subtitle': '当前账号无权查看此页面',
    'forbidden.back': '返回仪表盘',
  },
  'en-US': {
    'nav.workspace': 'Workspace',
    'nav.group.overview': 'Overview',
    'nav.group.operations': 'Operations',
    'nav.group.intelligence': 'Intelligence & Automation',
    'nav.group.platform': 'Platform',
    'nav.group.support': 'Support',
    'nav.dashboard': 'Dashboard',
    'nav.accounts': 'QQ Accounts',
    'nav.groups': 'Group Chats',
    'nav.requests': 'Request Review',
    'nav.messages': 'Messages',
    'nav.ai': 'AI Models',
    'nav.github': 'GitHub Monitoring',
    'nav.pushRules': 'Push Rules',
    'nav.pushRecords': 'Push Records',
    'nav.tasks': 'Automation',
    'nav.plugins': 'Plugins',
    'nav.logs': 'System Logs',
    'nav.system': 'System Monitor',
    'nav.settings': 'System Settings',
    'nav.email': 'Email Alerts',
    'nav.help': 'Getting Started',
    'shell.console': 'Console',
    'shell.realtime': 'Live sync',
    'shell.connecting': 'Connecting',
    'shell.reconnecting': 'Reconnecting…',
    'shell.closed': 'Disconnected',
    'shell.error': 'Connection error',
    'shell.system': 'System status',
    'shell.refresh': 'Refresh page',
    'shell.refreshed': 'Page data reloaded',
    'shell.search': 'Open command palette',
    'shell.searchPlaceholder': 'Search pages and actions…',
    'shell.commandNavigate': 'Navigation',
    'shell.commandActions': 'Quick actions',
    'shell.refreshDesc': 'Reload data on the current page',
    'shell.themeDesc': 'Switch between dark and light themes',
    'shell.updateDesc': 'Open online update settings',
    'shell.logoutDesc': 'End this session and return to sign-in',
    'shell.notifications': 'Notifications',
    'shell.notificationsHint': 'Errors and warnings from system logs',
    'shell.noNotifications': 'No unresolved alerts',
    'shell.viewAllLogs': 'View all logs',
    'shell.available': 'is available',
    'shell.themeLight': 'Switch to light mode',
    'shell.themeDark': 'Switch to dark mode',
    'shell.newVersion': 'New version',
    'shell.changePassword': 'Change password',
    'shell.logout': 'Sign out',
    'shell.collapse': 'Collapse sidebar',
    'shell.expand': 'Expand sidebar',
    'shell.openNav': 'Open navigation menu',
    'shell.closeNav': 'Close navigation menu',
    'shell.locale': 'Interface language',
    'shell.auto': 'Auto (system)',
    'shell.chinese': '简体中文',
    'shell.english': 'English',
    'shell.footer': 'Multi-account · Extensible · Secure',
    'guide.title': 'Get started',
    'guide.body': 'Connect the bot, configure AI models, authorize GitHub, bind a notification group, enable proactive pushes, then verify notifications and failed email alerts.',
    'guide.later': 'Set up later',
    'guide.start': 'Start guided setup',
    'password.title': 'Change login password',
    'password.current': 'Current password',
    'password.new': 'New password',
    'password.confirm': 'Confirm new password',
    'password.currentPlaceholder': 'Enter current password',
    'password.newPlaceholder': 'At least 8 characters',
    'password.confirmPlaceholder': 'Enter the new password again',
    'password.cancel': 'Cancel',
    'password.submit': 'Update password',
    'password.requiredCurrent': 'Enter the current password',
    'password.requiredNew': 'Enter a new password',
    'password.minLength': 'Password must be at least 8 characters',
    'password.requiredConfirm': 'Confirm the new password',
    'password.mismatch': 'The two passwords do not match',
    'password.success': 'Password updated. Keep it safe.',
    'password.failure': 'Failed to update password',
    'forbidden.title': 'Access denied',
    'forbidden.subtitle': 'Your account cannot view this page',
    'forbidden.back': 'Back to dashboard',
  },
}

function browserCandidates(): string[] {
  if (typeof navigator === 'undefined') return []
  return Array.isArray(navigator.languages) && navigator.languages.length
    ? navigator.languages
    : navigator.language ? [navigator.language] : []
}

export function resolveLocale(setting: LocaleSetting | undefined, candidates = browserCandidates()): Locale {
  if (setting === 'zh-CN' || setting === 'en-US') return setting
  for (const candidate of candidates) {
    const value = String(candidate).toLowerCase()
    if (value === 'en' || value.startsWith('en-')) return 'en-US'
    if (value === 'zh' || value.startsWith('zh-')) return 'zh-CN'
  }
  return fallbackLocale
}

function readSetting(): LocaleSetting {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'zh-CN' || value === 'en-US' ? value : 'auto'
  } catch {
    return 'auto'
  }
}

export const localeSetting = ref<LocaleSetting>(readSetting())
export const locale = ref<Locale>(resolveLocale(localeSetting.value))

function applyDocumentLocale() {
  if (typeof document !== 'undefined') document.documentElement.lang = locale.value
}

applyDocumentLocale()

export function setLocaleSetting(value: string): LocaleSetting {
  const setting: LocaleSetting = value === 'zh-CN' || value === 'en-US' ? value : 'auto'
  localeSetting.value = setting
  locale.value = resolveLocale(setting)
  try { localStorage.setItem(STORAGE_KEY, setting) } catch { /* private mode */ }
  applyDocumentLocale()
  return setting
}

export function t(key: string): string {
  return messages[locale.value][key] || messages[fallbackLocale][key] || key
}
