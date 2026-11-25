<template>
  <el-dialog :model-value="modelValue" :title="task ? '编辑任务' : '创建任务'" width="min(620px, calc(100vw - 28px))" destroy-on-close @update:model-value="$emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" label-position="top" :rules="rules">
      <el-form-item label="任务名称" prop="name"><el-input v-model="form.name" maxlength="190" /></el-form-item>
      <el-form-item label="任务类型" prop="task_type">
        <el-select v-model="form.task_type" :disabled="Boolean(task)" @change="resetPayload">
          <el-option v-for="type in types" :key="type.value" :label="type.label" :value="type.value" />
        </el-select>
      </el-form-item>
      <template v-if="['group_message', 'group_announcement', 'ai_summary', 'online_check'].includes(form.task_type)">
        <el-form-item :label="form.task_type === 'online_check' ? '告警账号（可选）' : '发送账号'">
          <el-select v-model="payloadAccount" clearable @change="changeAccount">
            <el-option v-for="account in accounts" :key="account.id" :value="account.id" :label="account.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="已登记群聊（内部映射 ID）">
          <el-select v-model="payloadGroup" filterable remote :remote-method="searchGroups" :loading="directory.loading.value" :disabled="!payloadAccount">
            <el-option v-for="group in directory.items.value" :key="group.id" :value="group.group_number" :label="`${groupTitle(group)} · ${groupNumberText(group)}`" />
            <template #footer><el-button v-if="directory.items.value.length < directory.total.value" link @click="directory.more">加载更多群聊</el-button></template>
          </el-select>
          <el-alert v-if="directory.error.value" type="error" :title="directory.error.value" :closable="false" />
        </el-form-item>
      </template>
      <el-form-item v-if="['group_message', 'group_announcement'].includes(form.task_type)" label="消息内容">
        <el-input v-model="form.payload.content" type="textarea" :rows="4" maxlength="4000" show-word-limit />
      </el-form-item>
      <el-form-item v-if="form.task_type === 'github_check'" label="仓库 ID（留空检查当前用户授权仓库）"><el-input-number v-model="form.payload.repository_id" :min="1" /></el-form-item>
      <template v-if="form.task_type === 'ai_summary'">
        <el-form-item label="总结最近小时数"><el-input-number v-model="form.payload.hours" :min="1" :max="168" /></el-form-item>
        <el-form-item label="发送总结到群"><el-switch v-model="form.payload.send_to_group" /></el-form-item>
      </template>
      <el-form-item v-if="form.task_type === 'backup'" label="保留备份份数"><el-input-number v-model="form.payload.keep" :min="1" :max="365" /></el-form-item>
      <el-form-item v-if="form.task_type === 'push_retry'" label="每次最多重试记录"><el-input-number v-model="form.payload.limit" :min="1" :max="200" /></el-form-item>
      <el-form-item v-if="form.task_type === 'clean_expired_data'" label="保留天数（0 停用清理；未填写使用系统设置）"><el-input-number v-model="form.payload.days" :min="0" :max="3650" /></el-form-item>
      <div class="task-columns">
        <el-form-item label="调度方式"><el-select v-model="form.schedule_kind"><el-option label="固定间隔" value="interval" /><el-option label="Cron 表达式" value="cron" /></el-select></el-form-item>
        <el-form-item v-if="form.schedule_kind === 'interval'" label="间隔秒数"><el-input-number v-model="form.interval_seconds" :min="30" :max="2592000" /></el-form-item>
        <el-form-item v-else label="Cron 表达式（5 段）"><el-input v-model="form.cron_expr" placeholder="0 9 * * *" /></el-form-item>
        <el-form-item label="最大重试次数"><el-input-number v-model="form.max_retries" :min="0" :max="5" /></el-form-item>
        <el-form-item label="整次执行超时（秒）"><el-input-number v-model="form.timeout_seconds" :min="10" :max="3600" /></el-form-item>
      </div>
      <el-form-item label="启用任务"><el-switch v-model="form.enabled" /></el-form-item>
      <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
      <el-alert v-if="preview" type="info" :closable="false" :title="`服务端调度时区：${preview.timezone}`"><div v-for="time in preview.next_runs" :key="time">{{ time }}</div></el-alert>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button :loading="previewing" @click="previewSchedule">校验与预览</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存任务</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { groupNumberText, groupTitle } from '../groupDisplay'
import { useAccountDirectory } from '../composables/useAccountDirectory'

const props = defineProps<{ modelValue: boolean; task?: any }>()
const emit = defineEmits(['update:modelValue', 'saved'])
const formRef = ref<any>()
const accounts = ref<any[]>([])
const saving = ref(false)
const previewing = ref(false)
const preview = ref<any>(null)
const error = ref('')
const form = reactive<any>({ name: '', task_type: 'health_check', schedule_kind: 'interval', interval_seconds: 3600, cron_expr: '', payload: {}, enabled: true, max_retries: 2, timeout_seconds: 300 })
const types = [
  { value: 'github_check', label: '指定授权仓库检查' }, { value: 'github_check_all', label: '当前用户授权仓库检查' },
  { value: 'group_message', label: '定时群消息' }, { value: 'online_check', label: '在线状态检查' },
  { value: 'ai_summary', label: 'AI 群聊总结' }, { value: 'health_check', label: '系统健康检查' },
  { value: 'backup', label: '数据库备份' }, { value: 'push_retry', label: '失败推送重试' },
  { value: 'clean_expired_data', label: '过期数据清理' },
]
const rules = { name: [{ required: true, message: '请填写任务名称' }], task_type: [{ required: true, message: '请选择类型' }] }
const directory = useAccountDirectory<any>(async (id, page, keyword) => (await api.get('/groups', { params: { account_id: id, page, keyword, page_size: 50 } })).data)
const payloadAccount = computed({ get: () => form.payload[form.task_type === 'online_check' ? 'notify_account_id' : 'account_id'], set: value => { form.payload[form.task_type === 'online_check' ? 'notify_account_id' : 'account_id'] = value } })
const payloadGroup = computed({ get: () => form.payload[form.task_type === 'online_check' ? 'notify_group' : 'group_number'], set: value => { form.payload[form.task_type === 'online_check' ? 'notify_group' : 'group_number'] = value } })
const searchGroups = (query: string) => directory.load(payloadAccount.value || null, query)
function changeAccount() { payloadGroup.value = undefined; void searchGroups('') }
const payloadFields: Record<string, string[]> = {
  group_message: ['account_id', 'group_number', 'content', 'also_send_message'],
  group_announcement: ['account_id', 'group_number', 'content', 'also_send_message'],
  ai_summary: ['account_id', 'group_number', 'hours', 'send_to_group'],
  github_check: ['repository_id'], github_check_all: [], health_check: [],
  backup: ['keep'], push_retry: ['limit'], online_check: ['notify_account_id', 'notify_group'],
  clean_expired_data: ['days'],
}
function payloadDefaults(type: string) {
  if (type === 'ai_summary') return { hours: 12, send_to_group: true }
  if (type === 'backup') return { keep: 14 }
  if (type === 'push_retry') return { limit: 20 }
  if (['group_message', 'group_announcement'].includes(type)) return { content: '', also_send_message: true }
  return {}
}
function resetPayload() { form.payload = payloadDefaults(form.task_type); preview.value = null; void directory.load(null) }
function requestPayload() {
  const payload = Object.fromEntries((payloadFields[form.task_type] || []).filter(key => form.payload[key] !== undefined && form.payload[key] !== null).map(key => [key, form.payload[key]]))
  return { name: form.name, task_type: form.task_type, schedule_kind: form.schedule_kind, interval_seconds: form.schedule_kind === 'interval' ? form.interval_seconds : null, cron_expr: form.schedule_kind === 'cron' ? form.cron_expr : null, payload, enabled: form.enabled, max_retries: form.max_retries, timeout_seconds: form.timeout_seconds }
}
function describeError(failure: any) {
  const detail = failure?.response?.data?.detail
  return Array.isArray(detail) ? detail.map(item => `${item.loc?.join('.') || ''}: ${item.msg}`).join('；') : detail || '请求失败，请重试'
}
async function previewSchedule() {
  try { await formRef.value?.validate() } catch { return false }
  previewing.value = true
  error.value = ''
  try { preview.value = (await api.post('/tasks/preview', requestPayload())).data; return true }
  catch (failure) { error.value = describeError(failure); return false }
  finally { previewing.value = false }
}
async function save() {
  if (saving.value || !await previewSchedule()) return
  saving.value = true
  try {
    const payload = requestPayload()
    if (props.task) {
      const { task_type, ...update } = payload
      await api.put(`/tasks/${props.task.id}`, update)
    } else await api.post('/tasks', payload)
    ElMessage.success('任务已保存')
    emit('saved')
    emit('update:modelValue', false)
  } catch (failure) { error.value = describeError(failure) }
  finally { saving.value = false }
}
watch(() => props.modelValue, async value => {
  if (!value) return
  Object.assign(form, { name: '', task_type: 'health_check', schedule_kind: 'interval', interval_seconds: 3600, cron_expr: '', payload: {}, enabled: true, max_retries: 2, timeout_seconds: 300 }, props.task || {})
  form.payload = { ...payloadDefaults(form.task_type), ...(props.task?.payload || {}) }
  preview.value = null
  error.value = ''
  try { accounts.value = (await api.get('/accounts')).data } catch (failure) { error.value = describeError(failure) }
  await searchGroups('')
})
</script>

<style scoped>
.task-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }
.el-select, .el-input-number { width: 100%; }
@media (max-width: 560px) { .task-columns { grid-template-columns: 1fr; } }
</style>
