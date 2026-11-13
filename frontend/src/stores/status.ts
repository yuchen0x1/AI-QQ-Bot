import { computed, onScopeDispose } from 'vue'
import { defineStore } from 'pinia'
import { useRealtimeSocket, type SocketState } from '../api'

export interface StatusPayload {
  online?: number
  error?: number
  total_runtime?: number
  messages_today?: number
  scheduler_running?: boolean
  accounts?: Array<{ id: number; name: string; state: string; online_seconds: number }>
  time?: string
}

const EMPTY: StatusPayload = {}

/**
 * `/ws/status` 的全局单例。
 *
 * 之前 App / Dashboard / Accounts / Messages 四个组件各自建立一条 WebSocket，
 * 服务端每条连接每 5 秒都会跑一次 COUNT(*) 统计今日消息。这里收敛成一条连接，
 * 由引用计数控制生命周期：最后一个消费者离开后才断开。
 */
export const useStatusStore = defineStore('status', () => {
  let socket: ReturnType<typeof useRealtimeSocket<StatusPayload>> | null = null
  let consumers = 0
  let stopTimer: ReturnType<typeof setTimeout> | null = null

  function ensure() {
    if (stopTimer) {
      clearTimeout(stopTimer)
      stopTimer = null
    }
    if (socket) return socket
    socket = useRealtimeSocket<StatusPayload>('/ws/status')
    socket.reconnect()
    return socket
  }

  const sock = () => ensure()

  const state = computed<SocketState>(() => sock().state.value)
  const payload = computed<StatusPayload>(() => sock().lastMessage.value ?? EMPTY)
  const online = computed(() => payload.value.online ?? 0)
  const totalRuntime = computed(() => payload.value.total_runtime ?? 0)
  const messagesToday = computed(() => payload.value.messages_today ?? 0)
  const accountStates = computed(() => payload.value.accounts ?? [])

  /** 组件挂载时调用；返回的 release 会在组件卸载时自动执行。 */
  function acquire(): () => void {
    consumers += 1
    ensure()
    let released = false
    const release = () => {
      if (released) return
      released = true
      consumers = Math.max(0, consumers - 1)
      if (consumers > 0) return
      // 稍作延迟，避免路由切换瞬间断开又重连。
      stopTimer = setTimeout(() => {
        stopTimer = null
        if (consumers > 0) return
        socket?.close()
        socket = null
      }, 1500)
    }
    onScopeDispose(release)
    return release
  }

  function reconnect() {
    ensure().reconnect()
  }

  return { state, payload, online, totalRuntime, messagesToday, accountStates, acquire, reconnect, ensure }
})