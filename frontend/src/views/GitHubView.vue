<template>
  <div class="page-heading github-heading">
    <div>
      <div class="eyebrow">INTEGRATIONS / GITHUB</div>
      <h1>GitHub 仓库监控</h1>
      <p>管理仓库监控、版本发布与检查状态，并把真实项目动态发送到已配置的 QQ 通知群。</p>
    </div>
    <div class="heading-actions">
      <el-button :loading="checkingAll" :disabled="!repos.length || !reposLoaded" @click="checkAll">
        <AppIcon name="refresh" :size="14" />
        检查全部
      </el-button>
      <el-button @click="openImport">
        <AppIcon name="download" :size="14" />
        从 GitHub 导入
      </el-button>
      <el-button type="primary" @click="openAddRepo">
        <AppIcon name="plus" :size="14" />
        添加仓库
      </el-button>
    </div>
  </div>

  <div class="page-stack">
    <section class="identity-banner surface" v-loading="statusLoading" aria-labelledby="github-identity-title">
      <div class="identity-main">
        <span class="identity-mark" :class="{ connected: status?.connected }">
          <AppIcon name="github" :size="22" />
        </span>
        <div class="identity-copy">
          <div class="identity-title-row">
            <h2 id="github-identity-title">GitHub 身份</h2>
            <el-tag :type="identityTagType" size="small">{{ identityTagText }}</el-tag>
          </div>
          <strong v-if="status?.connected">@{{ status.account?.login }}</strong>
          <strong v-else-if="status?.configured">OAuth App 已配置，等待绑定账号</strong>
          <strong v-else-if="status">尚未配置 OAuth App</strong>
          <strong v-else-if="statusError">GitHub 授权状态暂时不可用</strong>
          <strong v-else>正在读取 GitHub 授权状态…</strong>
          <p v-if="status?.connected">
            <template v-if="scopeText !== '—'">授权范围 {{ scopeText }} · </template>
            <template v-if="status.account?.bound_at">绑定于 {{ formatDate(status.account.bound_at) }} · </template>
            <template v-if="status.account?.last_used_at">最近使用 {{ formatDate(status.account.last_used_at) }} · </template>
            Token 加密存储且不会回显
          </p>
          <p v-else-if="status?.configured">绑定后可列出该账号可访问的仓库（含私有仓库）并批量导入，无需逐个粘贴 Token。</p>
          <p v-else-if="status">{{ status.message || '可直接使用下方 Token 连接 GitHub，无需创建 OAuth App。' }}</p>
          <p v-if="statusError" class="identity-error">状态读取失败：{{ statusError }}</p>
        </div>
      </div>
      <div class="identity-actions">
        <el-button v-if="status?.can_configure" @click="openAppDialog">
          <AppIcon name="settings" :size="14" />
          {{ status?.configured ? 'OAuth 配置' : '配置 OAuth App' }}
        </el-button>
        <el-button v-if="status && !status.connected && !status.configured" @click="scrollToSetup">
          <AppIcon name="key" :size="14" />
          使用 Token 连接
        </el-button>
        <el-button v-if="status?.configured && !status?.connected" type="primary" :loading="binding" @click="startBind">
          <AppIcon name="github" :size="14" />
          绑定 GitHub 账号
        </el-button>
        <template v-if="status?.connected">
          <el-button type="primary" @click="openImport">
            <AppIcon name="download" :size="14" />
            从 GitHub 导入
          </el-button>
          <el-button @click="unbind">
            <AppIcon name="logout" :size="14" />
            解除绑定
          </el-button>
        </template>
      </div>
    </section>

    <div class="stat-grid github-stats" aria-label="GitHub 仓库摘要">
      <article class="stat-tile">
        <span class="stat-tile-icon brand"><AppIcon name="branch" :size="17" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">监控仓库</span>
          <span class="stat-tile-value">{{ monitoredCount }}</span>
          <span class="stat-tile-meta">{{ statRepoMeta }}</span>
        </div>
      </article>
      <article class="stat-tile">
        <span class="stat-tile-icon green"><AppIcon name="check-circle" :size="17" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">已启用监控</span>
          <span class="stat-tile-value">{{ enabledCount }}</span>
          <span class="stat-tile-meta">{{ statEnabledMeta }}</span>
        </div>
      </article>
      <article class="stat-tile">
        <span class="stat-tile-icon" :class="hasCheckErrors ? 'red' : 'cyan'"><AppIcon name="alert" :size="17" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">检查异常</span>
          <span class="stat-tile-value">{{ errorCount }}</span>
          <span class="stat-tile-meta">{{ statErrorMeta }}</span>
        </div>
      </article>
      <article class="stat-tile">
        <span class="stat-tile-icon orange"><AppIcon name="star" :size="17" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">最新 Release</span>
          <span class="stat-tile-value release-value" :title="latestRelease?.last_release_tag || ''">
            {{ latestRelease?.last_release_tag || '—' }}
          </span>
          <span class="stat-tile-meta" :title="latestRelease?.last_release_at ? formatDate(latestRelease.last_release_at) : ''">
            {{ statReleaseMeta }}
          </span>
        </div>
      </article>
    </div>

    <div id="github-notification-setup" class="notification-setup-anchor">
      <GithubNotifications
        :identity="status"
        @connected="handleConnected"
        @changed="loadRepos"
      />
    </div>

    <section class="repo-surface surface" aria-labelledby="monitored-repos-title">
      <div class="surface-head repo-head">
        <div>
          <h2 id="monitored-repos-title">监控仓库</h2>
          <p>{{ repoSummaryText }}</p>
        </div>
        <div class="repo-tools">
          <el-input
            v-model="repoKeyword"
            clearable
            placeholder="搜索仓库、Owner 或描述"
            class="repo-search"
            aria-label="搜索监控仓库"
          >
            <template #prefix><AppIcon name="search" :size="14" /></template>
          </el-input>
          <el-select v-model="repoFilter" class="repo-filter" aria-label="按监控状态筛选">
            <el-option label="全部状态" value="" />
            <el-option label="监控中" value="enabled" />
            <el-option label="已暂停" value="paused" />
            <el-option label="有检查异常" value="error" />
          </el-select>
          <el-button :loading="refreshing" @click="refreshAll">
            <AppIcon name="refresh" :size="14" />
            刷新
          </el-button>
        </div>
      </div>

      <el-alert v-if="repoLoadError" class="repo-error" type="error" show-icon :closable="false" title="仓库列表加载失败">
        <template #default>
          <span>{{ repoLoadError }}</span>
          <el-button link type="danger" @click="loadRepos">重试</el-button>
        </template>
      </el-alert>

      <div class="repo-table-wrap" v-loading="reposLoading">
        <table v-if="filteredRepos.length" class="repo-table">
          <thead>
            <tr>
              <th scope="col">仓库</th>
              <th scope="col">最新 Release</th>
              <th scope="col">监控状态</th>
              <th scope="col">上次检查 / 频率</th>
              <th scope="col">健康状态</th>
              <th scope="col" class="actions-head">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="repo in filteredRepos" :key="repo.id">
              <td class="repo-main" data-label="仓库">
                <div class="repo-identity">
                  <span class="repo-mark"><AppIcon name="github" :size="16" /></span>
                  <div class="repo-copy">
                    <a
                      class="repo-name"
                      :href="repo.html_url"
                      target="_blank"
                      rel="noopener noreferrer"
                      :title="repo.full_name"
                    >
                      {{ repo.full_name }}
                    </a>
                    <p class="repo-description" :title="repo.description || ''">{{ repo.description || '暂无项目描述' }}</p>
                    <div class="repo-meta">
                      <span v-if="repo.language"><AppIcon name="code" :size="12" />{{ repo.language }}</span>
                      <span><AppIcon name="star" :size="12" />{{ repo.stars ?? 0 }}</span>
                      <span v-if="repo.owner_username"><AppIcon name="user" :size="12" />{{ repo.owner_username }} 添加</span>
                    </div>
                  </div>
                </div>
              </td>
              <td data-label="最新 Release">
                <div v-if="repo.last_release_tag" class="release-cell">
                  <a
                    class="release-link"
                    :href="releaseUrl(repo)"
                    target="_blank"
                    rel="noopener noreferrer"
                    :title="`在 GitHub 查看 ${repo.full_name} 的 Release`"
                  >
                    <span>{{ repo.last_release_tag }}</span>
                    <AppIcon name="external" :size="12" />
                  </a>
                  <small>{{ repo.last_release_at ? formatRelative(repo.last_release_at) : '发布时间未知' }}</small>
                </div>
                <span v-else class="cell-empty">尚无版本记录</span>
              </td>
              <td data-label="监控状态">
                <div class="state-cell">
                  <el-tag :type="repo.monitor_enabled ? 'success' : 'info'" size="small" effect="plain">
                    {{ repo.monitor_enabled ? '监控中' : '已暂停' }}
                  </el-tag>
                  <span class="monitor-activity">
                    <AppIcon name="activity" :size="12" />
                    {{ repo.monitor_activity ? '全部动态' : '动态监控关闭' }}
                  </span>
                </div>
              </td>
              <td data-label="上次检查 / 频率">
                <div class="check-cell">
                  <span>{{ formatDate(repo.last_checked_at) }}</span>
                  <small><AppIcon name="timer" :size="12" />每 {{ formatInterval(repo.poll_interval_seconds) }}</small>
                  <small v-if="repo.last_webhook_at" class="webhook-time">
                    <AppIcon name="zap" :size="12" />Webhook {{ formatRelative(repo.last_webhook_at) }}
                  </small>
                </div>
              </td>
              <td data-label="健康状态">
                <div class="health-cell">
                  <el-tag :type="repoStatusTone(repo)" size="small" effect="plain">{{ repoStatusText(repo) }}</el-tag>
                  <small
                    v-if="repo.last_check_error"
                    class="check-error"
                    :title="repo.last_check_error"
                  >
                    {{ repo.last_check_error }}
                  </small>
                  <small v-else-if="repo.last_check_status === 'ok'" class="check-ok">最近一次检查通过</small>
                  <small v-else class="cell-empty">等待后台检查</small>
                </div>
              </td>
              <td class="repo-actions" data-label="操作">
                <div class="action-row">
                  <el-button link type="primary" :loading="checkingId === repo.id" @click="checkRepo(repo)">检查更新</el-button>
                  <el-button link @click="openReleases(repo)">Release</el-button>
                  <el-button link @click="openEditRepo(repo)">编辑</el-button>
                  <el-button link type="danger" @click="removeRepo(repo)">删除</el-button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-else-if="!reposLoading && !repoLoadError" class="repo-empty">
          <span class="empty-mark"><AppIcon :name="repos.length ? 'search' : 'github'" :size="26" /></span>
          <b>{{ repos.length ? '没有匹配的仓库' : '还没有监控仓库' }}</b>
          <p>
            {{ repos.length
              ? '调整搜索词或状态筛选，查看其他已接入仓库。'
              : '添加仓库地址，或绑定 GitHub 账号后批量导入。首次接入只建立基线，不会推送历史版本。' }}
          </p>
          <div class="empty-actions">
            <el-button v-if="repos.length" @click="clearFilters">清除筛选</el-button>
            <template v-else>
              <el-button type="primary" @click="openAddRepo">
                <AppIcon name="plus" :size="14" />
                添加仓库
              </el-button>
              <el-button @click="openImport">
                <AppIcon name="download" :size="14" />
                从 GitHub 导入
              </el-button>
            </template>
          </div>
        </div>
      </div>

      <div v-if="repos.length && !repoLoadError" class="repo-footer">
        <span>显示 {{ filteredRepos.length }} / {{ repos.length }} 个仓库 · 仓库状态每 10 秒自动刷新</span>
        <el-button link type="primary" :loading="refreshing" @click="refreshAll">刷新状态</el-button>
      </div>
    </section>
  </div>

  <el-dialog v-model="repoDialog" :title="repoDialogTitle" width="min(720px, calc(100vw - 28px))" destroy-on-close>
    <p class="dialog-lead">
      {{ repoEditing ? '调整监控频率、通知选项或更新访问凭据。' : '可粘贴完整 GitHub 地址，或分别填写 Owner 与仓库名。' }}
    </p>
    <el-form label-position="top" class="repo-form" @submit.prevent="saveRepo">
      <section class="form-section">
        <div class="form-section-head">
          <span class="form-section-icon"><AppIcon name="branch" :size="16" /></span>
          <div>
            <h3>仓库标识</h3>
            <p>{{ repoEditing ? '当前正在编辑的仓库' : 'URL 与 Owner / 仓库名二选一' }}</p>
          </div>
        </div>
        <template v-if="!repoEditing">
          <el-form-item label="GitHub 仓库地址">
            <el-input v-model="repoForm.url" clearable placeholder="https://github.com/owner/repo" />
          </el-form-item>
          <div class="form-grid split-grid">
            <el-form-item label="Owner / 用户名">
              <el-input v-model="repoForm.owner" clearable placeholder="例如 openai" />
            </el-form-item>
            <el-form-item label="仓库名">
              <el-input v-model="repoForm.name" clearable placeholder="例如 openai-python" />
            </el-form-item>
          </div>
          <p class="form-note">如果同时填写，服务端会优先使用仓库地址识别 Owner 与仓库名。</p>
        </template>
        <div v-else class="repo-readonly">
          <span class="repo-readonly-icon"><AppIcon name="github" :size="18" /></span>
          <div>
            <small>正在编辑</small>
            <b>{{ repoEditing?.full_name }}</b>
          </div>
          <a :href="repoEditing?.html_url || ''" target="_blank" rel="noopener noreferrer">
            打开仓库
            <AppIcon name="external" :size="12" />
          </a>
        </div>
      </section>

      <section class="form-section">
        <div class="form-section-head">
          <span class="form-section-icon"><AppIcon name="key" :size="16" /></span>
          <div>
            <h3>访问凭据</h3>
            <p>私有仓库或更高 API 限额所需，凭据只在服务端加密保存</p>
          </div>
        </div>
        <div class="form-grid split-grid">
          <el-form-item label="GitHub Token（可选）">
            <el-input
              v-model="repoForm.token"
              type="password"
              show-password
              autocomplete="off"
              :placeholder="repoEditing ? '留空保持不变' : '访问私有仓库或提高限额'"
            />
          </el-form-item>
          <el-form-item label="Webhook Secret（可选）">
            <el-input
              v-model="repoForm.webhook_secret"
              type="password"
              show-password
              autocomplete="off"
              :placeholder="repoEditing ? '留空保持不变' : '用于校验 GitHub Webhook'"
            />
          </el-form-item>
        </div>
        <p class="form-note">接口不会回显明文；如需更新，请直接填入新的值。</p>
      </section>

      <section class="form-section">
        <div class="form-section-head">
          <span class="form-section-icon"><AppIcon name="settings" :size="16" /></span>
          <div>
            <h3>监控选项</h3>
            <p>控制后台检查频率与版本通知范围</p>
          </div>
        </div>
        <el-form-item label="轮询间隔（秒）">
          <el-input-number
            v-model="repoForm.poll_interval_seconds"
            :min="60"
            :max="86400"
            :step="60"
            controls-position="right"
          />
        </el-form-item>
        <div class="switch-grid split-grid">
          <div class="switch-field">
            <div>
              <b>启用监控</b>
              <small>关闭后暂停自动检查与新版本通知</small>
            </div>
            <el-switch v-model="repoForm.monitor_enabled" aria-label="启用仓库监控" />
          </div>
          <div class="switch-field">
            <div>
              <b>接收预发布版本</b>
              <small>包含 GitHub 标记为 Pre-release 的版本</small>
            </div>
            <el-switch v-model="repoForm.notify_prerelease" aria-label="接收预发布版本" />
          </div>
        </div>
      </section>
    </el-form>
    <template #footer>
      <el-button @click="repoDialog = false">取消</el-button>
      <el-button type="primary" :loading="savingRepo" @click="saveRepo">保存仓库</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="importVisible" title="从 GitHub 导入仓库" width="min(860px, calc(100vw - 28px))" destroy-on-close>
    <div class="import-intro">
      <span class="form-section-icon"><AppIcon name="download" :size="16" /></span>
      <div>
        <b>选择当前 GitHub 授权可访问的仓库</b>
        <p>已监控的仓库不会重复导入；导入后按下方频率检查版本。</p>
      </div>
    </div>
    <div class="import-toolbar">
      <el-input v-model="keyword" clearable placeholder="按仓库名 / 描述过滤" class="import-search" aria-label="筛选可导入仓库">
        <template #prefix><AppIcon name="search" :size="14" /></template>
      </el-input>
      <el-button :loading="githubReposLoading" @click="loadGithubRepos">
        <AppIcon name="refresh" :size="14" />
        刷新
      </el-button>
      <span class="muted">可导入 {{ importable.length }} 个 · 已选 {{ selected.length }} 个</span>
    </div>
    <el-table
      v-loading="githubReposLoading"
      :data="filtered"
      height="360"
      row-key="full_name"
      empty-text="没有可导入的仓库（已监控的仓库不会重复出现）"
      @selection-change="onSelection"
    >
      <el-table-column type="selection" width="44" :selectable="rowSelectable" />
      <el-table-column label="仓库" min-width="250">
        <template #default="{ row }">
          <div class="repo-cell">
            <b>{{ row.full_name }}</b>
            <small>{{ row.description || '暂无描述' }}</small>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="语言" prop="language" width="100" />
      <el-table-column label="Stars" prop="stars" width="84" />
      <el-table-column label="状态" width="96">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="row.monitored ? 'info' : row.private ? 'warning' : 'success'">
            {{ row.monitored ? '已监控' : row.private ? '私有' : '公开' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
    <div class="import-foot">
      <span class="muted">轮询间隔</span>
      <el-input-number
        v-model="importInterval"
        :min="60"
        :max="86400"
        :step="60"
        controls-position="right"
        class="import-interval"
        aria-label="导入仓库的轮询间隔（秒）"
      />
      <span class="muted">秒</span>
      <el-switch v-model="importPrerelease" aria-label="导入时接收预发布版本" />
      <span class="muted">接收预发布版本</span>
      <span class="grow" />
      <span class="muted">历史版本会标记为已通知，不会刷屏</span>
    </div>
    <template #footer>
      <el-button @click="importVisible = false">取消</el-button>
      <el-button type="primary" :loading="importing" :disabled="!selected.length" @click="doImport">
        导入选中的 {{ selected.length }} 个仓库
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="appVisible" title="GitHub OAuth App 配置" width="min(680px, calc(100vw - 28px))">
    <el-alert type="info" :closable="false" show-icon>
      <template #title>在 GitHub 上创建 OAuth App 后填入凭据</template>
      <ol class="steps">
        <li v-for="step in appInfo?.steps || []" :key="step">{{ step }}</li>
      </ol>
    </el-alert>
    <div class="callback-row">
      <div>
        <span class="muted">Authorization callback URL</span>
        <code>{{ appInfo?.redirect_uri || status?.redirect_uri || '—' }}</code>
      </div>
      <el-button link type="primary" @click="copyCallback">
        <AppIcon name="copy" :size="13" />
        复制
      </el-button>
    </div>
    <el-form label-position="top" class="app-form">
      <el-form-item label="Client ID">
        <el-input
          v-model="appForm.client_id"
          :placeholder="appInfo?.client_id ? `当前：${appInfo.client_id}（重新填写可覆盖）` : 'Iv1.xxxxxxxxxxxx'"
        />
      </el-form-item>
      <el-form-item label="Client Secret">
        <el-input
          v-model="appForm.client_secret"
          type="password"
          show-password
          autocomplete="off"
          :placeholder="appInfo?.has_secret ? '留空保持现有密钥不变' : 'GitHub 只显示一次，请立即填入'"
        />
      </el-form-item>
      <el-form-item label="授权范围（Scopes）">
        <el-input v-model="appForm.scopes" placeholder="read:user repo" />
        <div class="muted hint">仅监控公开仓库可改为 public_repo；含私有仓库需保留 repo。</div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="appVisible = false">取消</el-button>
      <el-button type="primary" :loading="savingApp" @click="saveApp">保存配置</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import GithubNotifications from '../components/GithubNotifications.vue'
import { api } from '../api'
import { useAutoRefresh } from '../composables/useAutoRefresh'

interface GithubAccount {
  login: string
  name?: string | null
  scopes?: string | null
  bound_at?: string | null
  last_used_at?: string | null
}

interface GithubStatus {
  configured: boolean
  connected: boolean
  source?: string | null
  scopes?: string | null
  redirect_uri: string
  account?: GithubAccount | null
  can_configure?: boolean
  message?: string | null
}

interface GithubRepo {
  id: number
  owner: string
  name: string
  full_name: string
  html_url: string
  description?: string | null
  language?: string | null
  stars?: number
  owner_username?: string | null
  monitor_enabled: boolean
  remote_available?: boolean
  poll_interval_seconds: number
  notify_prerelease: boolean
  last_checked_at?: string | null
  last_check_status?: string | null
  last_check_error?: string | null
  last_release_tag?: string | null
  last_release_at?: string | null
  last_webhook_at?: string | null
  monitor_activity: boolean
}

interface GithubRepoItem {
  full_name: string
  description?: string | null
  language?: string | null
  stars?: number
  private?: boolean
  monitored?: boolean
}

interface RepoForm {
  url: string
  owner: string
  name: string
  token: string
  webhook_secret: string
  poll_interval_seconds: number
  monitor_enabled: boolean
  notify_prerelease: boolean
}

const route = useRoute()
const router = useRouter()
const statusLoading = ref(false)
const binding = ref(false)
const status = ref<GithubStatus | null>(null)
const statusError = ref('')

const repos = ref<GithubRepo[]>([])
const reposLoaded = ref(false)
const reposLoading = ref(false)
const repoLoadError = ref('')
const repoKeyword = ref('')
const repoFilter = ref('')
const refreshing = ref(false)
const checkingId = ref<number | null>(null)
const checkingAll = ref(false)

const repoDialog = ref(false)
const repoEditing = ref<GithubRepo | null>(null)
const savingRepo = ref(false)
const repoForm = reactive<RepoForm>({
  url: '',
  owner: '',
  name: '',
  token: '',
  webhook_secret: '',
  poll_interval_seconds: 900,
  monitor_enabled: true,
  notify_prerelease: false,
})

const importVisible = ref(false)
const githubReposLoading = ref(false)
const importing = ref(false)
const githubRepos = ref<GithubRepoItem[]>([])
const selected = ref<GithubRepoItem[]>([])
const keyword = ref('')
const importInterval = ref(900)
const importPrerelease = ref(false)

const appVisible = ref(false)
const appInfo = ref<any>(null)
const savingApp = ref(false)
const appForm = reactive({ client_id: '', client_secret: '', scopes: '' })

useAutoRefresh(loadRepos)

const scopeText = computed(() => String(status.value?.account?.scopes || status.value?.scopes || '—').replace(/,/g, ' '))
const identityTagType = computed<'success' | 'info' | 'warning' | 'danger'>(() => {
  if (status.value?.connected) return 'success'
  if (status.value?.configured) return 'info'
  if (!status.value && statusError.value) return 'danger'
  return 'warning'
})
const identityTagText = computed(() => {
  if (!status.value) return statusError.value ? '读取失败' : '读取中'
  if (status.value.connected) return '已连接'
  if (status.value.configured) return '未绑定'
  return 'Token 可用'
})

const monitoredCount = computed(() => reposLoaded.value ? repos.value.length : '—')
const enabledCount = computed(() => reposLoaded.value ? repos.value.filter((repo) => repo.monitor_enabled).length : '—')
const hasCheckErrors = computed(() => repos.value.some((repo) => isCheckError(repo)))
const errorCount = computed(() => reposLoaded.value ? repos.value.filter((repo) => isCheckError(repo)).length : '—')
const latestRelease = computed(() => repos.value
  .filter((repo) => repo.last_release_tag)
  .sort((left, right) => {
    const rightTime = right.last_release_at ? new Date(right.last_release_at).getTime() : 0
    const leftTime = left.last_release_at ? new Date(left.last_release_at).getTime() : 0
    return rightTime - leftTime
  })[0])

const statRepoMeta = computed(() => {
  if (!reposLoaded.value) return '等待仓库数据'
  if (!repos.value.length) return '尚未添加仓库'
  return status.value?.connected ? `@${status.value.account?.login} 已连接` : '使用手动凭据或待绑定身份'
})
const statEnabledMeta = computed(() => {
  if (!reposLoaded.value) return '等待仓库数据'
  const paused = repos.value.length - Number(enabledCount.value)
  return paused ? `${paused} 个仓库已暂停` : '全部仓库正在监控'
})
const statErrorMeta = computed(() => {
  if (!reposLoaded.value) return '等待检查结果'
  if (!errorCount.value) return '暂无检查异常'
  return '包含检查失败或不可访问仓库'
})
const statReleaseMeta = computed(() => {
  if (!reposLoaded.value) return '等待仓库数据'
  if (!latestRelease.value) return '尚无版本记录'
  return `${latestRelease.value.full_name} · ${latestRelease.value.last_release_at ? formatRelative(latestRelease.value.last_release_at) : '更新时间未知'}`
})

const filteredRepos = computed(() => {
  const text = repoKeyword.value.trim().toLowerCase()
  return repos.value.filter((repo) => {
    if (repoFilter.value === 'enabled' && !repo.monitor_enabled) return false
    if (repoFilter.value === 'paused' && repo.monitor_enabled) return false
    if (repoFilter.value === 'error' && !isCheckError(repo)) return false
    if (!text) return true
    return [repo.full_name, repo.description, repo.owner, repo.language, repo.owner_username]
      .some((value) => String(value || '').toLowerCase().includes(text))
  })
})

const repoSummaryText = computed(() => {
  if (!reposLoaded.value) return '正在读取仓库列表'
  if (!repos.value.length) return '添加仓库后，这里会显示检查状态与最新版本'
  const enabled = Number(enabledCount.value)
  return `共 ${repos.value.length} 个仓库 · ${enabled} 个监控中${hasCheckErrors.value ? ` · ${errorCount.value} 个异常` : ''}`
})
const repoDialogTitle = computed(() => repoEditing.value ? '编辑监控仓库' : '添加监控仓库')

const importable = computed(() => githubRepos.value.filter((item) => !item.monitored))
const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return githubRepos.value
  return githubRepos.value.filter(
    (item) => item.full_name.toLowerCase().includes(text) || (item.description || '').toLowerCase().includes(text),
  )
})

function isCheckError(repo: GithubRepo) {
  return repo.last_check_status === 'error' || repo.last_check_status === 'unavailable'
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN')
}

function formatRelative(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return '刚刚'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return formatDate(value)
}

function formatInterval(seconds?: number | null) {
  if (!seconds) return '—'
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`
  return `${seconds} 秒`
}

function repoStatusText(repo: GithubRepo) {
  return ({
    ok: '检查正常',
    error: '检查失败',
    unavailable: '仓库不可用',
  } as Record<string, string>)[repo.last_check_status || ''] || '待检查'
}

function repoStatusTone(repo: GithubRepo): 'danger' | 'success' | 'info' {
  if (isCheckError(repo)) return 'danger'
  if (repo.last_check_status === 'ok') return 'success'
  return 'info'
}

function releaseUrl(repo: GithubRepo) {
  const base = (repo.html_url || `https://github.com/${repo.full_name}`).replace(/\/+$/, '')
  return `${base}/releases`
}

function clearFilters() {
  repoKeyword.value = ''
  repoFilter.value = ''
}

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : fallback
}

async function loadStatus() {
  statusLoading.value = true
  statusError.value = ''
  try {
    const { data } = await api.get('/github/oauth/status')
    status.value = data
  } catch (error: any) {
    statusError.value = errorText(error, '请稍后重试')
  } finally {
    statusLoading.value = false
  }
}

async function loadRepos() {
  reposLoading.value = true
  repoLoadError.value = ''
  try {
    const { data } = await api.get('/github/repos')
    repos.value = Array.isArray(data) ? data : data?.items || []
    reposLoaded.value = true
  } catch (error: any) {
    repoLoadError.value = errorText(error, '请检查网络或访问权限后重试')
  } finally {
    reposLoading.value = false
  }
}

async function refreshAll() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.allSettled([loadStatus(), loadRepos()])
  } finally {
    refreshing.value = false
  }
}

async function handleConnected() {
  await loadStatus()
}

function scrollToSetup() {
  document.getElementById('github-notification-setup')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function startBind() {
  binding.value = true
  const next = route.fullPath || '/github'
  window.location.href = `/api/github/oauth/start?next=${encodeURIComponent(next)}`
}

async function unbind() {
  try {
    await ElMessageBox.confirm('解除绑定后，已监控的仓库仍会保留，但私有仓库将无法再通过你的授权读取。确定继续？', '解除 GitHub 绑定', {
      type: 'warning',
    })
  } catch {
    return
  }
  await api.post('/github/oauth/disconnect')
  ElMessage.success('已解除 GitHub 绑定')
  await loadStatus()
}

function openAddRepo() {
  repoEditing.value = null
  Object.assign(repoForm, {
    url: '',
    owner: '',
    name: '',
    token: '',
    webhook_secret: '',
    poll_interval_seconds: 900,
    monitor_enabled: true,
    notify_prerelease: false,
  })
  repoDialog.value = true
}

function openEditRepo(repo: GithubRepo) {
  repoEditing.value = repo
  Object.assign(repoForm, {
    url: '',
    owner: repo.owner,
    name: repo.name,
    token: '',
    webhook_secret: '',
    poll_interval_seconds: repo.poll_interval_seconds,
    monitor_enabled: repo.monitor_enabled,
    notify_prerelease: repo.notify_prerelease,
  })
  repoDialog.value = true
}

async function saveRepo() {
  if (!repoEditing.value && !repoForm.url.trim() && (!repoForm.owner.trim() || !repoForm.name.trim())) {
    ElMessage.warning('请填写仓库地址，或同时填写 Owner 与仓库名')
    return
  }
  if (!repoForm.poll_interval_seconds || repoForm.poll_interval_seconds < 60) {
    ElMessage.warning('轮询间隔不能少于 60 秒')
    return
  }
  savingRepo.value = true
  try {
    if (repoEditing.value) {
      await api.put(`/github/repos/${repoEditing.value.id}`, {
        token: repoForm.token.trim(),
        webhook_secret: repoForm.webhook_secret.trim(),
        poll_interval_seconds: repoForm.poll_interval_seconds,
        monitor_enabled: repoForm.monitor_enabled,
        notify_prerelease: repoForm.notify_prerelease,
      })
    } else {
      await api.post('/github/repos', {
        url: repoForm.url.trim(),
        owner: repoForm.owner.trim(),
        name: repoForm.name.trim(),
        token: repoForm.token.trim(),
        webhook_secret: repoForm.webhook_secret.trim(),
        poll_interval_seconds: repoForm.poll_interval_seconds,
        monitor_enabled: repoForm.monitor_enabled,
        notify_prerelease: repoForm.notify_prerelease,
      })
    }
    ElMessage.success('仓库已保存')
    repoDialog.value = false
    await loadRepos()
  } finally {
    savingRepo.value = false
  }
}

async function removeRepo(repo: GithubRepo) {
  try {
    await ElMessageBox.confirm(`确定删除仓库「${repo.full_name}」吗？此操作不可撤销。`, '确认删除', { type: 'warning' })
  } catch {
    return
  }
  await api.delete(`/github/repos/${repo.id}`)
  ElMessage.success('已删除')
  await loadRepos()
}

async function checkRepo(repo: GithubRepo) {
  checkingId.value = repo.id
  try {
    const { data } = await api.post(`/github/repos/${repo.id}/check`)
    ElMessage.success(data.message || '检查完成')
    await loadRepos()
  } finally {
    checkingId.value = null
  }
}

async function checkAll() {
  checkingAll.value = true
  try {
    const { data } = await api.post('/github/repos/check-all')
    ElMessage.success(`检查完成，共处理 ${Array.isArray(data) ? data.length : 0} 个仓库`)
    await loadRepos()
  } finally {
    checkingAll.value = false
  }
}

function openReleases(repo: GithubRepo) {
  window.open(releaseUrl(repo), '_blank', 'noopener')
}

async function openImport() {
  if (!status.value?.connected) {
    ElMessage.warning(status.value?.configured ? '请先绑定 GitHub 账号' : '请先让管理员配置 GitHub OAuth App，或使用下方 Token 连接')
    if (status.value?.can_configure && !status.value?.configured) await openAppDialog()
    return
  }
  importVisible.value = true
  await loadGithubRepos()
}

async function loadGithubRepos() {
  githubReposLoading.value = true
  try {
    const all: GithubRepoItem[] = []
    for (let page = 1; page <= 50; page++) {
      const { data } = await api.get('/github/oauth/repos', { params: { page } })
      all.push(...(data.items || []))
      if (!data.has_more) break
      if (page === 50) ElMessage.warning('已达到 5000 个仓库的读取上限')
    }
    githubRepos.value = all
  } finally {
    githubReposLoading.value = false
  }
}

function rowSelectable(row: GithubRepoItem) {
  return !row.monitored
}

function onSelection(rows: GithubRepoItem[]) {
  selected.value = rows
}

async function doImport() {
  if (!selected.value.length) return
  importing.value = true
  try {
    const { data } = await api.post('/github/oauth/import', {
      full_names: selected.value.map((item) => item.full_name),
      poll_interval_seconds: importInterval.value,
      notify_prerelease: importPrerelease.value,
    })
    const imported = data.imported?.length || 0
    const skipped = data.skipped?.length || 0
    const failed = data.failed || []
    if (imported) ElMessage.success(`已导入 ${imported} 个仓库，历史版本已标记为已通知`)
    else if (skipped) ElMessage.info('所选仓库都已在监控列表中')
    if (failed.length) ElMessage.warning(`${failed.length} 个仓库导入失败：${failed[0].full_name}（${failed[0].error}）`)
    importVisible.value = false
    await Promise.all([loadRepos(), loadGithubRepos()])
  } finally {
    importing.value = false
  }
}

async function openAppDialog() {
  const { data } = await api.get('/github/oauth/app')
  appInfo.value = data
  appForm.client_id = ''
  appForm.client_secret = ''
  appForm.scopes = data.scopes || 'read:user repo'
  appVisible.value = true
}

async function saveApp() {
  if (!appForm.client_id.trim() && !appInfo.value?.configured) {
    ElMessage.warning('请填写 Client ID')
    return
  }
  savingApp.value = true
  try {
    await api.put('/github/oauth/app', {
      client_id: appForm.client_id.trim(),
      client_secret: appForm.client_secret.trim() || undefined,
      scopes: appForm.scopes.trim() || undefined,
    })
    ElMessage.success('OAuth App 配置已保存，现在可以绑定 GitHub 账号了')
    appVisible.value = false
    await loadStatus()
  } finally {
    savingApp.value = false
  }
}

async function copyCallback() {
  const value = appInfo.value?.redirect_uri || status.value?.redirect_uri || ''
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success('回调地址已复制')
  } catch {
    ElMessage.warning(`请手动复制：${value}`)
  }
}

onMounted(async () => {
  const result = route.query.github
  if (result === 'connected') {
    ElMessage.success(`GitHub 账号 @${route.query.login || ''} 绑定成功`)
    router.replace({ path: route.path })
  } else if (result === 'error') {
    ElMessage.error(String(route.query.reason || 'GitHub 授权失败，请重试'))
    router.replace({ path: route.path })
  }
  await Promise.allSettled([loadStatus(), loadRepos()])
})
</script>

<style scoped>
.identity-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 20px;
  min-width: 0;
}

.identity-main {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
}

.identity-mark {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-2);
  color: var(--text-3);
}

.identity-mark.connected {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.identity-copy {
  min-width: 0;
}

.identity-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.identity-title-row h2 {
  margin: 0;
  color: var(--text-3);
  font: 650 9.5px/1.4 var(--font-mono);
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.identity-copy > strong {
  display: block;
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 14px;
  font-weight: 620;
}

.identity-copy p {
  max-width: 820px;
  margin: 5px 0 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.identity-copy p.identity-error {
  color: var(--danger);
}

.identity-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex: none;
}

.identity-actions .el-button + .el-button {
  margin-left: 0;
}

:deep(.el-button .app-icon) {
  margin-right: 4px;
}

.github-stats {
  margin-bottom: 0;
}

.release-value {
  max-width: 240px;
  overflow: hidden;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.repo-surface {
  padding: 0;
  overflow: hidden;
  scroll-margin-top: calc(var(--topbar-height) + 20px);
}

.notification-setup-anchor {
  scroll-margin-top: calc(var(--topbar-height) + 20px);
}

.repo-head {
  margin-bottom: 0;
  padding: 18px 18px 14px;
  flex-wrap: wrap;
}

.repo-head h2 {
  margin: 0 0 4px;
  color: var(--text);
  font-size: 14px;
  font-weight: 640;
}

.repo-head p {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.55;
}

.repo-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.repo-search {
  width: 250px;
}

.repo-filter {
  width: 138px;
}

.repo-error {
  margin: 0 18px 14px;
}

.repo-table-wrap {
  min-height: 160px;
  overflow-x: auto;
}

.repo-table {
  width: 100%;
  min-width: 1040px;
  border-collapse: collapse;
  table-layout: fixed;
}

.repo-table th {
  padding: 10px 14px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 72%, transparent);
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-align: left;
  white-space: nowrap;
}

.repo-table th:nth-child(1) {
  width: 29%;
}

.repo-table th:nth-child(2) {
  width: 15%;
}

.repo-table th:nth-child(3) {
  width: 14%;
}

.repo-table th:nth-child(4) {
  width: 16%;
}

.repo-table th:nth-child(5) {
  width: 15%;
}

.repo-table th:nth-child(6) {
  width: 11%;
}

.repo-table td {
  padding: 14px;
  border-bottom: 1px solid var(--line-soft);
  vertical-align: top;
}

.repo-table tbody tr {
  transition: background var(--duration-fast) var(--ease);
}

.repo-table tbody tr:hover {
  background: color-mix(in srgb, var(--surface-hover) 36%, transparent);
}

.repo-table tbody tr:last-child td {
  border-bottom: 0;
}

.actions-head {
  text-align: right !important;
}

.repo-identity {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.repo-mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text-3);
}

.repo-copy {
  min-width: 0;
  flex: 1;
}

.repo-name {
  display: block;
  max-width: 100%;
  overflow: hidden;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.repo-name:hover {
  color: var(--brand-strong);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.repo-description {
  display: -webkit-box;
  margin: 4px 0 7px;
  overflow: hidden;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.55;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.repo-meta {
  display: flex;
  align-items: center;
  gap: 5px 10px;
  flex-wrap: wrap;
}

.repo-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-4);
  font-size: 9.5px;
}

.release-cell,
.check-cell,
.health-cell,
.state-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
  min-width: 0;
}

.release-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  color: var(--brand-strong);
  font: 600 10.5px/1.4 var(--font-mono);
  overflow-wrap: anywhere;
}

.release-link span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.release-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.release-cell small,
.check-cell small,
.health-cell small {
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.5;
}

.check-cell > span {
  color: var(--text-2);
  font-size: 10.5px;
  line-height: 1.5;
}

.check-cell small,
.webhook-time {
  display: inline-flex;
  align-items: flex-start;
  gap: 4px;
}

.monitor-activity {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-4);
  font-size: 9.5px;
}

.check-error {
  display: -webkit-box;
  overflow: hidden;
  color: var(--danger) !important;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.check-ok {
  color: var(--success) !important;
}

.cell-empty {
  color: var(--text-4);
  font-size: 9.5px;
}

.action-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  flex-wrap: wrap;
}

.action-row .el-button {
  margin-left: 0;
  font-size: 10.5px;
}

.repo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 230px;
  padding: 28px;
  text-align: center;
}

.empty-mark {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: var(--surface-2);
  color: var(--text-4);
}

.repo-empty b {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.repo-empty p {
  max-width: 520px;
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.empty-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.empty-actions .el-button + .el-button {
  margin-left: 0;
}

.repo-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 18px;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 42%, transparent);
  color: var(--text-4);
  font-size: 9.5px;
}

.dialog-lead {
  margin: 0 0 16px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.65;
}

.repo-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-section {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-2);
}

.form-section-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 14px;
}

.form-section-head > div {
  min-width: 0;
}

.form-section-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.form-section h3 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 620;
}

.form-section-head p {
  margin: 0;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.55;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

.form-section :deep(.el-form-item) {
  margin-bottom: 12px;
}

.form-section :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.form-section :deep(.el-input-number) {
  width: 180px;
}

.form-note {
  margin: 2px 0 0;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.6;
}

.repo-readonly {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
}

.repo-readonly-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text-3);
}

.repo-readonly > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.repo-readonly small {
  color: var(--text-4);
  font-size: 9px;
}

.repo-readonly b {
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
}

.repo-readonly a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  color: var(--brand-strong);
  font-size: 10px;
}

.switch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.switch-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
}

.switch-field > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.switch-field b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 600;
}

.switch-field small {
  color: var(--text-4);
  font-size: 9px;
  line-height: 1.45;
}

.import-intro {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 14px;
}

.import-intro > div {
  min-width: 0;
}

.import-intro b {
  display: block;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 600;
}

.import-intro p {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.55;
}

.import-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.import-search {
  width: 270px;
}

.import-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.import-interval {
  width: 132px;
}

.import-foot .grow {
  flex: 1;
}

.muted {
  color: var(--text-3);
  font-size: 10px;
}

.repo-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.repo-cell b {
  overflow-wrap: anywhere;
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
}

.repo-cell small {
  overflow: hidden;
  color: var(--text-4);
  font-size: 9.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.callback-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 14px 0;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-2);
}

.callback-row > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.callback-row code {
  overflow-wrap: anywhere;
  color: var(--text-2);
  font: 10.5px/1.5 var(--font-mono);
}

.callback-row .el-button {
  flex: none;
}

.steps {
  margin: 7px 0 0;
  padding-left: 18px;
  color: var(--text-2);
  font-size: 10px;
  line-height: 1.8;
}

.app-form {
  margin-top: 4px;
}

.hint {
  margin-top: 4px;
  line-height: 1.5;
}

@media (max-width: 1180px) {
  .identity-banner {
    align-items: flex-start;
    flex-direction: column;
  }

  .identity-actions {
    justify-content: flex-start;
  }

  .repo-table {
    min-width: 980px;
  }
}

@media (max-width: 900px) {
  .repo-tools {
    width: 100%;
    justify-content: flex-start;
  }

  .repo-search {
    width: min(100%, 280px);
  }

  .repo-table-wrap {
    overflow: visible;
  }

  .repo-table {
    min-width: 0;
    table-layout: fixed;
  }

  .repo-table thead {
    display: none;
  }

  .repo-table,
  .repo-table tbody,
  .repo-table tr,
  .repo-table td {
    display: block;
    width: 100%;
  }

  .repo-table tr {
    padding: 14px 16px;
    border-top: 1px solid var(--line);
  }

  .repo-table td {
    padding: 5px 0;
    border: 0;
  }

  .repo-table td:not(.repo-main):not(.repo-actions) {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr);
    gap: 12px;
    align-items: start;
  }

  .repo-table td:not(.repo-main):not(.repo-actions)::before {
    content: attr(data-label);
    padding-top: 2px;
    color: var(--text-4);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.03em;
  }

  .repo-main {
    padding-bottom: 10px !important;
  }

  .repo-actions {
    padding-top: 10px !important;
  }

  .action-row {
    justify-content: flex-start;
  }

  .repo-name {
    white-space: normal;
    overflow-wrap: anywhere;
  }

}

@media (max-width: 840px) {
  .form-grid,
  .switch-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .repo-filter {
    width: 154px;
  }

  .repo-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .import-search {
    width: 100%;
  }

  .import-foot .grow {
    display: none;
  }

  .callback-row {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 480px) {
  .identity-banner {
    padding: 16px;
  }

  .identity-main {
    gap: 10px;
  }

  .identity-actions,
  .identity-actions .el-button {
    width: 100%;
  }

  .identity-actions .el-button {
    margin-left: 0;
  }

  .repo-tools .el-button {
    width: 100%;
  }

  .repo-search,
  .repo-filter {
    width: 100%;
  }

  .repo-table td:not(.repo-main):not(.repo-actions) {
    display: block;
  }

  .repo-table td:not(.repo-main):not(.repo-actions)::before {
    display: block;
    margin-bottom: 3px;
  }

  .repo-empty {
    padding: 22px 16px;
  }

  .empty-actions,
  .empty-actions .el-button {
    width: 100%;
  }

  .form-section {
    padding: 13px;
  }

  .repo-readonly {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .repo-readonly a {
    margin-left: 42px;
  }
}
</style>
