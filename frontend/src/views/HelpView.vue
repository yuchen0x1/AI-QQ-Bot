<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">DOCUMENTATION CENTER</div>
      <h1>新手指引与操作文档</h1>
      <p>从第一次启动，到仓库动态送进群；按步骤完成自己的设置，也可以随时查阅常见问题。</p>
    </div>
    <div class="heading-actions">
      <el-button :loading="loading" @click="restart">
        <AppIcon name="refresh" :size="14" class="button-icon" />重新开始教学
      </el-button>
    </div>
  </div>

  <el-tabs v-model="tab" class="help-tabs">
    <el-tab-pane label="分步设置" name="setup">
      <div class="guide-layout">
        <nav class="surface guide-index" aria-label="设置步骤">
          <div class="index-heading">
            <span class="section-icon"><AppIcon name="branch" :size="17" /></span>
            <div>
              <b>设置路径</b>
              <p>状态来自真实配置检查</p>
            </div>
          </div>
          <div class="index-progress">
            <span class="progress-copy">{{ state.steps ? `${readyCount} / ${setupLessons.length}` : '同步中' }}</span>
            <el-tag :type="completionTone" size="small">{{ completionLabel }}</el-tag>
          </div>
          <div class="index-list">
            <button
              v-for="(lesson, index) in setupLessons"
              :key="lesson.title"
              type="button"
              class="lesson-index"
              :class="{
                selected: active === index,
                done: state.steps?.[index]?.ready,
                optional: state.steps?.[index]?.optional,
              }"
              :aria-current="active === index ? 'step' : undefined"
              @click="selectStep(index)"
            >
              <span class="index-badge">
                <AppIcon v-if="state.steps?.[index]?.ready" name="check" :size="12" />
                <template v-else>{{ index + 1 }}</template>
              </span>
              <span class="index-copy">
                <b>{{ lesson.title }}</b>
                <small>{{ stepStatus(index) }}</small>
              </span>
              <AppIcon class="index-end" :name="lessonIcons[index] || 'book'" :size="15" />
            </button>
          </div>
        </nav>

        <section class="surface guide-lesson" aria-live="polite" :aria-labelledby="`lesson-title-${active}`">
          <div class="lesson-top">
            <div class="lesson-progress">
              <span>STEP</span>
              <b>{{ active + 1 }}</b>
              <span>/ {{ setupLessons.length }}</span>
            </div>
            <span class="lesson-state" :class="lessonStateTone">
              <AppIcon :name="currentReady ? 'check-circle' : currentBlocked ? 'lock' : 'clock'" :size="13" />
              {{ currentReady ? '检查通过' : currentBlocked ? '无设置权限' : '等待完成' }}
            </span>
          </div>

          <h2 :id="`lesson-title-${active}`" class="lesson-title">{{ current.title }}</h2>
          <p class="lesson-intro">{{ current.intro }}</p>

          <div class="lesson-steps">
            <div class="steps-heading">
              <span>操作步骤</span>
              <b>{{ current.steps.length }} 步</b>
            </div>
            <ol>
              <li v-for="(text, index) in current.steps" :key="`${active}-${index}`">
                <span class="step-number">{{ index + 1 }}</span>
                <span>{{ text }}</span>
              </li>
            </ol>
          </div>

          <el-alert :title="current.note" type="info" :closable="false" show-icon class="lesson-note" />

          <QqSettingsIllustrations v-if="current.illustrations" />

          <div
            class="actual-state"
            :class="{ ready: currentReady, blocked: currentBlocked }"
            role="status"
          >
            <span class="actual-icon">
              <AppIcon
                :name="currentReady ? 'check-circle' : currentBlocked ? 'lock' : 'activity'"
                :size="17"
              />
            </span>
            <div class="actual-copy">
              <b>{{ currentReady ? '实际配置检查通过' : currentBlocked ? '当前账号没有设置权限' : '尚待完成检查' }}</b>
              <p>{{ actualStateCopy }}</p>
            </div>
            <code class="step-route" title="本步骤对应的后台页面">{{ state.steps?.[active]?.path || '/' }}</code>
          </div>

          <div class="lesson-actions">
            <el-button
              type="primary"
              :disabled="state.steps?.[active]?.allowed === false"
              @click="$router.push(state.steps?.[active]?.path || '/')"
            >
              {{ current.action }}<AppIcon name="arrow-right" :size="14" class="button-icon-after" />
            </el-button>
            <el-button :loading="loading" @click="refresh">
              <AppIcon name="refresh" :size="14" class="button-icon" />重新检查
            </el-button>
          </div>

          <footer class="lesson-footer">
            <el-button :disabled="active === 0" @click="selectStep(active - 1)">
              <AppIcon name="chevron-left" :size="14" class="button-icon" />上一步
            </el-button>
            <span class="footer-progress">{{ active + 1 }} / {{ setupLessons.length }}</span>
            <el-button v-if="active < setupLessons.length - 1" @click="selectStep(active + 1)">
              下一步<AppIcon name="chevron-right" :size="14" class="button-icon-after" />
            </el-button>
            <el-button v-else type="primary" @click="tab = 'docs'">
              阅读操作文档<AppIcon name="book" :size="14" class="button-icon-after" />
            </el-button>
          </footer>
        </section>
      </div>
    </el-tab-pane>

    <el-tab-pane label="操作文档与常见问题" name="docs">
      <div class="docs-layout">
        <aside class="surface docs-index" aria-label="文档搜索与分类">
          <div class="docs-index-heading">
            <span class="section-icon cyan"><AppIcon name="book" :size="17" /></span>
            <div>
              <b>文章库</b>
              <p>{{ helpArticles.length }} 篇说明，随时检索</p>
            </div>
          </div>
          <el-input
            v-model="query"
            aria-label="搜索操作文档"
            placeholder="搜索 Token、绑定、主动推送、仓库数量、发信…"
            clearable
            class="docs-search"
          >
            <template #prefix><AppIcon name="search" :size="14" /></template>
          </el-input>
          <p class="category-label">文档分类</p>
          <div class="category-list">
            <button
              type="button"
              class="category-button"
              :class="{ active: selectedCategory === '' }"
              :aria-pressed="selectedCategory === ''"
              @click="selectCategory('')"
            >
              <span>全部文档</span><small>{{ helpArticles.length }}</small>
            </button>
            <button
              v-for="category in categories"
              :key="category.name"
              type="button"
              class="category-button"
              :class="{ active: selectedCategory === category.name }"
              :aria-pressed="selectedCategory === category.name"
              @click="selectCategory(category.name)"
            >
              <span>{{ category.name }}</span><small>{{ category.count }}</small>
            </button>
          </div>
        </aside>

        <section class="surface help-library" aria-labelledby="docs-library-title">
          <div class="library-heading">
            <div>
              <div class="library-kicker">KNOWLEDGE BASE</div>
              <h2 id="docs-library-title">{{ selectedCategory || '全部操作文档' }}</h2>
              <p>{{ query ? `正在搜索“${query}”` : '按主题展开文章，查找配置、排错与运行规则。' }}</p>
            </div>
            <span class="result-count">{{ filtered.length }} 篇</span>
          </div>

          <el-collapse v-if="filtered.length" class="library-collapse">
            <el-collapse-item v-for="article in filtered" :key="article.title" :name="article.title">
              <template #title>
                <div class="article-title">
                  <span class="article-category">{{ article.category }}</span>
                  <span>{{ article.title }}</span>
                </div>
              </template>
              <div class="article-body">
                <p v-for="paragraph in article.paragraphs" :key="paragraph">{{ paragraph }}</p>
                <QqSettingsIllustrations v-if="article.illustrated" />
              </div>
            </el-collapse-item>
          </el-collapse>

          <div v-else class="docs-empty">
            <span class="empty-icon"><AppIcon name="search" :size="24" /></span>
            <b>没有匹配的说明</b>
            <p>换个关键词，或清除分类后查看全部文档。</p>
            <el-button @click="resetDocs">清除搜索与分类</el-button>
          </div>

          <div class="official-links">
            <div class="official-heading">
              <span class="official-icon"><AppIcon name="external" :size="17" /></span>
              <div>
                <b>官方参考</b>
                <p>涉及平台权限、Token 与邮件授权时，以官方页面为准。</p>
              </div>
            </div>
            <div class="link-list">
              <a
                href="https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html"
                target="_blank"
                rel="noopener noreferrer"
              >
                QQ 消息规则<AppIcon name="arrow-up-right" :size="13" />
              </a>
              <a
                href="https://github.com/settings/personal-access-tokens/new"
                target="_blank"
                rel="noopener noreferrer"
              >
                GitHub Token<AppIcon name="arrow-up-right" :size="13" />
              </a>
              <a
                href="https://agent.qq.com/doc/cli-setup.md"
                target="_blank"
                rel="noopener noreferrer"
              >
                Agent Mail 接入<AppIcon name="arrow-up-right" :size="13" />
              </a>
            </div>
          </div>
        </section>
      </div>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import { setupLessons, helpArticles } from '../guideContent'
import { useAutoRefresh } from '../composables/useAutoRefresh'
import QqSettingsIllustrations from '../components/QqSettingsIllustrations.vue'

const tab = ref('setup'), active = ref(0), query = ref(''), loading = ref(false), state = ref<any>({})
const selectedCategory = ref('')
let stepSelected = false

const lessonIcons = ['bot', 'sparkles', 'github', 'users', 'send', 'mail']
const current = computed(() => setupLessons[active.value]!)
const currentStep = computed(() => state.value.steps?.[active.value])
const currentReady = computed(() => Boolean(currentStep.value?.ready))
const currentBlocked = computed(() => currentStep.value?.allowed === false)
const readyCount = computed(() => state.value.steps?.filter((step: any) => step.ready).length ?? 0)
const completionTone = computed<'info' | 'success' | 'warning'>(() => {
  if (!state.value.steps) return 'info'
  return state.value.complete ? 'success' : 'warning'
})
const completionLabel = computed(() => {
  if (!state.value.steps) return '同步中'
  return state.value.complete ? '必选完成' : '待完成'
})
const lessonStateTone = computed(() => currentReady.value ? 'ready' : currentBlocked.value ? 'blocked' : 'pending')
const actualStateCopy = computed(() => {
  if (!state.value.steps) return '正在读取实际配置检查结果。'
  if (currentBlocked.value) return '当前账号缺少此步骤所需的设置权限，请联系管理员。'
  return currentStep.value?.hint || '完成上方步骤后，点击「重新检查」读取最新配置。'
})

const categories = computed(() => {
  const counts = new Map<string, number>()
  for (const article of helpArticles) {
    counts.set(article.category, (counts.get(article.category) || 0) + 1)
  }
  return Array.from(counts, ([name, count]) => ({ name, count }))
})
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return helpArticles.filter((article) => {
    if (selectedCategory.value && article.category !== selectedCategory.value) return false
    return `${article.title} ${article.category} ${article.paragraphs.join(' ')}`.toLowerCase().includes(keyword)
  })
})

function stepStatus(index: number) {
  const step = state.value.steps?.[index]
  if (!state.value.steps) return '正在检查'
  if (step?.ready) return '检查通过'
  if (step?.allowed === false) return '无设置权限'
  if (step?.optional) return '可稍后设置'
  return '等待设置'
}

function selectCategory(category: string) {
  selectedCategory.value = category
}

function resetDocs() {
  query.value = ''
  selectedCategory.value = ''
}

async function refresh() {
  loading.value = true
  try {
    state.value = (await api.get('/onboarding')).data
  } finally {
    loading.value = false
  }
}
async function selectStep(index: number) {
  stepSelected = true
  active.value = Math.max(0, Math.min(setupLessons.length - 1, index))
  await api.put('/onboarding', { seen: true, step: active.value })
}
async function restart() {
  tab.value = 'setup'
  await selectStep(0)
  await refresh()
}

onMounted(async () => {
  await refresh()
  if (!stepSelected) {
    active.value = state.value.progress?.step || 0
    await api.put('/onboarding', { seen: true, step: active.value })
  }
})
useAutoRefresh(refresh, 15000)
</script>

<style scoped>
.help-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}

.help-tabs :deep(.el-tabs__item) {
  padding-inline: 14px;
}

.guide-layout,
.docs-layout {
  display: grid;
  grid-template-columns: 265px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.docs-layout {
  grid-template-columns: 255px minmax(0, 1fr);
}

.guide-index,
.docs-index {
  position: sticky;
  top: calc(var(--topbar-height) + 18px);
  min-width: 0;
  padding: 15px;
}

.index-heading,
.docs-index-heading {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 13px;
}

.index-heading > div,
.docs-index-heading > div {
  min-width: 0;
}

.index-heading b,
.docs-index-heading b {
  display: block;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 620;
}

.index-heading p,
.docs-index-heading p {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 9px;
  line-height: 1.55;
}

.section-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.section-icon.cyan {
  border-color: var(--cyan-line);
  background: var(--cyan-soft);
  color: var(--cyan);
}

.index-progress {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 9px;
  padding: 8px 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
}

.progress-copy {
  color: var(--text-2);
  font: 600 10px/1.4 var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.index-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.lesson-index {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
  padding: 9px 8px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: var(--text-3);
  text-align: left;
  cursor: pointer;
  transition: color var(--duration-fast), background var(--duration-fast), border-color var(--duration-fast);
}

.lesson-index:hover {
  background: var(--surface-2);
  color: var(--text);
}

.lesson-index.selected {
  border-color: var(--brand-line);
  background: linear-gradient(90deg, var(--brand-soft), color-mix(in srgb, var(--brand-soft) 24%, transparent));
  color: var(--text);
}

.index-badge {
  display: grid;
  place-items: center;
  width: 27px;
  height: 27px;
  flex: none;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  color: var(--text-3);
  font: 650 9.5px/1 var(--font-mono);
}

.lesson-index.done .index-badge {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.index-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.index-copy b {
  overflow: hidden;
  color: inherit;
  font-size: 10.5px;
  font-weight: 560;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.index-copy small {
  color: var(--text-4);
  font-size: 8.5px;
}

.index-end {
  flex: none;
  color: var(--text-4);
}

.lesson-index.selected .index-end {
  color: var(--brand-strong);
}

.guide-lesson {
  min-width: 0;
  padding: 26px 30px;
}

.lesson-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.lesson-progress {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  color: var(--text-4);
  font: 600 9px/1.4 var(--font-mono);
  letter-spacing: 0.08em;
}

.lesson-progress b {
  color: var(--brand-strong);
  font-size: 15px;
  letter-spacing: 0;
}

.lesson-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 23px;
  padding: 2px 8px;
  border: 1px solid var(--warning-line);
  border-radius: 99px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 9px;
  font-weight: 600;
}

.lesson-state.ready {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}

.lesson-state.blocked {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}

.lesson-title {
  margin: 12px 0 7px;
  color: var(--text);
  font-size: clamp(22px, 2.2vw, 28px);
  font-weight: 680;
  letter-spacing: -0.035em;
  line-height: 1.2;
}

.lesson-intro {
  max-width: 74ch;
  margin: 0;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.8;
}

.lesson-steps {
  margin: 24px 0;
  padding: 17px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
}

.steps-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 13px;
}

.steps-heading span {
  color: var(--text);
  font-size: 10.5px;
  font-weight: 620;
}

.steps-heading b {
  color: var(--text-4);
  font: 600 9px/1.4 var(--font-mono);
}

.lesson-steps ol {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.lesson-steps li {
  display: grid;
  grid-template-columns: 27px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.8;
}

.step-number {
  display: grid;
  place-items: center;
  width: 27px;
  height: 27px;
  margin-top: 1px;
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font: 650 9.5px/1 var(--font-mono);
}

.lesson-note {
  margin-top: 18px;
}

.lesson-note :deep(.el-alert__title) {
  line-height: 1.75;
}

.actual-state {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-top: 20px;
  padding: 13px 14px;
  border: 1px solid var(--warning-line);
  border-radius: var(--radius-md);
  background: var(--warning-soft);
}

.actual-state.ready {
  border-color: var(--success-line);
  background: var(--success-soft);
}

.actual-state.blocked {
  border-color: var(--danger-line);
  background: var(--danger-soft);
}

.actual-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid currentColor;
  border-radius: 9px;
  background: color-mix(in srgb, var(--surface) 68%, transparent);
  color: var(--warning);
}

.actual-state.ready .actual-icon {
  color: var(--success);
}

.actual-state.blocked .actual-icon {
  color: var(--danger);
}

.actual-copy {
  flex: 1;
  min-width: 0;
}

.actual-copy b {
  display: block;
  color: var(--text);
  font-size: 10.5px;
  font-weight: 600;
}

.actual-copy p {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.65;
}

.step-route {
  flex: none;
  padding: 3px 7px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--code-bg);
  color: var(--text-3);
  font: 500 9px/1.5 var(--font-mono);
}

.lesson-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 18px;
}

.lesson-actions :deep(.el-button) {
  margin-left: 0;
}

.button-icon {
  margin-right: 5px;
}

.button-icon-after {
  margin-left: 5px;
}

.lesson-footer {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: 25px;
  padding-top: 17px;
  border-top: 1px solid var(--line);
}

.footer-progress {
  flex: 1;
  color: var(--text-4);
  font: 550 9px/1.4 var(--font-mono);
  text-align: center;
}

.docs-search {
  margin-bottom: 14px;
}

.category-label {
  margin: 0 0 6px;
  padding: 0 4px;
  color: var(--text-4);
  font-size: 8.5px;
  font-weight: 650;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.category-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 8px 9px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-3);
  font-size: 10px;
  text-align: left;
  cursor: pointer;
}

.category-button:hover {
  background: var(--surface-2);
  color: var(--text);
}

.category-button.active {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-weight: 600;
}

.category-button small {
  color: var(--text-4);
  font: 550 8.5px/1.4 var(--font-mono);
}

.help-library {
  min-width: 0;
  padding: 24px;
}

.library-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.library-kicker {
  margin-bottom: 5px;
  color: var(--brand-strong);
  font: 650 8.5px/1.4 var(--font-mono);
  letter-spacing: 0.14em;
}

.library-heading h2 {
  margin: 0 0 4px;
  color: var(--text);
  font-size: 19px;
  font-weight: 650;
  letter-spacing: -0.025em;
}

.library-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.6;
}

.result-count {
  flex: none;
  padding: 4px 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font: 600 9px/1.4 var(--font-mono);
}

.library-collapse {
  border-top: 1px solid var(--line);
}

.library-collapse :deep(.el-collapse-item__header) {
  min-height: 50px;
  height: auto;
  padding: 10px 2px;
  line-height: 1.55;
}

.library-collapse :deep(.el-collapse-item__arrow) {
  color: var(--text-4);
}

.library-collapse :deep(.el-collapse-item__content) {
  padding: 2px 0 20px;
}

.article-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding-right: 10px;
}

.article-category {
  flex: none;
  min-width: 50px;
  padding: 2px 6px;
  border: 1px solid var(--brand-line);
  border-radius: 5px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 8.5px;
  font-weight: 600;
  text-align: center;
}

.article-body {
  max-width: 82ch;
}

.article-body p {
  margin: 0 0 13px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.9;
}

.article-body p:last-child {
  margin-bottom: 0;
}

.official-links {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.official-heading {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 11px;
}

.official-icon {
  display: grid;
  place-items: center;
  width: 31px;
  height: 31px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text-3);
}

.official-heading b {
  color: var(--text);
  font-size: 10.5px;
  font-weight: 600;
}

.official-heading p {
  margin: 2px 0 0;
  color: var(--text-3);
  font-size: 9px;
  line-height: 1.55;
}

.link-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.link-list a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 9px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 9.5px;
  text-decoration: none;
}

.link-list a:hover {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.docs-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  padding: 42px 20px;
  text-align: center;
}

.docs-empty .empty-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface-2);
  color: var(--text-4);
}

.docs-empty b {
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 600;
}

.docs-empty p {
  margin: 0 0 5px;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.65;
}

.lesson-index:focus-visible,
.category-button:focus-visible,
.link-list a:focus-visible,
.guide-lesson :deep(.el-button:focus-visible),
.help-library :deep(.el-button:focus-visible) {
  outline: 2px solid var(--brand-strong);
  outline-offset: 2px;
}

@media (max-width: 960px) {
  .guide-layout,
  .docs-layout {
    grid-template-columns: 1fr;
  }

  .guide-index,
  .docs-index {
    position: static;
    padding: 12px;
  }

  .index-list {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .lesson-index {
    min-width: 205px;
  }

  .category-list {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .category-button {
    width: auto;
    min-width: max-content;
    flex: none;
  }
}

@media (max-width: 680px) {
  .guide-lesson,
  .help-library {
    padding: 18px;
  }

  .lesson-title {
    font-size: 22px;
  }

  .lesson-steps {
    padding: 14px;
  }

  .actual-state {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .step-route {
    margin-left: 45px;
  }

  .lesson-footer {
    flex-wrap: wrap;
  }

  .footer-progress {
    order: 3;
    flex-basis: 100%;
  }

  .library-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .article-title {
    align-items: flex-start;
    flex-direction: column;
    gap: 5px;
  }

  .article-category {
    min-width: 0;
  }

  .article-body p {
    font-size: 11.5px;
    line-height: 1.85;
  }
}

@media (max-width: 420px) {
  .lesson-index {
    min-width: 188px;
  }

  .guide-lesson,
  .help-library,
  .guide-index,
  .docs-index {
    padding: 14px;
  }

  .actual-copy {
    flex-basis: calc(100% - 45px);
  }

  .step-route {
    margin-left: 0;
  }
}
</style>
