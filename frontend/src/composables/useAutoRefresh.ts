import { onMounted, onBeforeUnmount } from 'vue'

/** Refresh on visible intervals and when returning to the page; never overlap requests. */
export function useAutoRefresh(refresh: () => Promise<unknown>, milliseconds = 10000) {
  let pending = false
  let timer: ReturnType<typeof setInterval> | undefined
  const update = async () => {
    if (pending || document.hidden) return
    pending = true
    try { await refresh() } catch { /* The request interceptor reports actionable failures. */ }
    finally { pending = false }
  }
  onMounted(() => {
    timer = setInterval(update, milliseconds)
    window.addEventListener('focus', update)
    document.addEventListener('visibilitychange', update)
  })
  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
    window.removeEventListener('focus', update)
    document.removeEventListener('visibilitychange', update)
  })
}
