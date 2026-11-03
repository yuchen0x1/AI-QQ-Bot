import axios from 'axios'
import { ElMessage } from 'element-plus'

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
