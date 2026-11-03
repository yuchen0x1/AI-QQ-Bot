<template>
  <el-dialog v-model="visible" title="扫码添加 QQ 账号" width="min(480px, calc(100vw - 28px))" destroy-on-close @closed="reset">
    <div class="wizard">
      <div class="step-line"><span :class="{ active: step >= 1 }">1. 获取二维码</span><i></i><span :class="{ active: step >= 2 }">2. 手机 QQ 扫码</span><i></i><span :class="{ active: step >= 3 }">3. 接入完成</span></div>
      <div v-if="!configured" class="empty-state">
        <el-icon><WarningFilled /></el-icon>
        <h3>尚未配置扫码服务</h3>
        <p>管理员需要在服务器配置 NapCat 扫码实例。当前仍可使用“高级 OneBot 接入”添加已有协议端。</p>
      </div>
      <template v-else>
        <el-form v-if="!session" label-position="top" class="start-form">
          <el-form-item label="账号备注（可选）"><el-input v-model="name" maxlength="96" placeholder="例如：运营机器人" /></el-form-item>
          <el-form-item label="扫码实例"><el-select v-model="instanceId" style="width:100%"><el-option v-for="item in instances" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        </el-form>
        <div v-else class="qr-panel">
          <div v-if="session.status === 'online'" class="success-state"><el-icon><CircleCheckFilled /></el-icon><h3>QQ 登录成功</h3><p>正在写入账号并接入 OneBot。</p></div>
          <template v-else>
            <div class="qr-frame"><img v-if="qrSource" :src="qrSource" alt="QQ 登录二维码" /><div v-else class="qr-loading"><el-icon class="spin"><Loading /></el-icon><span>正在生成二维码…</span></div></div>
            <h3>{{ statusTitle }}</h3><p>{{ statusMessage }}</p>
            <el-progress v-if="session.status === 'qrcode_scanned' || session.status === 'initializing'" :percentage="70" :show-text="false" status="success" />
          </template>
        </div>
      </template>
    </div>
    <template #footer>
      <el-button @click="close">关闭</el-button>
      <template v-if="configured && !session"><el-button type="primary" :loading="loading" @click="start">生成二维码</el-button></template>
      <template v-else-if="session && session.status !== 'online'"><el-button @click="refresh" :loading="loading">刷新二维码</el-button><el-button type="primary" @click="cancel">取消本次登录</el-button></template>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { CircleCheckFilled, Loading, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'
import { api } from '../api'

type Instance = { id: string; name: string }
type Session = { session_id: string; instance_id: string; instance_name: string; qrcode: string; status: string; expires_at: number; message?: string; login_error?: string | null; login_phase?: string | null; account?: { id: number } | null }
const visible = ref(false), loading = ref(false), configured = ref(false), instances = ref<Instance[]>([]), instanceId = ref(''), name = ref(''), session = ref<Session | null>(null), timer = ref<number | undefined>()
const emit = defineEmits<{ completed: [] }>()
const step = computed(() => !session.value ? 1 : session.value.status === 'online' ? 3 : 2)
const qrSource = ref('')
async function renderQr(value: string) { qrSource.value = value.startsWith('data:image/') ? value : value ? await QRCode.toDataURL(value, { width: 300, margin: 2 }) : '' }

const statusTitle = computed(() => ({ waiting_qrcode: '请使用手机 QQ 扫描', qrcode_scanned: '已扫描，等待手机确认', initializing: '登录成功，正在启动协议', offline: 'QQ 当前离线', error: '二维码服务异常' } as Record<string, string>)[session.value?.status || 'waiting_qrcode'] || '等待扫码')
const statusMessage = computed(() => session.value?.login_error || session.value?.message || '打开手机 QQ，使用扫一扫完成授权。二维码仅短期有效。')
async function open() { visible.value = true; try { const { data } = await api.get('/napcat/instances'); instances.value = data; configured.value = instances.value.length > 0; instanceId.value = instances.value[0]?.id || '' } catch { configured.value = false } }
async function start() { loading.value = true; try { const { data } = await api.post('/napcat/login/start', { instance_id: instanceId.value || undefined, name: name.value || undefined }); session.value = data; await renderQr(data.qrcode); poll() } finally { loading.value = false } }
async function refresh() { if (!session.value) return; loading.value = true; try { const { data } = await api.post(`/napcat/login/${session.value.session_id}/refresh`); session.value = data; await renderQr(data.qrcode) } finally { loading.value = false } }
function poll() { stopPoll(); timer.value = window.setInterval(async () => { if (!session.value || session.value.status === 'online') return stopPoll(); try { const previousQr = session.value.qrcode; const { data } = await api.get(`/napcat/login/${session.value.session_id}`); session.value = { ...session.value, ...data }; if (data.qrcode && data.qrcode !== previousQr) await renderQr(data.qrcode); if (data.status === 'online') { stopPoll(); ElMessage.success('QQ 账号已接入'); emit('completed') } } catch { stopPoll() } }, 2500) }
async function cancel() { if (!session.value) return; try { await api.delete(`/napcat/login/${session.value.session_id}`) } finally { stopPoll(); session.value = null } }
function stopPoll() { if (timer.value) { clearInterval(timer.value); timer.value = undefined } }
function close() { visible.value = false; stopPoll() }
function reset() { session.value = null; name.value = ''; qrSource.value = ''; stopPoll() }
onBeforeUnmount(stopPoll)
defineExpose({ open })
</script>
<style scoped>
.wizard{min-height:360px}.step-line{display:flex;align-items:center;gap:8px;color:#738097;font-size:11px;margin:0 0 26px}.step-line span.active{color:#9d8cff}.step-line i{height:1px;background:#2c3748;flex:1}.start-form{max-width:330px;margin:60px auto}.qr-panel{text-align:center}.qr-frame{width:280px;height:280px;margin:8px auto 18px;background:#fff;border-radius:12px;display:grid;place-items:center;overflow:hidden}.qr-frame img{width:100%;height:100%;object-fit:contain}.qr-loading{color:#66758e;display:flex;flex-direction:column;gap:12px;align-items:center}.spin{animation:spin 1s linear infinite}.qr-panel h3,.success-state h3,.empty-state h3{margin:8px 0;color:#e7edf7}.qr-panel p,.success-state p,.empty-state p{color:#8996aa;font-size:12px;line-height:1.7}.success-state{padding:85px 20px}.success-state .el-icon{font-size:56px;color:#52c28c}.empty-state{text-align:center;padding:80px 30px}.empty-state .el-icon{font-size:48px;color:#e5a74e}@keyframes spin{to{transform:rotate(360deg)}}
</style>
