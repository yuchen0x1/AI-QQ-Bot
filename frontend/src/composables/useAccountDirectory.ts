import { ref, shallowRef } from 'vue'
import type { Page } from '../api'

export function useAccountDirectory<T extends { id: number }>(
  fetchPage: (accountId: number, page: number, keyword: string) => Promise<Page<T>>,
) {
  const accountId = ref<number | null>(null)
  const items = shallowRef<T[]>([])
  const total = ref(0)
  const page = ref(0)
  const keyword = ref('')
  const loading = ref(false)
  const error = ref('')
  let generation = 0

  async function load(id: number | null, query = '', append = false) {
    const request = ++generation
    const nextPage = append && id === accountId.value && query === keyword.value ? page.value + 1 : 1
    if (nextPage === 1) {
      items.value = []
      total.value = 0
      page.value = 0
    }
    accountId.value = id
    keyword.value = query
    error.value = ''
    if (!id) { loading.value = false; return }
    loading.value = true
    try {
      const data = await fetchPage(id, nextPage, query)
      if (request !== generation) return
      const previous = nextPage === 1 ? [] : items.value
      items.value = [...new Map([...previous, ...(data.items || [])].map(item => [item.id, item])).values()]
      total.value = data.total
      page.value = nextPage
    } catch (failure: any) {
      if (request === generation) error.value = failure?.response?.data?.detail || '列表加载失败，请重试'
    } finally {
      if (request === generation) loading.value = false
    }
  }

  const more = () => load(accountId.value, keyword.value, true)
  return { accountId, items, total, page, keyword, loading, error, load, more }
}
