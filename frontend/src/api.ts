import axios from 'axios'
import { ElMessage } from 'element-plus'
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import type { Ref, ShallowRef } from 'vue'

export const api = axios.create({ baseURL: '/api', timeout: 30000 })
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('qbot_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
api.interceptors.response.use((response) => response, (error) => {
  const status = error?.response?.status
  if (status === 401 && !location.pathname.startsWith('/login')) {
    localStorage.removeItem('qbot_token')
    location.href = '/login'
  } else if (status !== 401) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '请求失败')
  }
  return Promise.reject(error)
})

export type Page<T> = { items: T[]; total: number; page: number; page_size: number; pages: number }
export const unwrap = <T>(data: T | { data: T }): T => ('data' in (data as object) ? (data as { data: T }).data : data as T)

export type SocketState = 'connecting' | 'open' | 'closed' | 'error'
export interface RealtimeSocket<T = unknown> {
  state: Readonly<Ref<SocketState>>
  lastMessage: Readonly<ShallowRef<T | null>>
  reconnect: () => void
  close: () => void
}

/** 连接后端实时通道。协议端每 25 秒发送 ping，客户端主动保持连接并在异常时指数重连。 */
export function useRealtimeSocket<T = Record<string, unknown>>(path: string, options: { reconnect?: boolean; maxDelay?: number } = {}): RealtimeSocket<T> {
  const state = ref<SocketState>('closed')
  const lastMessage = shallowRef<T | null>(null)
  const reconnectEnabled = options.reconnect !== false
  const maxDelay = options.maxDelay ?? 15000
  let socket: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let heartbeatTimer: ReturnType<typeof setInterval> | undefined
  let attempts = 0
  let stopped = false

  const url = () => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const token = localStorage.getItem('qbot_token')
    return `${protocol}//${location.host}/api${path}?token=${encodeURIComponent(token || '')}`
  }
  const clearTimers = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (heartbeatTimer) clearInterval(heartbeatTimer)
    reconnectTimer = undefined
    heartbeatTimer = undefined
  }
  const schedule = () => {
    if (stopped || !reconnectEnabled || reconnectTimer) return
    const delay = Math.min(maxDelay, 1000 * 2 ** Math.min(attempts, 4))
    reconnectTimer = setTimeout(() => { reconnectTimer = undefined; connect() }, delay)
  }
  const connect = () => {
    if (!localStorage.getItem('qbot_token')) { state.value = 'closed'; return }
    if (stopped || socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return
    clearTimers()
    state.value = 'connecting'
    try { socket = new WebSocket(url()) } catch { state.value = 'error'; schedule(); return }
    socket.onopen = () => {
      attempts = 0
      state.value = 'open'
      heartbeatTimer = setInterval(() => { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' })) }, 20000)
    }
    socket.onmessage = (event) => {
      try { lastMessage.value = JSON.parse(event.data) as T } catch { /* 忽略非 JSON 推送 */ }
    }
    socket.onerror = () => { state.value = 'error' }
    socket.onclose = () => { socket = null; clearTimers(); if (!stopped) { state.value = 'closed'; attempts += 1; schedule() } }
  }
  const close = () => { stopped = true; clearTimers(); socket?.close(); socket = null; state.value = 'closed' }
  const reconnect = () => { stopped = false; attempts = 0; socket?.close(); socket = null; connect() }
  onMounted(connect)
  onBeforeUnmount(close)
  return { state, lastMessage, reconnect, close }
}
