import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UpdatePanel from '../components/UpdatePanel.vue'
import { SNOOZE_DURATION_MS } from '../updateReminder'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api', () => ({ api: { get, post: vi.fn() } }))
vi.mock('element-plus', () => ({
  ElMessage: { info: vi.fn(), success: vi.fn() }, ElMessageBox: { confirm: vi.fn() },
}))

function panel(canManage = false) {
  return mount(UpdatePanel, { props: { canManage }, global: { stubs: {
    AppIcon: true,
    'el-button': { props: ['disabled'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>' },
    'el-tag': { template: '<span><slot /></span>' },
    'el-link': { template: '<a><slot /></a>' },
    'el-alert': true, 'el-progress': true, 'el-table': true, 'el-table-column': true,
  } } })
}

describe('UpdatePanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(1_800_000_000_000)
    localStorage.clear()
    get.mockResolvedValue({ data: {
      current_version: '1.5.3', latest_version: '1.6.0', update_available: true, ok: true,
      check_interval_minutes: 360, installable: true, installer: { available: true },
      checked_at: '2027-01-15T08:00:00+00:00', last_success_at: '2027-01-15T08:00:00+00:00',
    } })
  })
  afterEach(() => { vi.useRealTimers(); localStorage.clear() })

  it('restores the later reminder button on the same mounted page after expiry', async () => {
    const wrapper = panel()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '稍后提醒')!.trigger('click')
    expect(wrapper.text()).toContain('已延后提醒至')
    expect(wrapper.findAll('button').some((button) => button.text() === '稍后提醒')).toBe(false)
    await vi.advanceTimersByTimeAsync(SNOOZE_DURATION_MS)
    expect(wrapper.findAll('button').some((button) => button.text() === '稍后提醒')).toBe(true)
    wrapper.unmount()
  })

  it('allows viewer metadata checks but never exposes an executable install button', async () => {
    const wrapper = panel(false)
    await flushPromises()
    expect(wrapper.text()).toContain('v1.6.0')
    expect(wrapper.findAll('button').some((button) => button.text().includes('升级到'))).toBe(false)
    await wrapper.findAll('button').find((button) => button.text().includes('检查更新'))!.trigger('click')
    await flushPromises()
    expect(get).toHaveBeenLastCalledWith('/system/update', { params: { force: true } })
    wrapper.unmount()
  })
})
