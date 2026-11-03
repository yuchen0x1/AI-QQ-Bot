<template>
  <div class="login-page"><div class="login-grid"></div><div class="login-glow glow-a"></div><div class="login-glow glow-b"></div>
    <section class="login-panel"><div class="login-brand"><div class="brand-mark large"><el-icon><Promotion /></el-icon></div><div><b>QBOT<span> AI</span></b><small>CONTROL CENTER</small></div></div>
      <div class="login-heading"><div class="eyebrow">WELCOME BACK</div><h1>登录管理控制台</h1><p>安全管理你的 QQ 机器人集群</p></div>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="用户名" prop="username"><el-input v-model="form.username" size="large" placeholder="请输入用户名" :prefix-icon="User" autocomplete="username" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" size="large" placeholder="请输入密码" type="password" show-password :prefix-icon="Lock" autocomplete="current-password" /></el-form-item>
        <el-button class="login-submit" type="primary" size="large" :loading="loading" @click="submit">登录控制台 <el-icon><ArrowRight /></el-icon></el-button>
      </el-form><div class="login-foot"><span class="pulse-dot"></span>安全连接已启用 <span class="login-version">QBOT AI · 1.0</span></div>
    </section><div class="login-side-copy"><div class="login-side-orb"><span></span><span></span><span></span></div><h2>一个平台<br/>掌控所有机器人</h2><p>多账号隔离 · 智能群管理 · AI 对话<br/>GitHub 版本追踪 · 自动化任务</p></div>
  </div>
</template>
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const router = useRouter(), route = useRoute(), formRef = ref(), loading = ref(false)
const form = reactive({ username: '', password: '' })
const rules = { username: [{ required: true, message: '请输入用户名', trigger: 'blur' }], password: [{ required: true, message: '请输入密码', trigger: 'blur' }] }
async function submit() {
  await formRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    loading.value = true
    try { const { data } = await api.post('/auth/login', form); localStorage.setItem('qbot_token', data.access_token); ElMessage.success('登录成功'); router.replace(String(route.query.next || '/')) }
    finally { loading.value = false }
  })
}
</script>
