<template>
  <div class="login-page">
    <div class="login-grid" aria-hidden="true"></div>
    <div class="login-glow glow-a" aria-hidden="true"></div>
    <div class="login-glow glow-b" aria-hidden="true"></div>

    <main class="login-shell">
      <section class="login-visual" aria-label="平台介绍">
        <div class="login-brand">
          <span class="brand-mark" aria-hidden="true"><AppIcon name="bot" :size="21" :stroke-width="1.8" /></span>
          <span class="login-brand-copy">
            <b>QBOT<span> AI</span></b>
            <small>INTELLIGENT BOT OPERATIONS</small>
          </span>
        </div>

        <div class="login-visual-copy">
          <div class="eyebrow">OPERATIONS CONTROL</div>
          <h1>让机器人集群的<br /><span>每一次运行</span>都有据可循</h1>
          <p>统一管理 QQ 机器人账号、群聊策略、AI 模型路由、GitHub 监控与自动化任务。关键操作通过服务端 API 执行，并写入审计记录。</p>
        </div>

        <div class="login-features" aria-label="平台能力">
          <span class="login-feature"><AppIcon name="activity" :size="14" />实时运行监控</span>
          <span class="login-feature"><AppIcon name="layers" :size="14" />多账号隔离</span>
          <span class="login-feature"><AppIcon name="sparkles" :size="14" />AI 模型路由</span>
          <span class="login-feature"><AppIcon name="shield" :size="14" />安全审计</span>
        </div>

        <div class="login-orbit" aria-hidden="true"><i></i><i></i><i></i></div>
      </section>

      <section class="login-panel" aria-labelledby="login-panel-title">
        <div class="login-mobile-brand">
          <span class="brand-mark" aria-hidden="true"><AppIcon name="bot" :size="20" :stroke-width="1.8" /></span>
          <span class="login-brand-copy">
            <b>QBOT<span> AI</span></b>
            <small>INTELLIGENT BOT OPERATIONS</small>
          </span>
        </div>

        <div class="login-heading">
          <div class="eyebrow">{{ requires2fa ? 'TWO-FACTOR VERIFICATION' : 'ADMIN ACCESS' }}</div>
          <h2 id="login-panel-title">{{ requires2fa ? '完成两步验证' : '登录管理控制台' }}</h2>
          <p>{{ requires2fa ? '密码校验已通过，请继续完成身份验证。' : '使用管理员账户进入受保护的运维会话。' }}</p>
        </div>

        <el-form
          v-if="!requires2fa"
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          aria-labelledby="login-panel-title"
          @keyup.enter="submit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              ref="usernameInput"
              v-model="form.username"
              size="large"
              placeholder="请输入用户名"
              autocomplete="username"
              autofocus
              :disabled="loading"
            >
              <template #prefix><AppIcon name="user" :size="15" /></template>
            </el-input>
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              size="large"
              placeholder="请输入密码"
              type="password"
              show-password
              autocomplete="current-password"
              :disabled="loading"
            >
              <template #prefix><AppIcon name="lock" :size="15" /></template>
            </el-input>
          </el-form-item>
          <el-button class="login-submit" type="primary" size="large" :loading="loading" :disabled="loading" @click="submit">
            登录控制台<AppIcon name="arrow-right" :size="15" />
          </el-button>
        </el-form>

        <el-form
          v-else
          ref="otpFormRef"
          :model="otpForm"
          :rules="otpRules"
          label-position="top"
          aria-labelledby="login-panel-title"
          @keyup.enter="verifyOtp"
        >
          <div class="otp-hint" role="status">
            <span class="otp-hint-icon"><AppIcon name="shield" :size="17" /></span>
            <div>
              <b>请输入身份验证器中的 6 位动态验证码</b>
              <small>验证码会定时更新，请确保验证设备时间准确。</small>
            </div>
          </div>
          <el-form-item label="动态验证码" prop="code">
            <el-input
              ref="otpInput"
              v-model="otpForm.code"
              size="large"
              maxlength="6"
              inputmode="numeric"
              autocomplete="one-time-code"
              placeholder="000000"
              :disabled="loading"
            >
              <template #prefix><AppIcon name="key" :size="15" /></template>
            </el-input>
          </el-form-item>
          <el-button class="login-submit" type="primary" size="large" :loading="loading" :disabled="loading" @click="verifyOtp">
            验证并登录<AppIcon name="arrow-right" :size="15" />
          </el-button>
          <el-button class="back-login" text :disabled="loading" @click="resetLogin">使用其他账号登录</el-button>
        </el-form>

        <div class="login-foot">
          <span class="login-session"><span class="pulse-dot" aria-hidden="true"></span>安全会话 · HttpOnly Cookie</span>
          <span class="login-version">QBOT AI · v{{ uiVersion }}</span>
        </div>
        <p class="login-audit-note"><AppIcon name="shield" :size="13" />登录与关键管理操作会写入审计日志。</p>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import { version as uiVersion } from '../../package.json'

const router = useRouter()
const route = useRoute()
const formRef = ref()
const otpFormRef = ref()
const usernameInput = ref()
const otpInput = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const otpForm = reactive({ code: '' })
const requires2fa = ref(false)
let challengeToken = ''

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const otpRules = {
  code: [{ required: true, len: 6, message: '请输入 6 位验证码', trigger: 'blur' }],
}

watch(requires2fa, async (enabled) => {
  await nextTick()
  if (enabled) otpInput.value?.focus?.()
  else usernameInput.value?.focus?.()
})

function finishLogin() {
  ElMessage.success('登录成功')
  router.replace(String(route.query.next || '/'))
}

async function submit() {
  if (loading.value) return
  await formRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    loading.value = true
    try {
      const { data } = await api.post('/auth/login', form)
      if (data.requires_2fa) {
        challengeToken = data.challenge_token
        requires2fa.value = true
        otpForm.code = ''
      } else {
        finishLogin()
      }
    } finally {
      loading.value = false
    }
  })
}

async function verifyOtp() {
  if (loading.value) return
  await otpFormRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    loading.value = true
    try {
      await api.post('/auth/login/2fa', { challenge_token: challengeToken, code: otpForm.code })
      finishLogin()
    } finally {
      loading.value = false
    }
  })
}

function resetLogin() {
  requires2fa.value = false
  challengeToken = ''
  otpForm.code = ''
}
</script>

<style scoped>
.login-mobile-brand {
  display: none;
  align-items: center;
  gap: 11px;
  margin-bottom: 20px;
}

.otp-hint {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--brand-line);
  border-radius: var(--radius-md);
  background: var(--brand-soft);
}

.otp-hint-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--surface) 64%, transparent);
  color: var(--brand-strong);
}

.otp-hint b {
  display: block;
  margin-bottom: 3px;
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.5;
}

.otp-hint small {
  display: block;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.6;
}

.login-session {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.login-foot {
  flex-wrap: wrap;
  row-gap: 6px;
}

.login-audit-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 14px 0 0;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.5;
}

@media (max-width: 1024px) {
  .login-mobile-brand {
    display: flex;
  }
}

@media (max-width: 480px) {
  .login-version {
    width: 100%;
    margin-left: 0;
  }
}
</style>
