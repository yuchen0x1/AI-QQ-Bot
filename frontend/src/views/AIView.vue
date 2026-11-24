<template>
  <div class="ai-page">
    <div class="page-heading ai-heading">
      <div>
        <div class="eyebrow">AI MODEL OPERATIONS</div>
        <h1>AI 模型运营中心</h1>
        <p>统一管理供应商、模型路由、密钥与调用质量，并通过真实接口进行连通性测试和对话调试。</p>
      </div>
      <div class="heading-actions">
        <el-button :loading="loading" @click="load()">
          <AppIcon name="refresh" :size="14" class="btn-icon" />刷新配置
        </el-button>
        <el-button @click="openPlayground">
          <AppIcon name="sparkles" :size="14" class="btn-icon" />对话沙盒
        </el-button>
        <el-button type="primary" @click="openProviderCreate">
          <AppIcon name="plus" :size="14" class="btn-icon" />添加供应商
        </el-button>
      </div>
    </div>

    <el-alert v-if="loadError" class="ai-error" type="error" show-icon :closable="false" title="AI 配置加载失败">
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="danger" @click="load()">重新加载</el-button>
      </template>
    </el-alert>

    <div class="stat-grid ai-stats">
      <div class="stat-tile">
        <span class="stat-tile-icon brand"><AppIcon name="layers" :size="18" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">已配置模型</span>
          <span class="stat-tile-value">{{ formatNumber(models.length) }}<small>个</small></span>
          <span class="stat-tile-meta">当前模型列表 · {{ formatNumber(enabledModels.length) }} 个启用</span>
        </div>
      </div>
      <div class="stat-tile">
        <span class="stat-tile-icon green"><AppIcon name="check-circle" :size="18" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">启用 / 健康模型</span>
          <span class="stat-tile-value">{{ formatNumber(enabledModels.length) }}<small>启用</small></span>
          <span class="stat-tile-meta">{{ formatNumber(healthyModels.length) }} 个连接正常 · {{ formatNumber(testedModels.length) }} 个已测试</span>
        </div>
      </div>
      <div class="stat-tile route-tile">
        <span class="stat-tile-icon cyan"><AppIcon name="branch" :size="18" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">默认供应商 / 模型</span>
          <span class="stat-tile-value route-value" :title="defaultRouteTitle">
            {{ defaultProviderName }}
            <small :title="defaultModelName">{{ defaultModelName }}</small>
          </span>
          <span class="stat-tile-meta">{{ defaultRouteMeta }}</span>
        </div>
      </div>
      <div class="stat-tile">
        <span class="stat-tile-icon orange"><AppIcon name="activity" :size="18" /></span>
        <div class="stat-tile-copy">
          <span class="stat-tile-label">模型累计调用 / 错误</span>
          <span class="stat-tile-value">{{ formatNumber(modelCalls) }}<small>次</small></span>
          <span class="stat-tile-meta">当前模型列表 · {{ formatNumber(modelErrors) }} 次错误</span>
        </div>
      </div>
    </div>
    <p class="scope-note">
      <AppIcon name="info" :size="13" />
      <span>统计范围仅限当前已加载的模型配置行；“健康”表示最近一次连通测试成功，不代表实时探测。调用与错误数取模型累计字段。</span>
    </p>

    <div class="ai-sections">
      <section class="surface providers-panel">
        <div class="surface-head">
          <div>
            <h3>模型供应商</h3>
            <p>兼容 OpenAI 协议及常见服务商；密钥只以脱敏形式展示。</p>
          </div>
          <span class="section-count">{{ providers.length }} 个供应商 · {{ providers.filter(p => p.enabled).length }} 个启用</span>
        </div>
        <div v-if="!providers.length && !loading" class="empty-inline provider-empty">
          <AppIcon name="server" :size="28" />
          <b>还没有配置 AI 供应商</b>
          <span>先添加供应商并保存 API Key，再获取或手动添加可用模型。</span>
          <el-button type="primary" size="small" @click="openProviderCreate">
            <AppIcon name="plus" :size="13" class="btn-icon" />添加第一个供应商
          </el-button>
        </div>
        <div v-else class="provider-grid" v-loading="loading">
          <article
            v-for="p in providers"
            :key="p.id"
            class="provider-card"
            :class="{ 'is-off': !p.enabled }"
          >
            <div class="provider-head">
              <span class="provider-mark"><AppIcon name="server" :size="17" /></span>
              <div class="provider-title">
                <b :title="p.name">{{ p.name }}</b>
                <small>{{ providerKindLabel(p.kind) }}</small>
              </div>
              <span class="provider-enabled" :class="p.enabled ? 'is-on' : 'is-off'">
                <AppIcon :name="p.enabled ? 'check-circle' : 'pause'" :size="11" />
                {{ p.enabled ? '已启用' : '已停用' }}
              </span>
            </div>

            <div class="provider-meta">
              <span :title="p.base_url"><AppIcon name="globe" :size="12" /><span>{{ p.base_url }}</span></span>
              <span><AppIcon name="key" :size="12" /><span class="mono">{{ providerKeyLabel(p) }}</span></span>
            </div>

            <div
              class="provider-feedback"
              :class="providerFeedback(p.id)?.tone || (!p.has_api_key && p.kind !== 'ollama' ? 'warn' : 'idle')"
              :title="providerFeedbackText(p)"
              role="status"
              aria-live="polite"
            >
              <AppIcon :name="providerFeedbackIcon(p)" :size="12" />
              <span>{{ providerFeedbackText(p) }}</span>
              <small v-if="providerFeedback(p.id)?.latency_ms !== undefined">{{ providerFeedback(p.id)?.latency_ms }} ms</small>
            </div>

            <p v-if="p.remark" class="provider-remark" :title="p.remark">{{ p.remark }}</p>

            <div class="provider-foot">
              <span class="model-count">
                <AppIcon name="layers" :size="12" />{{ formatNumber(p.model_count) }} 个模型
              </span>
              <div class="provider-actions">
                <el-button link type="primary" :loading="syncing === p.id" @click="syncProvider(p)">
                  <AppIcon name="download" :size="12" class="btn-icon" />获取模型
                </el-button>
                <el-button link type="success" :loading="providerTestingId === p.id" @click="testProvider(p)">
                  <AppIcon name="zap" :size="12" class="btn-icon" />测试连接
                </el-button>
                <el-button link @click="openEditProvider(p)">
                  <AppIcon name="edit" :size="12" class="btn-icon" />编辑
                </el-button>
                <el-button link type="danger" @click="removeProvider(p)">
                  <AppIcon name="trash" :size="12" class="btn-icon" />删除
                </el-button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="surface models-panel">
        <div class="surface-head">
          <div>
            <h3>模型路由与健康状态</h3>
            <p>按优先级选择模型；默认模型优先生效，备用模型参与故障降级。</p>
          </div>
          <div class="surface-actions">
            <span class="section-count">{{ enabledModels.length }} 个启用</span>
            <el-button type="primary" plain @click="openModel">
              <AppIcon name="plus" :size="13" class="btn-icon" />添加模型
            </el-button>
          </div>
        </div>
        <div class="table-scroll">
          <el-table
            :data="models"
            v-loading="loading"
            row-key="id"
            stripe
            class="models-table"
            style="width: 100%"
          >
            <el-table-column label="模型" min-width="220">
              <template #default="{ row }">
                <div class="model-cell">
                  <div class="model-title">
                    <b :title="modelLabel(row)">{{ modelLabel(row) }}</b>
                    <el-tag v-if="row.is_default" size="small" type="success" effect="light">默认</el-tag>
                    <el-tag v-else-if="row.is_fallback" size="small" type="warning" effect="light">备用</el-tag>
                  </div>
                  <code :title="row.model_name">{{ row.model_name }}</code>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="供应商" min-width="120">
              <template #default="{ row }">
                <div class="provider-cell">
                  <span :title="row.provider_name">{{ row.provider_name || '—' }}</span>
                  <small v-if="row.provider_kind">{{ providerKindLabel(row.provider_kind) }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="86">
              <template #default="{ row }">
                <span class="status-badge" :class="row.enabled ? 'ok' : 'muted'">
                  <AppIcon :name="row.enabled ? 'check-circle' : 'pause'" :size="11" />
                  {{ row.enabled ? '启用' : '停用' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="连接状态" width="126">
              <template #default="{ row }">
                <el-tooltip
                  v-if="row.last_check_status === 'error' && row.last_check_error"
                  :content="row.last_check_error"
                  placement="top"
                >
                  <span class="status-badge bad">
                    <AppIcon name="alert" :size="11" />异常
                  </span>
                </el-tooltip>
                <span v-else class="status-badge" :class="modelHealthTone(row)">
                  <AppIcon :name="modelHealthIcon(row)" :size="11" />
                  {{ modelHealthLabel(row) }}
                  <small v-if="row.last_latency_ms !== null && row.last_latency_ms !== undefined">{{ row.last_latency_ms }}ms</small>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="调用" width="76" align="right">
              <template #default="{ row }"><span class="numeric">{{ formatNumber(row.total_calls) }}</span></template>
            </el-table-column>
            <el-table-column label="错误" width="76" align="right">
              <template #default="{ row }"><span class="numeric" :class="{ 'danger-text': Number(row.total_errors) > 0 }">{{ formatNumber(row.total_errors) }}</span></template>
            </el-table-column>
            <el-table-column label="Token" width="96" align="right">
              <template #default="{ row }"><span class="numeric">{{ formatCompact(row.total_tokens) }}</span></template>
            </el-table-column>
            <el-table-column label="优先级" width="76" align="right">
              <template #default="{ row }"><span class="numeric">{{ row.priority }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="242" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button link type="primary" @click="testModel(row)">对话</el-button>
                  <el-button link type="success" :loading="modelTestingId === row.id" @click="checkModel(row)">测试</el-button>
                  <el-button link type="warning" :disabled="row.is_default" @click="setDefault(row)">设默认</el-button>
                  <el-button link type="danger" @click="removeModel(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
            <template #empty>
              <div class="table-empty">
                <AppIcon name="layers" :size="26" />
                <b>还没有配置模型</b>
                <span>添加模型后即可设置默认路由、测试连接或直接开始对话。</span>
                <el-button size="small" type="primary" plain @click="openModel">添加模型</el-button>
              </div>
            </template>
          </el-table>
        </div>
      </section>

      <section class="surface usage-panel">
        <div class="surface-head usage-head">
          <div>
            <h3>最近调用记录</h3>
            <p>AI 服务接口返回的最近 7 天请求状态、Token 与耗时；按页加载。</p>
          </div>
          <div class="surface-actions usage-summary">
            <span class="summary-chip">本页调用 <b>{{ formatNumber(usage.length) }}</b></span>
            <span class="summary-chip">本页 Token <b>{{ formatCompact(pageUsageTokens) }}</b></span>
            <span class="summary-chip" :class="{ 'is-danger': pageUsageErrors > 0 }">本页错误 <b>{{ formatNumber(pageUsageErrors) }}</b></span>
            <el-button text :loading="usageLoading" @click="loadUsage">
              <AppIcon name="refresh" :size="13" class="btn-icon" />刷新
            </el-button>
          </div>
        </div>
        <el-alert v-if="usageError" class="usage-error" type="error" show-icon :closable="false" :title="usageError" />
        <div class="table-scroll">
          <el-table :data="usage" v-loading="usageLoading" stripe class="usage-table" style="width: 100%">
            <el-table-column label="时间" width="166">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="模型" min-width="160">
              <template #default="{ row }">
                <span class="usage-model" :title="row.model_name">{{ row.model_name || '未记录模型' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="94">
              <template #default="{ row }">
                <span class="status-badge" :class="usageStatusMeta(row.status).tone">
                  <AppIcon :name="usageStatusMeta(row.status).icon" :size="11" />
                  {{ usageStatusMeta(row.status).label }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="Token" width="146">
              <template #default="{ row }">
                <div class="token-cell">
                  <b class="numeric">{{ formatNumber(row.prompt_tokens + row.completion_tokens) }}</b>
                  <small>P {{ formatNumber(row.prompt_tokens) }} · C {{ formatNumber(row.completion_tokens) }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="92">
              <template #default="{ row }"><span class="numeric">{{ formatLatency(row.latency_ms) }}</span></template>
            </el-table-column>
            <el-table-column label="错误详情" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.error" class="error-detail" :title="row.error">{{ row.error }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <template #empty>
              <div class="table-empty">
                <AppIcon name="activity" :size="26" />
                <b>暂无调用记录</b>
                <span>使用对话沙盒或模型对话测试发起真实请求后，结果会出现在这里。</span>
                <el-button size="small" :loading="usageLoading" @click="loadUsage">刷新记录</el-button>
              </div>
            </template>
          </el-table>
        </div>
        <div class="pagination-wrap usage-pagination">
          <span>共 {{ formatNumber(usageTotal) }} 条 · 第 {{ usagePage }} 页</span>
          <el-pagination
            v-model:current-page="usagePage"
            :page-size="10"
            :total="usageTotal"
            layout="prev, pager, next"
            @current-change="loadUsage"
          />
        </div>
      </section>
    </div>

    <el-dialog
      v-model="providerDialog"
      :title="editingProvider ? '编辑供应商' : '添加供应商'"
      width="min(600px, calc(100vw - 28px))"
      destroy-on-close
    >
      <el-form ref="providerRef" :model="providerForm" :rules="providerRules" label-position="top" class="dialog-form">
        <div class="form-cols">
          <el-form-item label="供应商名称" prop="name">
            <el-input v-model="providerForm.name" placeholder="例如：DeepSeek 主账号" />
          </el-form-item>
          <el-form-item label="供应商类型" prop="kind">
            <el-select v-model="providerForm.kind" style="width: 100%">
              <el-option v-for="option in providerKinds" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="API Base URL" prop="base_url">
          <el-input v-model="providerForm.base_url" placeholder="https://api.example.com/v1" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="providerForm.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="editingProvider ? '留空则沿用已保存的密钥' : '粘贴 API Key'"
          />
          <p v-if="editingProvider && providerRow" class="form-hint">
            <AppIcon name="lock" :size="12" />
            当前密钥：{{ providerKeyLabel(providerRow) }}。保存空值不会覆盖原密钥。
          </p>
          <p v-else class="form-hint">
            <AppIcon name="shield" :size="12" />密钥仅加密存储，接口只返回脱敏值。
          </p>
        </el-form-item>
        <div class="form-cols">
          <el-form-item label="启用状态">
            <el-switch v-model="providerForm.enabled" active-text="启用" inactive-text="停用" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="providerForm.remark" placeholder="可选，例如用途或额度说明" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="providerDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProvider">保存供应商</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="modelDialog" title="添加模型" width="min(600px, calc(100vw - 28px))" destroy-on-close>
      <el-form ref="modelRef" :model="modelForm" :rules="modelRules" label-position="top" class="dialog-form">
        <el-form-item label="所属供应商" prop="provider_id">
          <el-select v-model="modelForm.provider_id" style="width: 100%" placeholder="选择一个已启用的供应商">
            <el-option v-for="p in providers.filter(x => x.enabled)" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <div class="form-cols">
          <el-form-item label="Model ID" prop="model_name">
            <el-input v-model="modelForm.model_name" placeholder="例如：deepseek-chat / gpt-4o-mini" />
          </el-form-item>
          <el-form-item label="显示名称">
            <el-input v-model="modelForm.display_name" placeholder="可选，便于后台识别" />
          </el-form-item>
        </div>
        <div class="form-cols">
          <el-form-item label="温度">
            <el-input-number v-model="modelForm.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
          </el-form-item>
          <el-form-item label="最大输出 Token">
            <el-input-number v-model="modelForm.max_tokens" :min="16" :max="200000" :step="256" style="width: 100%" />
          </el-form-item>
        </div>
        <div class="form-cols">
          <el-form-item label="优先级">
            <el-input-number v-model="modelForm.priority" :min="1" :max="999" style="width: 100%" />
          </el-form-item>
          <el-form-item label="超时（秒）">
            <el-input-number v-model="modelForm.timeout_seconds" :min="5" :max="600" style="width: 100%" />
          </el-form-item>
        </div>
        <el-form-item label="路由与状态">
          <div class="checkbox-row">
            <el-checkbox v-model="modelForm.is_default">设为默认模型</el-checkbox>
            <el-checkbox v-model="modelForm.is_fallback">作为备用模型</el-checkbox>
            <el-checkbox v-model="modelForm.enabled">启用</el-checkbox>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveModel">保存模型</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="chatDialog" title="模型对话测试" width="min(720px, calc(100vw - 28px))" destroy-on-close>
      <div class="chat-dialog-shell">
        <div class="chat-context">
          <span class="context-mark"><AppIcon name="sparkles" :size="15" /></span>
          <div>
            <b>{{ chatModel?.display_name || chatModel?.model_name || '未选择模型' }}</b>
            <small>{{ chatModel?.provider_name || '供应商' }} · 真实 API 对话</small>
          </div>
          <span class="status-badge info"><AppIcon name="wifi" :size="11" />按次调用</span>
        </div>
        <div ref="chatBox" class="chat-messages" aria-live="polite">
          <div v-if="!chatMessages.length && !chatLoading" class="chat-empty">
            <AppIcon name="chat" :size="24" />
            <b>开始测试模型回复</b>
            <span>发送的内容会直接请求当前模型，不会写入群聊数据。</span>
          </div>
          <div v-for="(message, index) in chatMessages" :key="index" class="chat-line" :class="message.role">
            <span class="chat-avatar">
              <AppIcon :name="message.role === 'user' ? 'user' : 'sparkles'" :size="13" />
            </span>
            <div class="chat-body">
              <span class="chat-role">{{ message.role === 'user' ? '你' : 'AI 助手' }}</span>
              <div class="chat-bubble">{{ message.content }}</div>
            </div>
          </div>
          <div v-if="chatLoading" class="chat-line assistant">
            <span class="chat-avatar"><AppIcon name="sparkles" :size="13" /></span>
            <div class="chat-body">
              <span class="chat-role">AI 助手</span>
              <div class="chat-bubble typing"><AppIcon name="loader" :size="13" />正在生成回复…</div>
            </div>
          </div>
        </div>
        <div class="chat-entry">
          <el-input
            v-model="chatInput"
            type="textarea"
            :rows="2"
            resize="none"
            aria-label="输入测试消息"
            placeholder="输入消息开始测试，Ctrl + Enter 发送"
            @keydown.ctrl.enter="sendChat"
          />
          <el-button type="primary" :loading="chatLoading" :disabled="!chatInput.trim()" @click="sendChat">
            <AppIcon name="send" :size="14" class="btn-icon" />发送
          </el-button>
        </div>
        <p class="entry-hint">此测试直接调用模型接口，可能产生真实 Token 消耗。</p>
      </div>
    </el-dialog>

    <el-dialog
      v-model="playgroundVisible"
      title="AI 对话调试沙盒"
      width="min(1080px, calc(100vw - 28px))"
      destroy-on-close
    >
      <div class="playground-container">
        <aside class="playground-sidebar">
          <div class="panel-heading">
            <span class="panel-heading-icon"><AppIcon name="settings" :size="15" /></span>
            <div><b>参数调优</b><small>每轮请求使用当前参数</small></div>
          </div>
          <el-form label-position="top" size="small" class="playground-form">
            <el-form-item label="调试模型">
              <el-select v-model="pgModelId" style="width: 100%" placeholder="选择模型">
                <el-option
                  v-for="m in enabledModels"
                  :key="m.id"
                  :label="`${modelLabel(m)}${m.is_default ? '（默认）' : ''}`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="System Prompt">
              <el-input
                v-model="pgSystemPrompt"
                type="textarea"
                :rows="4"
                resize="none"
                placeholder="例如：你是开源项目的群聊助手，回答口语化并带幽默感…"
              />
            </el-form-item>
            <div class="preset-block">
              <span>快捷人设</span>
              <div class="preset-row">
                <button type="button" class="preset-chip" @click="pgSystemPrompt = '你是 QQ 群里友好、活泼的助手，回答简洁明了，适当使用可爱颜文字。'">活泼助手</button>
                <button type="button" class="preset-chip" @click="pgSystemPrompt = '你是严谨的软件架构师与资深全栈工程师，回答精准、注重代码规范与架构安全性。'">资深架构师</button>
                <button type="button" class="preset-chip" @click="pgSystemPrompt = '你是毒舌群管，说话犀利风趣但逻辑清晰，喜欢调侃群员但乐于助人。'">幽默毒舌</button>
              </div>
            </div>
            <el-form-item label="温度（Temperature）" class="slider-item">
              <el-slider v-model="pgTemperature" :min="0" :max="2" :step="0.1" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="最大 Tokens">
              <el-input-number v-model="pgMaxTokens" :min="64" :max="32000" :step="256" style="width: 100%" />
            </el-form-item>
          </el-form>
          <div class="playground-foot">
            <span>已保留 {{ pgMessages.length }} 条上下文</span>
            <el-button size="small" :disabled="!pgMessages.length && !pgInput" @click="clearPlayground">
              <AppIcon name="trash" :size="12" class="btn-icon" />清空
            </el-button>
          </div>
        </aside>

        <div class="playground-chat">
          <div class="playground-topbar">
            <div class="playground-model">
              <span class="context-mark"><AppIcon name="sparkles" :size="14" /></span>
              <div>
                <b>{{ selectedPlaygroundModel }}</b>
                <small>直接调用模型接口，消息仅用于本次沙盒上下文</small>
              </div>
            </div>
            <span class="status-badge info"><AppIcon name="terminal" :size="11" />Playground</span>
          </div>
          <div ref="pgChatBox" class="chat-messages pg-messages" aria-live="polite">
            <div v-if="!pgMessages.length && !pgLoading" class="chat-empty">
              <AppIcon name="sparkles" :size="26" />
              <b>准备开始调试</b>
              <span>选择模型、填写 System Prompt 后发送第一条消息。所有回复均来自真实接口。</span>
            </div>
            <div v-for="(message, index) in pgMessages" :key="index" class="chat-line" :class="message.role">
              <span class="chat-avatar">
                <AppIcon :name="message.role === 'user' ? 'user' : 'sparkles'" :size="13" />
              </span>
              <div class="chat-body">
                <span class="chat-role">{{ message.role === 'user' ? '你' : 'AI 助手' }}</span>
                <div class="chat-bubble">
                  {{ message.content }}
                  <div v-if="message.meta" class="bubble-meta">
                    <span><AppIcon name="clock" :size="10" />{{ formatLatency(message.meta.latency_ms) }}</span>
                    <span>Prompt {{ formatOptionalNumber(message.meta.usage?.prompt_tokens) }}</span>
                    <span>Comp {{ formatOptionalNumber(message.meta.usage?.completion_tokens) }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="pgLoading" class="chat-line assistant">
              <span class="chat-avatar"><AppIcon name="sparkles" :size="13" /></span>
              <div class="chat-body">
                <span class="chat-role">AI 助手</span>
                <div class="chat-bubble typing"><AppIcon name="loader" :size="13" />正在生成回复并追踪 Token 消耗…</div>
              </div>
            </div>
          </div>
          <div class="chat-entry playground-entry">
            <el-input
              v-model="pgInput"
              type="textarea"
              :rows="3"
              resize="none"
              aria-label="输入沙盒消息"
              placeholder="按 Ctrl + Enter 快速发送消息…"
              @keydown.ctrl.enter="sendPlayground"
            />
            <el-button type="primary" :loading="pgLoading" :disabled="!pgInput.trim()" @click="sendPlayground">
              <AppIcon name="send" :size="14" class="btn-icon" />发送
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '../components/AppIcon.vue'
import { AI_TIMEOUT, api } from '../api'

interface ProviderRow {
  id: number
  name: string
  kind: string
  base_url: string
  enabled: boolean
  remark?: string | null
  api_key_masked?: string | null
  has_api_key?: boolean
  model_count?: number
}

interface ModelRow {
  id: number
  provider_id: number
  model_name: string
  display_name?: string | null
  provider_name?: string | null
  provider_kind?: string | null
  enabled: boolean
  is_default: boolean
  is_fallback: boolean
  priority: number
  total_calls?: number
  total_errors?: number
  total_tokens?: number
  last_latency_ms?: number | null
  last_check_status?: string | null
  last_check_error?: string | null
}

interface UsageRow {
  id: number
  model_name?: string | null
  status: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  error?: string | null
  created_at: string
}

interface TestFeedback {
  tone: 'ok' | 'bad' | 'testing'
  message: string
  latency_ms?: number
}

const providers = ref<ProviderRow[]>([])
const models = ref<ModelRow[]>([])
const usage = ref<UsageRow[]>([])
const loading = ref(false)
const usageLoading = ref(false)
const saving = ref(false)
const providerDialog = ref(false)
const modelDialog = ref(false)
const editingProvider = ref(false)
const providerRef = ref<any>()
const modelRef = ref<any>()
const providerRow = ref<ProviderRow | null>(null)
const chatDialog = ref(false)
const chatModel = ref<ModelRow | null>(null)
const chatMessages = ref<any[]>([])
const chatInput = ref('')
const chatLoading = ref(false)
const chatBox = ref<HTMLElement>()
const usagePage = ref(1)
const usageTotal = ref(0)
const syncing = ref<number | null>(null)
const providerTestingId = ref<number | null>(null)
const modelTestingId = ref<number | null>(null)
const loadError = ref('')
const usageError = ref('')
const providerFeedbackMap = reactive<Record<number, TestFeedback>>({})

const playgroundVisible = ref(false)
const pgModelId = ref<number | null>(null)
const pgSystemPrompt = ref('')
const pgTemperature = ref(0.7)
const pgMaxTokens = ref(2048)
const pgMessages = ref<any[]>([])
const pgInput = ref('')
const pgLoading = ref(false)
const pgChatBox = ref<HTMLElement>()

const providerKinds = [
  { value: 'openai', label: 'OpenAI 兼容' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'qwen', label: '通义千问 Qwen' },
  { value: 'moonshot', label: 'Moonshot' },
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama 本地模型' },
  { value: 'custom', label: '自定义' },
]

const providerForm = reactive<any>({
  name: '',
  kind: 'openai',
  base_url: '',
  api_key: '',
  enabled: true,
  remark: '',
})

const modelForm = reactive<any>({
  provider_id: null,
  model_name: '',
  display_name: '',
  temperature: 0.7,
  max_tokens: 2048,
  timeout_seconds: 60,
  retries: 1,
  priority: 100,
  is_default: false,
  is_fallback: false,
  enabled: true,
})

const providerRules = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请填写 API Base URL', trigger: 'blur' }],
}

const modelRules = {
  provider_id: [{ required: true, message: '请选择供应商', trigger: 'change' }],
  model_name: [{ required: true, message: '请填写 Model ID', trigger: 'blur' }],
}

const enabledModels = computed(() => models.value.filter(model => model.enabled !== false))
const testedModels = computed(() => models.value.filter(model => Boolean(model.last_check_status)))
const healthyModels = computed(() => models.value.filter(model => model.last_check_status === 'ok'))
const defaultModel = computed(() => models.value.find(model => model.is_default) || null)
const defaultProvider = computed(() => {
  if (!defaultModel.value) return null
  return providers.value.find(provider => provider.id === defaultModel.value?.provider_id) || null
})
const defaultProviderName = computed(() => defaultProvider.value?.name || defaultModel.value?.provider_name || '—')
const defaultModelName = computed(() => defaultModel.value ? modelLabel(defaultModel.value) : '未设置默认模型')
const defaultRouteTitle = computed(() => `${defaultProviderName.value} / ${defaultModelName.value}`)
const defaultRouteMeta = computed(() => {
  if (!defaultModel.value) return '未设置默认模型，将按优先级选择启用模型'
  if (defaultProvider.value && !defaultProvider.value.enabled) return '默认模型所属供应商当前已停用'
  return '当前显式默认路由'
})
const modelCalls = computed(() => models.value.reduce((total, model) => total + Number(model.total_calls || 0), 0))
const modelErrors = computed(() => models.value.reduce((total, model) => total + Number(model.total_errors || 0), 0))
const pageUsageTokens = computed(() => usage.value.reduce((total, item) => total + Number(item.prompt_tokens || 0) + Number(item.completion_tokens || 0), 0))
const pageUsageErrors = computed(() => usage.value.filter(item => item.status !== 'success').length)
const selectedPlaygroundModel = computed(() => {
  const selected = models.value.find(model => model.id === pgModelId.value)
  return selected ? modelLabel(selected) : '未选择模型'
})

function errorText(error: any) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : '请求失败，请检查后端连接后重试'
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [providerResponse, modelResponse] = await Promise.all([api.get('/ai/providers'), api.get('/ai/models')])
    providers.value = providerResponse.data
    models.value = modelResponse.data
  } catch (error) {
    loadError.value = errorText(error)
  } finally {
    loading.value = false
  }
  await loadUsage()
}

async function loadUsage() {
  usageLoading.value = true
  usageError.value = ''
  try {
    const { data } = await api.get('/ai/usage', { params: { page: usagePage.value, page_size: 10 } })
    usage.value = data.items || []
    usageTotal.value = data.total || 0
  } catch (error) {
    usageError.value = errorText(error)
  } finally {
    usageLoading.value = false
  }
}

function providerKindLabel(kind: string) {
  return providerKinds.find(item => item.value === kind)?.label || kind || '未知类型'
}

function providerKeyLabel(provider: ProviderRow) {
  if (!provider.has_api_key) return '未配置 API Key'
  return provider.api_key_masked || '已保存（已脱敏）'
}

function providerFeedback(id: number) {
  return providerFeedbackMap[id]
}

function providerFeedbackText(provider: ProviderRow) {
  const feedback = providerFeedback(provider.id)
  if (feedback) return feedback.message
  if (!provider.has_api_key && provider.kind !== 'ollama') return '未配置 API Key，测试前请先编辑供应商'
  return '尚未测试连接'
}

function providerFeedbackIcon(provider: ProviderRow) {
  const feedback = providerFeedback(provider.id)
  if (feedback?.tone === 'ok') return 'check-circle'
  if (feedback?.tone === 'bad') return 'alert'
  if (feedback?.tone === 'testing') return 'loader'
  if (!provider.has_api_key && provider.kind !== 'ollama') return 'info'
  return 'clock'
}

function modelLabel(model: ModelRow) {
  return model.display_name || model.model_name
}

function modelHealthLabel(model: ModelRow) {
  if (model.last_check_status === 'ok') return '正常'
  if (model.last_check_status === 'error') return '异常'
  return '未测试'
}

function modelHealthIcon(model: ModelRow) {
  if (model.last_check_status === 'ok') return 'check-circle'
  if (model.last_check_status === 'error') return 'alert'
  return 'clock'
}

function modelHealthTone(model: ModelRow) {
  if (model.last_check_status === 'ok') return 'ok'
  if (model.last_check_status === 'error') return 'bad'
  return 'muted'
}

function usageStatusMeta(status: string) {
  if (status === 'success') return { label: '成功', icon: 'check-circle', tone: 'ok' }
  if (status === 'error') return { label: '失败', icon: 'alert', tone: 'bad' }
  return { label: status || '未知', icon: 'info', tone: 'muted' }
}

function formatNumber(value: number | string | null | undefined) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatOptionalNumber(value: number | string | null | undefined) {
  return value === null || value === undefined ? '—' : Number(value).toLocaleString('zh-CN')
}

function formatCompact(value: number | string | null | undefined) {
  const number = Number(value || 0)
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`
  if (number >= 10_000) return `${(number / 1000).toFixed(1)}K`
  return number.toLocaleString('zh-CN')
}

function formatLatency(value: number | null | undefined) {
  return value === null || value === undefined ? '—' : `${Number(value).toLocaleString('zh-CN')} ms`
}

function openProviderCreate() {
  newProvider()
  providerDialog.value = true
}

function newProvider() {
  editingProvider.value = false
  providerRow.value = null
  Object.assign(providerForm, {
    name: '',
    kind: 'openai',
    base_url: '',
    api_key: '',
    enabled: true,
    remark: '',
  })
}

function openEditProvider(provider: ProviderRow) {
  editingProvider.value = true
  providerRow.value = provider
  Object.assign(providerForm, {
    name: provider.name,
    kind: provider.kind,
    base_url: provider.base_url,
    api_key: '',
    enabled: provider.enabled,
    remark: provider.remark || '',
  })
  providerDialog.value = true
}

async function saveProvider() {
  await providerRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    saving.value = true
    try {
      const payload = { ...providerForm }
      if (editingProvider.value && !payload.api_key) delete (payload as any).api_key
      const saved: ProviderRow = editingProvider.value
        ? (await api.put(`/ai/providers/${providerRow.value?.id}`, payload)).data
        : (await api.post('/ai/providers', payload)).data
      ElMessage.success('供应商已保存')
      providerDialog.value = false
      await load()
      syncing.value = saved.id
      try {
        const { data: result } = await api.post(
          `/ai/providers/${saved.id}/sync-models`,
          null,
          { timeout: AI_TIMEOUT },
        )
        if (result.ok && result.created) ElMessage.success(`已自动导入 ${result.created} 个模型，可继续调整优先级`)
        else if (result.ok && !result.fetched) ElMessage.warning('供应商未返回模型列表，可稍后点「获取模型」重试')
        else if (!result.ok) ElMessage.warning(result.message || '获取模型列表失败，可稍后点「获取模型」重试')
      } catch {
        ElMessage.warning('获取模型列表失败，可稍后点「获取模型」重试')
      } finally {
        syncing.value = null
        await load()
      }
    } finally {
      saving.value = false
    }
  })
}

async function testProvider(provider: ProviderRow) {
  providerTestingId.value = provider.id
  providerFeedbackMap[provider.id] = { tone: 'testing', message: '正在测试连接…' }
  try {
    const { data } = await api.post(`/ai/providers/${provider.id}/test`, null, { timeout: AI_TIMEOUT })
    if (data.ok) {
      providerFeedbackMap[provider.id] = {
        tone: 'ok',
        message: data.message || '连接成功',
        latency_ms: data.latency_ms,
      }
      ElMessage.success(data.message || '连接成功')
    } else {
      providerFeedbackMap[provider.id] = {
        tone: 'bad',
        message: data.message || '连接失败',
        latency_ms: data.latency_ms,
      }
      ElMessage.error(data.message || '连接失败')
    }
  } catch (error) {
    providerFeedbackMap[provider.id] = { tone: 'bad', message: errorText(error) }
  } finally {
    providerTestingId.value = null
  }
}

async function syncProvider(provider: ProviderRow) {
  syncing.value = provider.id
  try {
    const { data } = await api.post(`/ai/providers/${provider.id}/sync-models`, null, { timeout: AI_TIMEOUT })
    if (data.ok) ElMessage.success(data.message)
    else ElMessage.error(data.message)
  } catch {
    ElMessage.error('获取模型列表失败')
  } finally {
    syncing.value = null
    await load()
  }
}

async function removeProvider(provider: ProviderRow) {
  try {
    const content = provider.model_count
      ? `删除供应商「${provider.name}」后，其下 ${provider.model_count} 个模型也会一并删除。此操作不可撤销。`
      : `删除供应商「${provider.name}」？此操作不可撤销。`
    await ElMessageBox.confirm(content, '确认删除供应商', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await api.delete(`/ai/providers/${provider.id}`)
    ElMessage.success('已删除供应商')
    await load()
  } catch {
    /* 用户取消或接口错误由全局拦截器提示 */
  }
}

function openModel() {
  Object.assign(modelForm, {
    provider_id: providers.value.find(provider => provider.enabled)?.id || null,
    model_name: '',
    display_name: '',
    temperature: 0.7,
    max_tokens: 2048,
    timeout_seconds: 60,
    retries: 1,
    priority: 100,
    is_default: false,
    is_fallback: false,
    enabled: true,
  })
  modelDialog.value = true
}

async function saveModel() {
  await modelRef.value?.validate(async (valid: boolean) => {
    if (!valid) return
    saving.value = true
    try {
      await api.post('/ai/models', modelForm)
      ElMessage.success('模型已保存')
      modelDialog.value = false
      await load()
    } finally {
      saving.value = false
    }
  })
}

function testModel(model: ModelRow) {
  chatModel.value = model
  chatMessages.value = []
  chatInput.value = ''
  chatDialog.value = true
}

async function checkModel(model: ModelRow) {
  modelTestingId.value = model.id
  try {
    const { data } = await api.post(`/ai/models/${model.id}/test`, null, { timeout: AI_TIMEOUT })
    if (data.ok) ElMessage.success(data.message || '连接正常')
    else ElMessage.error(data.message || '连接测试失败')
    await load()
  } catch {
    /* 全局拦截器已展示错误 */
  } finally {
    modelTestingId.value = null
  }
}

async function setDefault(model: ModelRow) {
  try {
    const { data } = await api.post(`/ai/models/${model.id}/default`)
    ElMessage.success(data.detail || '已设置默认模型')
    await load()
  } catch {
    /* 全局拦截器已展示错误 */
  }
}

async function removeModel(model: ModelRow) {
  try {
    await ElMessageBox.confirm(
      `删除模型「${modelLabel(model)}」？删除后不可恢复，正在使用它的群聊会回到优先级路由。`,
      '确认删除模型',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await api.delete(`/ai/models/${model.id}`)
    ElMessage.success('已删除模型')
    await load()
  } catch {
    /* 用户取消或接口错误由全局拦截器提示 */
  }
}

async function sendChat() {
  const text = chatInput.value.trim()
  if (!text || chatLoading.value || !chatModel.value) return
  chatMessages.value.push({ role: 'user', content: text })
  chatInput.value = ''
  chatLoading.value = true
  await scrollChat()
  try {
    const { data } = await api.post(
      '/ai/chat',
      {
        model_id: chatModel.value.id,
        messages: chatMessages.value.map(message => ({
          role: message.role === 'assistant' ? 'assistant' : 'user',
          content: message.content,
        })),
      },
      { timeout: AI_TIMEOUT },
    )
    if (data.ok) chatMessages.value.push({ role: 'assistant', content: data.content })
    else ElMessage.error(data.error || '模型调用失败')
  } finally {
    chatLoading.value = false
    await scrollChat()
  }
}

async function scrollChat() {
  await nextTick()
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

function openPlayground() {
  const defaultOption = models.value.find(model => model.is_default) || models.value.find(model => model.enabled !== false)
  if (defaultOption) pgModelId.value = defaultOption.id
  playgroundVisible.value = true
}

function clearPlayground() {
  pgMessages.value = []
  pgInput.value = ''
}

async function sendPlayground() {
  const text = pgInput.value.trim()
  if (!text || pgLoading.value) return
  if (!pgModelId.value) {
    ElMessage.warning('请选择要测试的 AI 模型')
    return
  }
  pgMessages.value.push({ role: 'user', content: text })
  pgInput.value = ''
  pgLoading.value = true
  await scrollPlayground()
  try {
    const { data } = await api.post(
      '/ai/chat',
      {
        model_id: pgModelId.value,
        system_prompt: pgSystemPrompt.value || undefined,
        temperature: pgTemperature.value,
        max_tokens: pgMaxTokens.value,
        messages: pgMessages.value.map(message => ({
          role: message.role === 'assistant' ? 'assistant' : 'user',
          content: message.content,
        })),
      },
      { timeout: AI_TIMEOUT },
    )
    if (data.ok) {
      pgMessages.value.push({
        role: 'assistant',
        content: data.content,
        meta: {
          latency_ms: data.latency_ms,
          usage: data.usage,
          model: data.model_name,
        },
      })
    } else {
      ElMessage.error(data.error || '模型调用失败')
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '请求失败')
  } finally {
    pgLoading.value = false
    await scrollPlayground()
  }
}

async function scrollPlayground() {
  await nextTick()
  if (pgChatBox.value) pgChatBox.value.scrollTop = pgChatBox.value.scrollHeight
}

function formatDate(value: string) {
  return value
    ? new Date(value).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : '—'
}

onMounted(async () => {
  newProvider()
  await load()
})
</script>

<style scoped>
.ai-page {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.ai-heading {
  margin-bottom: 18px;
}
.btn-icon {
  margin-right: 5px;
}
.ai-error {
  margin-bottom: 14px;
}
.ai-error :deep(.el-alert__content) {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ai-stats {
  margin-bottom: 8px;
}
.route-tile .stat-tile-copy {
  width: calc(100% - 49px);
}
.route-value {
  display: flex;
  max-width: 100%;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  font-size: 15px;
  line-height: 1.25;
}
.route-value,
.route-value small {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.route-value small {
  display: block;
  margin: 0;
  color: var(--text-3);
}
.scope-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 0 0 14px;
  padding: 0 2px;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.6;
}
.scope-note .app-icon {
  margin-top: 1px;
  color: var(--text-4);
}
.ai-sections {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 14px;
}
.providers-panel,
.models-panel,
.usage-panel {
  min-width: 0;
}
.section-count {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9.5px;
  white-space: nowrap;
}
.provider-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 11px;
}
.provider-empty b {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}
.provider-empty span {
  max-width: 420px;
  color: var(--text-3);
  line-height: 1.6;
}
.provider-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 11px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  transition: border-color var(--duration) var(--ease), background var(--duration) var(--ease);
}
.provider-card:hover {
  border-color: var(--line-strong);
  background: color-mix(in srgb, var(--surface-2) 78%, var(--surface-3));
}
.provider-card.is-off {
  border-style: dashed;
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
}
.provider-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}
.provider-mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.provider-title {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}
.provider-title b {
  overflow: hidden;
  color: var(--text);
  font-size: 12px;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.provider-title small {
  overflow: hidden;
  color: var(--text-3);
  font-size: 9.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.provider-enabled,
.provider-feedback,
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  width: fit-content;
  border: 1px solid var(--line);
  white-space: nowrap;
}
.provider-enabled {
  min-height: 22px;
  padding: 0 7px;
  border-radius: 99px;
  background: var(--surface);
  color: var(--text-3);
  font-size: 9px;
  font-weight: 600;
}
.provider-enabled.is-on {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}
.provider-enabled.is-off {
  color: var(--text-4);
}
.provider-meta {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
  color: var(--text-3);
  font-size: 9.5px;
}
.provider-meta > span {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}
.provider-meta > span > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.provider-meta .app-icon {
  flex: none;
  color: var(--text-4);
}
.provider-feedback {
  min-height: 25px;
  max-width: 100%;
  padding: 4px 8px;
  border-radius: 7px;
  background: var(--surface);
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.4;
}
.provider-feedback > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.provider-feedback small {
  color: inherit;
  font: 600 8.5px var(--font-mono);
}
.provider-feedback.ok {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}
.provider-feedback.bad {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}
.provider-feedback.testing {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}
.provider-feedback.testing .app-icon {
  animation: spin 1s linear infinite;
}
.provider-feedback.warn {
  border-color: var(--warning-line);
  background: var(--warning-soft);
  color: var(--warning);
}
.provider-remark {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.provider-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--line-soft);
}
.model-count {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-4);
  font-size: 9px;
}
.provider-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
}
.provider-actions .el-button {
  margin-left: 0;
  padding-inline: 5px;
  font-size: 9.5px;
}
.provider-actions .btn-icon {
  margin-right: 3px;
}
.surface-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
.table-scroll {
  min-width: 0;
  overflow-x: auto;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
}
.models-table {
  min-width: 1080px;
}
.usage-table {
  min-width: 900px;
}
.model-cell,
.provider-cell,
.token-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}
.model-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}
.model-title b {
  overflow: hidden;
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-title .el-tag {
  flex: none;
}
.model-cell code {
  overflow: hidden;
  color: var(--text-4);
  font: 9px/1.4 var(--font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.provider-cell span,
.usage-model {
  overflow: hidden;
  color: var(--text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.provider-cell small {
  color: var(--text-4);
  font-size: 8.5px;
}
.status-badge {
  min-height: 22px;
  padding: 0 7px;
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9px;
  font-weight: 550;
}
.status-badge small {
  color: inherit;
  font: 500 8px var(--font-mono);
}
.status-badge.ok {
  border-color: var(--success-line);
  background: var(--success-soft);
  color: var(--success);
}
.status-badge.bad {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}
.status-badge.info {
  border-color: var(--info-line);
  background: var(--info-soft);
  color: var(--info);
}
.status-badge.muted {
  color: var(--text-4);
}
.numeric {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.danger-text {
  color: var(--danger);
  font-weight: 600;
}
.row-actions {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: wrap;
}
.row-actions .el-button {
  margin-left: 0;
  padding-inline: 2px;
}
.table-empty {
  display: flex;
  min-height: 160px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--text-3);
  text-align: center;
}
.table-empty .app-icon {
  color: var(--text-4);
}
.table-empty b {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}
.table-empty span {
  max-width: 440px;
  font-size: 10px;
  line-height: 1.6;
}
.usage-head {
  align-items: center;
}
.usage-summary {
  gap: 6px;
}
.summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-4);
  font-size: 9px;
  white-space: nowrap;
}
.summary-chip b {
  color: var(--text-2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.summary-chip.is-danger {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger);
}
.summary-chip.is-danger b {
  color: var(--danger);
}
.usage-error {
  margin-bottom: 10px;
}
.usage-summary .el-button {
  margin-left: 2px;
}
.usage-model {
  display: block;
  color: var(--text-2);
  font-size: 10.5px;
}
.token-cell b {
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 600;
}
.token-cell small {
  color: var(--text-4);
  font: 8.5px var(--font-mono);
}
.error-detail {
  display: block;
  overflow: hidden;
  color: var(--danger);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.usage-pagination {
  border-top: 0;
  padding-bottom: 0;
  background: transparent;
}
.dialog-form .form-cols {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}
.form-hint {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin: 6px 0 0;
  color: var(--text-4);
  font-size: 9px;
  line-height: 1.5;
}
.form-hint .app-icon {
  margin-top: 1px;
  flex: none;
}
.checkbox-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.chat-dialog-shell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
}
.chat-context,
.playground-model,
.panel-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
}
.chat-context {
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-2);
}
.context-mark {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  border: 1px solid var(--brand-line);
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.chat-context > div,
.playground-model > div,
.panel-heading > div {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.chat-context b,
.playground-model b,
.panel-heading b {
  overflow: hidden;
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-context small,
.playground-model small,
.panel-heading small {
  overflow: hidden;
  color: var(--text-3);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-messages {
  min-height: 320px;
  max-height: 50vh;
  overflow-y: auto;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-inset);
}
.chat-empty {
  display: flex;
  min-height: 250px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--text-3);
  text-align: center;
}
.chat-empty .app-icon {
  color: var(--text-4);
}
.chat-empty b {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}
.chat-empty span {
  max-width: 460px;
  color: var(--text-4);
  font-size: 10px;
  line-height: 1.6;
}
.chat-line {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 14px;
}
.chat-line:last-child {
  margin-bottom: 0;
}
.chat-line.user {
  flex-direction: row-reverse;
}
.chat-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  flex: none;
  place-items: center;
  border: 1px solid var(--brand-line);
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.chat-line.user .chat-avatar {
  border-color: var(--cyan-line);
  background: var(--cyan-soft);
  color: var(--cyan);
}
.chat-body {
  display: flex;
  min-width: 0;
  max-width: min(82%, 620px);
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.chat-line.user .chat-body {
  align-items: flex-end;
}
.chat-role {
  color: var(--text-4);
  font-size: 8.5px;
}
.chat-bubble {
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 4px 11px 11px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 11px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.chat-line.user .chat-bubble {
  border-color: var(--brand-line);
  border-radius: 11px 4px 11px 11px;
  background: var(--brand-soft);
  color: var(--text);
}
.chat-bubble.typing {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-3);
}
.chat-bubble.typing .app-icon {
  animation: spin 1s linear infinite;
}
.bubble-meta {
  display: flex;
  align-items: center;
  gap: 6px 10px;
  flex-wrap: wrap;
  margin-top: 7px;
  padding-top: 6px;
  border-top: 1px solid var(--line-soft);
  color: var(--text-4);
  font: 8.5px var(--font-mono);
}
.bubble-meta span {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.chat-entry {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.chat-entry .el-input {
  min-width: 0;
  flex: 1;
}
.entry-hint {
  margin: -2px 0 0;
  color: var(--text-4);
  font-size: 8.5px;
}
.playground-container {
  display: grid;
  grid-template-columns: minmax(250px, 300px) minmax(0, 1fr);
  gap: 14px;
  max-height: calc(100vh - 200px);
  min-height: 520px;
}
.playground-sidebar,
.playground-chat {
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
}
.playground-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  padding: 14px;
}
.panel-heading-icon {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text-3);
}
.playground-form {
  min-width: 0;
}
.preset-block {
  margin: 0 0 12px;
}
.preset-block > span {
  display: block;
  margin-bottom: 6px;
  color: var(--text-2);
  font-size: 11px;
}
.preset-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.preset-chip {
  padding: 4px 7px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  color: var(--text-3);
  font-size: 9px;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease), color var(--duration-fast) var(--ease);
}
.preset-chip:hover,
.preset-chip:focus-visible {
  border-color: var(--brand-line);
  color: var(--brand-strong);
}
.slider-item :deep(.el-slider) {
  width: 100%;
}
.playground-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--line-soft);
}
.playground-foot > span {
  color: var(--text-4);
  font-size: 9px;
}
.playground-chat {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  background: var(--surface);
}
.playground-topbar {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line-soft);
}
.playground-model {
  min-width: 0;
}
.pg-messages {
  flex: 1;
  min-height: 0;
  max-height: none;
}
.playground-entry {
  padding-top: 2px;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 900px) {
  .playground-container {
    grid-template-columns: 1fr;
    max-height: none;
    min-height: 0;
  }
  .playground-sidebar {
    max-height: 360px;
  }
  .pg-messages {
    height: 340px;
    flex: none;
  }
}
@media (max-width: 700px) {
  .ai-heading .heading-actions {
    width: 100%;
  }
  .ai-heading .heading-actions .el-button {
    flex: 1;
    margin-left: 0;
  }
  .provider-grid {
    grid-template-columns: 1fr;
  }
  .providers-panel .surface-head,
  .models-panel .surface-head,
  .usage-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .surface-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .usage-summary {
    width: 100%;
  }
  .usage-summary .summary-chip {
    flex: 1;
    justify-content: center;
  }
  .dialog-form .form-cols {
    grid-template-columns: 1fr;
    gap: 0;
  }
  .checkbox-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
  .chat-messages {
    min-height: 280px;
    padding: 12px;
  }
  .chat-body {
    max-width: 86%;
  }
  .chat-entry {
    align-items: stretch;
    flex-direction: column;
  }
  .chat-entry .el-button {
    align-self: flex-end;
  }
  .playground-chat {
    padding: 12px;
  }
  .playground-topbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
@media (max-width: 520px) {
  .provider-actions {
    width: 100%;
  }
  .provider-actions .el-button {
    flex: 1 1 calc(50% - 4px);
    justify-content: flex-start;
  }
  .usage-pagination {
    align-items: flex-start;
    flex-direction: column;
  }
  .chat-dialog-shell .status-badge {
    display: none;
  }
}
</style>
