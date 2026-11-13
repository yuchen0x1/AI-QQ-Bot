import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
// 只注册实际用到的图标。@element-plus/icons-vue 共导出 293 个，全量注册会让
// 主 chunk 白白多出上百 KB。新增图标请在下面的表里补充（含路由 meta.icon
// 与仪表盘指标里以字符串引用的名字）。
import {
  ArrowDown,
  ArrowRight,
  Avatar,
  Bell,
  ChatDotRound,
  ChatLineSquare,
  CircleCheckFilled,
  Clock,
  Connection,
  Cpu,
  DataBoard,
  Document,
  Download,
  Expand,
  Fold,
  Grid,
  Loading,
  Lock,
  Menu,
  Message,
  Reading,
  Monitor,
  Plus,
  Position,
  Promotion,
  Refresh,
  Search,
  Setting,
  Tickets,
  Timer,
  User,
  WarningFilled,
} from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
import router from './router'
import { api } from './api'

const ICONS = {
  ArrowDown,
  ArrowRight,
  Avatar,
  Bell,
  ChatDotRound,
  ChatLineSquare,
  CircleCheckFilled,
  Clock,
  Connection,
  Cpu,
  DataBoard,
  Document,
  Download,
  Expand,
  Fold,
  Grid,
  Loading,
  Lock,
  Menu,
  Message,
  Reading,
  Monitor,
  Plus,
  Position,
  Promotion,
  Refresh,
  Search,
  Setting,
  Tickets,
  Timer,
  User,
  WarningFilled,
}

const app = createApp(App)
for (const [key, component] of Object.entries(ICONS)) app.component(key, component)
app.use(createPinia()).use(router).use(ElementPlus).mount('#app')

// 面板标题由系统设置 panel_title 控制（登录页也要生效，所以放在入口拉取）。
api.get('/system/config')
  .then(({ data }) => {
    if (data?.panel_title) document.title = String(data.panel_title)
  })
  .catch(() => { /* 后端不可达时保留 index.html 的默认标题 */ })
