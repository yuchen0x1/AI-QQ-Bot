import { onMounted, ref } from 'vue'
import { api } from '../api'

export function usePermissions() {
  const permissions = ref<string[]>([])
  const ready = ref(false)
  const can = (permission: string) => permissions.value.includes('*') || permissions.value.includes(permission)
  onMounted(async () => {
    try {
      const { data } = await api.get('/auth/me')
      permissions.value = data.permissions || []
    } catch {
      permissions.value = []
    } finally {
      ready.value = true
    }
  })
  return { permissions, ready, can }
}
