<template>
  <div class="page-heading"><div><h1>新手指引与操作文档</h1><p>从第一次启动，到仓库动态送进群；按步骤完成自己的设置。</p></div><el-button @click="restart">重新开始教学</el-button></div>
  <el-tabs v-model="tab">
    <el-tab-pane label="分步设置" name="setup">
      <div class="guide-layout">
        <nav class="surface guide-index" aria-label="设置步骤"><p>你的设置进度</p><button v-for="(lesson, index) in setupLessons" :key="lesson.title" :class="{ selected: active === index }" @click="selectStep(index)"><span>{{ state.steps?.[index]?.ready ? '✓' : index + 1 }}</span><div><b>{{ lesson.title }}</b><small>{{ state.steps?.[index]?.ready ? '检查通过' : index === 4 ? '可稍后设置' : '等待设置' }}</small></div></button></nav>
        <section class="surface guide-lesson" aria-live="polite">
          <div class="lesson-progress">步骤 {{ active + 1 }} / {{ setupLessons.length }}</div>
          <h2>{{ current.title }}</h2><p>{{ current.intro }}</p>
          <ol><li v-for="text in current.steps" :key="text">{{ text }}</li></ol>
          <el-alert :title="current.note" type="info" :closable="false" />
          <QqSettingsIllustrations v-if="active === 2" />
          <div class="actual-state"><el-tag :type="state.steps?.[active]?.ready ? 'success' : 'warning'">{{ state.steps?.[active]?.ready ? '实际配置检查通过' : '尚待完成检查' }}</el-tag><span>{{ state.steps?.[active]?.allowed === false ? '当前账号没有设置权限，请联系管理员' : state.steps?.[active]?.hint }}</span></div>
          <div class="lesson-actions"><el-button type="primary" :disabled="state.steps?.[active]?.allowed === false" @click="$router.push(state.steps?.[active]?.path || '/')">{{ current.action }}</el-button><el-button :loading="loading" @click="refresh">重新检查</el-button></div>
          <footer><el-button :disabled="active === 0" @click="selectStep(active - 1)">上一步</el-button><el-button v-if="active < 4" @click="selectStep(active + 1)">下一步</el-button><el-button v-else @click="tab = 'docs'">阅读操作文档</el-button></footer>
        </section>
      </div>
    </el-tab-pane>
    <el-tab-pane label="操作文档与常见问题" name="docs">
      <section class="surface help-library"><el-input v-model="query" aria-label="搜索操作文档" placeholder="搜索 Token、绑定、主动推送、仓库数量、发信…" clearable /><p>{{ filtered.length }} 篇操作说明</p><el-collapse><el-collapse-item v-for="article in filtered" :key="article.title" :name="article.title"><template #title><span class="article-category">{{ article.category }}</span>{{ article.title }}</template><p v-for="paragraph in article.paragraphs" :key="paragraph">{{ paragraph }}</p><QqSettingsIllustrations v-if="article.illustrated" /></el-collapse-item></el-collapse><el-empty v-if="!filtered.length" description="没有匹配的说明，换个关键词试试" /><div class="official-links"><span>官方参考：</span><a href="https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html" target="_blank" rel="noopener noreferrer">QQ 消息规则</a><a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">GitHub Token</a><a href="https://agent.qq.com/doc/cli-setup.md" target="_blank" rel="noopener noreferrer">Agent Mail 接入</a></div></section>
    </el-tab-pane>
  </el-tabs>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { setupLessons, helpArticles } from '../guideContent'
import { useAutoRefresh } from '../composables/useAutoRefresh'
import QqSettingsIllustrations from '../components/QqSettingsIllustrations.vue'
const tab = ref('setup'), active = ref(0), query = ref(''), loading = ref(false), state = ref<any>({})
let stepSelected = false
const current = computed(() => setupLessons[active.value]!)
const filtered = computed(() => helpArticles.filter(a => `${a.title} ${a.category} ${a.paragraphs.join(' ')}`.toLowerCase().includes(query.value.trim().toLowerCase())))
async function refresh() { loading.value = true; try { state.value = (await api.get('/onboarding')).data } finally { loading.value = false } }
async function selectStep(index: number) { stepSelected = true; active.value = Math.max(0, Math.min(4, index)); await api.put('/onboarding', { seen: true, step: active.value }) }
async function restart() { tab.value = 'setup'; await selectStep(0); await refresh() }
onMounted(async () => { await refresh(); if (!stepSelected) { active.value = state.value.progress?.step || 0; await api.put('/onboarding', { seen: true, step: active.value }) } })
useAutoRefresh(refresh, 15000)
</script>
<style scoped>
.guide-layout{display:grid;grid-template-columns:285px minmax(0,1fr);gap:22px;margin-top:16px;align-items:start}.guide-index{padding:22px 14px}.guide-index>p{color:#9eb2ce;margin:0 12px 18px}.guide-index button{display:flex;text-align:left;gap:12px;align-items:center;width:100%;padding:16px 12px;border:1px solid transparent;border-radius:8px;background:transparent;color:#b9c8dc;cursor:pointer}.guide-index button.selected{background:#1b2940;border-color:#5770a5;color:#fff}.guide-index button>span{display:grid;place-items:center;width:28px;height:28px;border:1px solid #405778;border-radius:50%;flex-shrink:0;color:#94deeb}.guide-index b{font-size:14px}.guide-index small{display:block;margin-top:6px;color:#8ea5c3}.guide-lesson{padding:30px 36px}.lesson-progress{font-size:13px;color:#8fb1db}h2{font-size:25px;margin:16px 0}.guide-lesson p,.guide-lesson li{color:#b3c3d9;font-size:14px;line-height:1.9;max-width:78ch}.guide-lesson ol{padding-left:22px;margin:26px 0}.guide-lesson li{padding-left:8px;margin-bottom:18px}.actual-state{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:24px 0 18px;font-size:13px;color:#a9bbd3}.lesson-actions{display:flex;gap:8px;flex-wrap:wrap}.guide-lesson footer{display:flex;justify-content:space-between;border-top:1px solid #2b3b53;margin-top:32px;padding-top:22px}.help-library{padding:28px;max-width:1100px}.help-library>p{color:#8da4c1;font-size:13px}.help-library .el-collapse p{color:#b7c7dc;line-height:1.9;max-width:80ch}.article-category{font-size:12px;color:#8fd9e5;margin-right:16px;min-width:56px}.official-links{display:flex;gap:20px;flex-wrap:wrap;margin-top:28px;font-size:13px;color:#9fb2ce}a{color:#92dce9}button:focus-visible{outline:2px solid #8edce8;outline-offset:2px}@media(max-width:950px){.guide-layout{grid-template-columns:1fr}.guide-index{display:flex;overflow:auto;padding:10px}.guide-index>p{display:none}.guide-index button{min-width:195px}.guide-lesson{padding:22px}.help-library{padding:18px}}
</style>
<style scoped>
.guide-lesson :deep(.el-alert){background:#16263c;border:1px solid #344c6a}.guide-lesson :deep(.el-alert__title){color:#b9d0eb;font-size:13px;line-height:1.8}
</style>
