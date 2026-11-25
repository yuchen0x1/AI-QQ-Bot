import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import MessagesView from '../views/MessagesView.vue'
import AIView from '../views/AIView.vue'
import LoginView from '../views/LoginView.vue'
import AccountsView from '../views/AccountsView.vue'
import TaskEditor from '../components/TaskEditor.vue'
import PluginsView from '../views/PluginsView.vue'
import PushRulesView from '../views/PushRulesView.vue'
import PushRecordsView from '../views/PushRecordsView.vue'

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), request: vi.fn(), replace: vi.fn() }))
vi.mock('../api', async () => {
  const { ref, shallowRef } = await import('vue')
  return { api: mocks, AI_TIMEOUT: 630000, useRealtimeSocket: () => ({ state: ref('open'), lastMessage: shallowRef(null), close: vi.fn(), reconnect: vi.fn() }) }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: mocks.replace }), useRoute: () => ({ query: {} }) }))

const accounts = [
  { id: 1, name: '账号 A', runtime_state: 'online', capabilities: { send_group_message: true, send_private_message: true }, enabled: true },
  { id: 2, name: '账号 B', runtime_state: 'online', capabilities: { send_group_message: true, send_private_message: true }, enabled: true },
]
let permissions = ['*']
let mounted: ReturnType<typeof mount>[] = []
const SelectControl = {
  name: 'ElSelect',
  props: ['modelValue', 'placeholder', 'disabled', 'loading', 'remoteMethod'],
  emits: ['update:modelValue', 'change'],
  template: '<div><select :aria-label="placeholder" :disabled="disabled" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select><slot name="footer" /></div>',
}
const OptionControl = { name: 'ElOption', props: ['value', 'label', 'disabled'], template: '<option :value="value" :disabled="disabled"><slot>{{ label }}</slot></option>' }
function render(component: any, props: Record<string, any> = {}) {
  // Business components stay real; library selects use native controls because
  // their popper geometry and focus loops require an actual browser layout.
  const wrapper = mount(component, { props, attachTo: document.body, global: { plugins: [createPinia(), ElementPlus], stubs: { ElSelect: SelectControl, ElOption: OptionControl, teleport: true, transition: false, 'transition-group': false }, mocks: { $router: { push: vi.fn() } } } })
  mounted.push(wrapper)
  return wrapper
}
function clickText(wrapper: any, text: string) {
  const button = wrapper.findAll('button').find((item: any) => item.text() === text)
  expect(button, `找不到按钮：${text}`).toBeTruthy()
  return button!.trigger('click')
}
beforeEach(() => {
  permissions = ['*']
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {} }))
  mocks.get.mockImplementation(async (url: string) => {
    if (url === '/auth/me') return { data: { permissions } }
    if (url === '/accounts') return { data: accounts }
    if (url === '/messages') return { data: { items: [], total: 0 } }
    if (url === '/groups' || url === '/messages/contacts' || url === '/ai/usage') return { data: { items: [], total: 0 } }
    if (url === '/ai/providers') return { data: [{ id: 3, name: '测试供应商', kind: 'openai', enabled: true, base_url: 'https://example.com', has_api_key: true }] }
    if (url === '/ai/models') return { data: [{ id: 41, provider_id: 3, provider_name: '测试供应商', model_name: 'model-original', display_name: '原模型', temperature: 0.7, max_tokens: 2048, timeout_seconds: 60, retries: 1, priority: 100, is_default: true, is_fallback: false, allow_cross_provider_fallback: false, enabled: true }] }
    return { data: [] }
  })
  mocks.post.mockResolvedValue({ data: { ok: true } })
  mocks.put.mockResolvedValue({ data: { id: 41, enabled: false } })
})
afterEach(() => {
  for (const wrapper of mounted) wrapper.unmount()
  mounted = []
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('消息工作台行为', () => {
  it('收到增量消息时保留历史分页，显示未读并从最新已知游标继续', async () => {
    vi.useFakeTimers()
    const original = mocks.get.getMockImplementation()!
    mocks.get.mockImplementation((url: string, options?: any) => {
      if (url !== '/messages') return original(url, options)
      if (options.params.after_id !== undefined) return Promise.resolve({ data: { items: options.params.after_id === 3 ? [{ id: 4, content: '新到达消息' }] : [], total: 1 } })
      return Promise.resolve({ data: { items: options.params.page === 2 ? [{ id: 1, content: '保留历史页面' }] : [{ id: 3, content: '原来最新消息' }], total: 40 } })
    })
    const wrapper = render(MessagesView)
    await flushPromises()
    const pagination = wrapper.findComponent({ name: 'ElPagination' })
    pagination.vm.$emit('update:current-page', 2)
    pagination.vm.$emit('current-change', 2)
    await flushPromises()
    expect(wrapper.text()).toContain('保留历史页面')
    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()
    expect(wrapper.text()).toContain('1 条新消息')
    expect(wrapper.text()).toContain('第 2 页')
    expect(wrapper.text()).toContain('保留历史页面')
    expect(wrapper.text()).not.toContain('新到达消息')
    expect(mocks.get).toHaveBeenCalledWith('/messages', expect.objectContaining({ params: expect.objectContaining({ after_id: 3 }) }))
  })

  it('快速从 A 切 B 后，A 的迟到群列表不会覆盖 B，发送窗口也不覆盖历史目录', async () => {
    const pending = new Map<number, (value: any) => void>()
    const original = mocks.get.getMockImplementation()!
    mocks.get.mockImplementation((url: string, options?: any) => url === '/groups'
      ? new Promise(resolve => pending.set(options.params.account_id, resolve))
      : original(url, options))
    const wrapper = render(MessagesView)
    await flushPromises()
    const accountButton = (name: string) => wrapper.findAll('button.message-nav-item').find(button => button.text().includes(name))!
    await accountButton('账号 A').trigger('click')
    await accountButton('账号 B').trigger('click')
    pending.get(2)!({ data: { items: [{ id: 22, group_number: 222, name: 'B 的群' }], total: 1 } })
    await flushPromises()
    pending.get(1)!({ data: { items: [{ id: 11, group_number: 111, name: 'A 的迟到群' }], total: 1 } })
    await flushPromises()
    expect(wrapper.find('[aria-label="群聊列表"]').text()).toContain('B 的群')
    expect(wrapper.find('[aria-label="群聊列表"]').text()).not.toContain('A 的迟到群')
    await clickText(wrapper, '发送消息')
    const sendSelect = wrapper.findAllComponents({ name: 'ElSelect' }).find(select => select.props('placeholder') === '选择 QQ 账号')!
    sendSelect.vm.$emit('update:modelValue', 1)
    sendSelect.vm.$emit('change', 1)
    await nextTick()
    pending.get(1)!({ data: { items: [{ id: 11, group_number: 111, name: '发送 A 的群' }], total: 1 } })
    await flushPromises()
    expect(wrapper.find('[aria-label="群聊列表"]').text()).toContain('B 的群')
  })

  it('第 201 个群可通过分页取得并以内部映射 ID 发送', async () => {
    const original = mocks.get.getMockImplementation()!
    mocks.get.mockImplementation((url: string, options?: any) => {
      if (url === '/accounts') return Promise.resolve({ data: [accounts[0]] })
      if (url === '/groups') {
        const start = (options.params.page - 1) * 50
        const items = Array.from({ length: Math.min(50, 201 - start) }, (_, index) => ({ id: start + index + 1, group_number: 1000 + start + index + 1, name: `登记群 ${start + index + 1}` }))
        return Promise.resolve({ data: { items, total: 201 } })
      }
      return original(url, options)
    })
    const wrapper = render(MessagesView)
    await flushPromises()
    await clickText(wrapper, '发送消息')
    await flushPromises()
    // The footer remains operable even when all 200 earlier options are loaded.
    for (let page = 1; page <= 4; page++) {
      const more = wrapper.findAll('button').find(button => button.text() === '加载更多群聊')!
      expect(more).toBeTruthy()
      await more.trigger('click')
      await flushPromises()
    }
    const target = wrapper.findAllComponents({ name: 'ElSelect' }).find(select => select.props('placeholder') === '先选账号，再选择群聊')!
    expect(target.findAllComponents({ name: 'ElOption' }).some(option => option.props('label').includes('登记群 201'))).toBe(true)
    target.vm.$emit('update:modelValue', '1201')
    await wrapper.find('textarea').setValue('确认发送')
    await clickText(wrapper, '发送')
    await flushPromises()
    expect(mocks.post).toHaveBeenCalledWith('/messages/send', { account_id: 1, qq_group: 1201, content: '确认发送' })
  })
})

describe('模型编辑与只读权限', () => {
  it('编辑保留模型主键与 Model ID，PUT 保存超时和重试参数；可以原地停用', async () => {
    const wrapper = render(AIView)
    await flushPromises()
    await wrapper.find('button[aria-label="编辑模型 原模型"]').trigger('click')
    await flushPromises()
    const readonly = wrapper.find('input[readonly][placeholder="例如：deepseek-chat / gpt-4o-mini"]')
    expect((readonly.element as HTMLInputElement).value).toBe('model-original')
    const formItem = (label: string) => wrapper.findAll('.el-form-item').find(item => item.find('.el-form-item__label').exists() && item.find('.el-form-item__label').text() === label)!
    await formItem('超时（秒）').find('input').setValue('120')
    await formItem('失败重试次数').find('input').setValue('3')
    await clickText(wrapper, '保存模型')
    await flushPromises()
    expect(mocks.put).toHaveBeenCalledWith('/ai/models/41', expect.objectContaining({ timeout_seconds: 120, retries: 3, allow_cross_provider_fallback: false }))
    const saved = mocks.put.mock.calls[0][1]
    expect(saved).not.toHaveProperty('provider_id')
    expect(saved).not.toHaveProperty('model_name')
    await clickText(wrapper, '停用')
    await flushPromises()
    expect(mocks.put).toHaveBeenLastCalledWith('/ai/models/41', { enabled: false })
  })

  it('viewer 无模型写入、发送及账号启停入口', async () => {
    permissions = ['ai:view', 'message:view', 'account:view']
    const ai = render(AIView)
    const messages = render(MessagesView)
    const accountsView = render(AccountsView)
    await flushPromises()
    expect(ai.find('button[aria-label="编辑模型 原模型"]').exists()).toBe(false)
    expect(ai.findAll('button').some(button => button.text() === '添加模型')).toBe(false)
    expect(messages.findAll('button').some(button => button.text() === '发送消息')).toBe(false)
    const startStop = accountsView.findAll('button').filter(button => ['启动', '停止', '重启', '测试连接'].some(label => button.text() === label))
    expect(startStop.length).toBeGreaterThan(0)
    expect(startStop.every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(mocks.post).not.toHaveBeenCalled()
  })
})

describe('任务参数与通用操作权限', () => {
  it('切换任务类型仅提交对应参数，空的可选数值不会写为 null', async () => {
    const wrapper = render(TaskEditor, { modelValue: false })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    await wrapper.find('input[maxlength="190"]').setValue('参数校验任务')
    const taskType = wrapper.findAllComponents({ name: 'ElSelect' })[0]!
    const cases = [['backup', { keep: 14 }], ['push_retry', { limit: 20 }], ['health_check', {}], ['clean_expired_data', {}]] as const
    for (const [type, expected] of cases) {
      taskType.vm.$emit('update:modelValue', type)
      taskType.vm.$emit('change', type)
      await nextTick()
      if (type === 'clean_expired_data') wrapper.findComponent({ name: 'ElInputNumber' }).vm.$emit('update:modelValue', null)
      await clickText(wrapper, '校验与预览')
      await flushPromises()
      expect(mocks.post).toHaveBeenLastCalledWith('/tasks/preview', expect.objectContaining({ task_type: type, payload: expected }))
    }
    wrapper.findComponent({ name: 'ElInputNumber' }).vm.$emit('update:modelValue', 0)
    await clickText(wrapper, '校验与预览')
    await flushPromises()
    expect(mocks.post).toHaveBeenLastCalledWith('/tasks/preview', expect.objectContaining({ payload: { days: 0 } }))
  })

  it('只读用户可看插件指标，但不能扫描或重载插件', async () => {
    permissions = ['plugin:view']
    const original = mocks.get.getMockImplementation()!
    mocks.get.mockImplementation((url: string, options?: any) => url === '/plugins' ? Promise.resolve({ data: [{ id: 5, name: '只读插件', enabled: true }] }) : original(url, options))
    const wrapper = render(PluginsView)
    await flushPromises()
    expect(wrapper.findAll('button').some(button => button.text() === '扫描插件目录')).toBe(false)
    const metrics = wrapper.findAll('button').find(button => button.text() === '指标')!
    const reload = wrapper.findAll('button').find(button => button.text() === '重新加载')!
    expect(metrics.attributes('disabled')).toBeUndefined()
    expect(reload.attributes('disabled')).toBeDefined()
    await metrics.trigger('click')
    await flushPromises()
    expect(mocks.get).toHaveBeenCalledWith('/plugins/5/metrics')
    expect(mocks.request).not.toHaveBeenCalled()
  })

  it('有推送管理权限即可新增规则，并能加载第 201 个群', async () => {
    permissions = ['push:manage', 'push:view', 'github:view', 'account:view', 'group:view']
    const original = mocks.get.getMockImplementation()!
    mocks.get.mockImplementation((url: string, options?: any) => {
      if (url === '/groups') {
        const start = (options.params.page - 1) * 50
        return Promise.resolve({ data: { items: Array.from({ length: Math.min(50, 201 - start) }, (_, index) => ({ id: start + index + 1, group_number: 1001 + start + index, name: `推送登记群 ${start + index + 1}` })), total: 201 } })
      }
      return original(url, options)
    })
    const wrapper = render(PushRulesView)
    await flushPromises()
    await clickText(wrapper, '新增规则')
    const account = wrapper.findAll('.el-form-item').find(item => item.find('.el-form-item__label').text() === '发送 QQ 账号')!.findComponent({ name: 'ElSelect' })
    account.vm.$emit('update:modelValue', 1)
    account.vm.$emit('change', 1)
    await flushPromises()
    for (let page = 1; page <= 4; page++) { await clickText(wrapper, '加载更多群聊'); await flushPromises() }
    const target = wrapper.findAll('.el-form-item').find(item => item.find('.el-form-item__label').text() === '目标 QQ 群')!
    expect(target.text()).toContain('推送登记群 201')
    expect(target.text()).toContain('内部映射 ID 1201')
    expect(mocks.get).toHaveBeenCalledWith('/groups', expect.objectContaining({ params: expect.objectContaining({ page: 5, page_size: 50 }) }))
  })

  it('推送记录展示服务端错误分类、重试耗尽与处理建议并保留原错误', async () => {
    permissions = ['push:view']
    const original = mocks.get.getMockImplementation()!
    mocks.get.mockImplementation((url: string, options?: any) => url === '/github/push-records'
      ? Promise.resolve({ data: { items: [{ id: 9, account_id: 1, qq_group: 1201, status: 'failed', retries: 3, error: '平台连接中断', error_category: 'connection', retries_exhausted: true, next_action: '自动重试次数已耗尽，请检查连接并确认平台投递结果后再手动重推' }], total: 1 } })
      : original(url, options))
    const wrapper = render(PushRecordsView)
    await flushPromises()
    expect(wrapper.text()).toContain('连接异常')
    expect(wrapper.text()).toContain('已耗尽')
    expect(wrapper.text()).toContain('平台连接中断')
    expect(wrapper.text()).toContain('确认平台投递结果后再手动重推')
    expect(wrapper.text()).toContain('内部映射 ID 1201')
    expect(wrapper.findAll('button').find(button => button.text() === '重新推送')!.attributes('disabled')).toBeDefined()
  })
})

it('登录要求两步验证时，仅提交 challenge 与 OTP 后进入控制台', async () => {
  mocks.post.mockImplementation(async (url: string) => ({ data: url === '/auth/login' ? { requires_2fa: true, challenge_token: 'one-time-challenge' } : { ok: true } }))
  const wrapper = render(LoginView)
  await wrapper.find('input[placeholder="请输入用户名"]').setValue('operator')
  await wrapper.find('input[placeholder="请输入密码"]').setValue('correct-password')
  await clickText(wrapper, '登录控制台')
  await flushPromises()
  expect(mocks.replace).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('完成两步验证')
  await wrapper.find('input[autocomplete="one-time-code"]').setValue('123456')
  await clickText(wrapper, '验证并登录')
  await flushPromises()
  expect(mocks.post).toHaveBeenLastCalledWith('/auth/login/2fa', { challenge_token: 'one-time-challenge', code: '123456' })
  expect(mocks.replace).toHaveBeenCalledWith('/')
})
