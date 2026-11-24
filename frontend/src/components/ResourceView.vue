<template>
  <div class="page-heading resource-page-heading">
    <div class="resource-heading-copy">
      <div class="eyebrow">{{ config.kicker || 'MANAGEMENT' }}</div>
      <h1>{{ config.title }}</h1>
      <p>{{ config.description }}</p>
    </div>
    <div class="heading-actions resource-heading-actions">
      <el-button
        v-if="config.secondaryAction"
        :icon="config.secondaryAction.icon || Refresh"
        @click="runSecondary"
      >
        {{ config.secondaryAction.label }}
      </el-button>
      <el-button
        v-if="config.secondaryCreateLabel"
        :icon="config.secondaryCreateIcon || 'Setting'"
        @click="openRawCreate"
      >
        {{ config.secondaryCreateLabel }}
      </el-button>
      <el-button
        v-if="config.extraCreateLabel"
        :icon="config.extraCreateIcon || 'Iphone'"
        @click="runExtraCreate"
      >
        {{ config.extraCreateLabel }}
      </el-button>
      <el-button v-if="canCreate" type="primary" @click="openCreate">
        <AppIcon name="plus" :size="14" class="button-icon" />
        {{ config.createLabel || '新增' }}
      </el-button>
    </div>
  </div>

  <slot name="panel" />

  <section class="surface resource-surface">
    <div class="resource-toolbar">
      <div class="resource-toolbar-main">
        <div v-if="hasToolbarFilters" class="filter-row resource-filter-row">
          <el-input
            v-if="config.keyword"
            v-model="filters.keyword"
            class="resource-keyword"
            clearable
            :placeholder="config.keyword"
            @keyup.enter="load(1)"
            @clear="load(1)"
          >
            <template #prefix><AppIcon name="search" :size="14" /></template>
          </el-input>

          <template v-for="filter in config.filters || []" :key="filter.key">
            <el-input
              v-if="filter.type === 'input'"
              v-model="filters[filter.key]"
              class="resource-filter-input"
              clearable
              :placeholder="filter.placeholder || filter.label"
              @keyup.enter="load(1)"
              @clear="load(1)"
            >
              <template #prefix><AppIcon name="filter" :size="13" /></template>
            </el-input>
            <el-select
              v-else
              v-model="filters[filter.key]"
              class="resource-filter-select"
              clearable
              :placeholder="filter.label"
              @change="load(1)"
            >
              <el-option
                v-for="option in filter.options || []"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </template>

          <el-select
            v-if="config.statusFilter"
            v-model="filters.status"
            class="resource-filter-select"
            clearable
            placeholder="状态"
            @change="load(1)"
          >
            <el-option
              v-for="option in config.statusFilter"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>

          <el-button type="primary" @click="load(1)">
            <AppIcon name="search" :size="14" class="button-icon" />查询
          </el-button>
          <el-button v-if="hasActiveFilters" text type="primary" @click="resetFilters">
            <AppIcon name="filter" :size="14" class="button-icon" />清除筛选
          </el-button>
        </div>
      </div>

      <div class="resource-toolbar-actions">
        <span v-if="showResultCount" class="resource-count">{{ resultLabel }}</span>
        <el-button :loading="loading" @click="load()">
          <AppIcon name="refresh" :size="14" class="button-icon" />刷新
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="loadError"
      class="resource-error"
      type="error"
      show-icon
      :closable="false"
      title="数据加载失败"
    >
      <template #default>
        <span>{{ loadError }}</span>
        <el-button link type="danger" @click="load()">重试</el-button>
      </template>
    </el-alert>

    <div v-if="!config.cardView" class="resource-table-wrap">
      <el-table
        v-loading="loading"
        :data="rows"
        row-key="id"
        stripe
        style="width: 100%"
      >
        <el-table-column
          v-for="col in config.columns"
          :key="col.key"
          :prop="col.key"
          :label="col.label"
          :min-width="col.width || 120"
          :show-overflow-tooltip="col.overflow !== false"
        >
          <template #default="scope">
            <template v-if="col.type === 'status'">
              <el-tag
                :type="tagType(getValue(scope.row, col.key), col)"
                effect="dark"
                round
                class="resource-tag"
              >
                <AppIcon
                  :name="statusIcon(getValue(scope.row, col.key), col)"
                  :size="11"
                  class="tag-icon"
                />
                {{ display(getValue(scope.row, col.key), col) }}
              </el-tag>
            </template>
            <template v-else-if="col.type === 'bool'">
              <el-tag
                :type="getValue(scope.row, col.key) ? 'success' : 'info'"
                effect="dark"
                size="small"
                class="resource-tag"
              >
                <AppIcon
                  :name="getValue(scope.row, col.key) ? 'check' : 'close'"
                  :size="11"
                  class="tag-icon"
                />
                {{ getValue(scope.row, col.key) ? '启用' : '关闭' }}
              </el-tag>
            </template>
            <template v-else-if="col.type === 'date'">
              {{ formatDate(getValue(scope.row, col.key)) }}
            </template>
            <template v-else-if="col.type === 'link'">
              <a
                class="table-link"
                :href="getValue(scope.row, col.key)"
                target="_blank"
                rel="noreferrer"
              >
                {{ getValue(scope.row, col.key) || '—' }}
              </a>
            </template>
            <template v-else>{{ display(getValue(scope.row, col.key), col) }}</template>
          </template>
        </el-table-column>

        <el-table-column
          v-if="hasRowActions"
          label="操作"
          :width="config.actionWidth || 210"
          fixed="right"
          class-name="resource-action-column"
        >
          <template #default="scope">
            <div class="row-actions">
              <el-button
                v-for="(action, actionIndex) in config.actions || []"
                :key="actionKey(action, actionIndex)"
                link
                :type="action.type || 'primary'"
                @click="runAction(action, scope.row)"
              >
                {{ action.labelFor?.(scope.row) || action.label }}
              </el-button>
              <el-button
                v-if="config.editFields?.length"
                link
                type="primary"
                :aria-label="`编辑${config.itemName || '记录'} ${rowName(scope.row)}`"
                @click="openEdit(scope.row)"
              >
                {{ config.editLabel || '编辑' }}
              </el-button>
              <el-button
                v-if="config.deletePath"
                link
                type="danger"
                :aria-label="`删除${config.itemName || '记录'} ${rowName(scope.row)}`"
                @click="remove(scope.row)"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="empty-inline resource-empty">
            <span class="resource-empty-icon">
              <AppIcon :name="emptyIcon" :size="24" />
            </span>
            <div class="resource-empty-copy">
              <strong>{{ emptyTitle }}</strong>
              <span>{{ emptyDescription }}</span>
            </div>
            <div v-if="loadError" class="resource-empty-actions">
              <el-button type="primary" @click="load()">
                <AppIcon name="refresh" :size="14" class="button-icon" />重新加载
              </el-button>
            </div>
            <div v-else-if="hasActiveFilters" class="resource-empty-actions">
              <el-button type="primary" plain @click="resetFilters">
                <AppIcon name="filter" :size="14" class="button-icon" />清除筛选
              </el-button>
            </div>
            <div v-else-if="canCreate" class="resource-empty-actions">
              <el-button type="primary" @click="openCreate">
                <AppIcon name="plus" :size="14" class="button-icon" />
                {{ config.createLabel || '新增' }}
              </el-button>
            </div>
          </div>
        </template>
      </el-table>
    </div>

    <div v-else v-loading="loading" class="resource-card-stage">
      <div v-if="rows.length" class="resource-cards">
        <article
          v-for="(row, rowIndex) in rows"
          :key="row.id ?? rowIndex"
          class="resource-card"
        >
          <header class="resource-card-head">
            <span class="resource-card-icon">
              <AppIcon :name="config.cardIcon || 'layers'" :size="18" />
            </span>
            <div class="resource-card-heading">
              <b>{{ cardTitle(row) }}</b>
              <span v-if="cardSubtitle(row)" class="resource-card-subtitle">
                <span v-if="cardSubtitleField" class="resource-card-subtitle-label">
                  {{ cardSubtitleField.label }}
                </span>
                {{ cardSubtitle(row) }}
              </span>
            </div>
          </header>

          <div v-if="cardDetailFields.length" class="resource-card-fields">
            <div
              v-for="field in cardDetailFields"
              :key="field.key"
              class="resource-card-field"
            >
              <span class="resource-card-field-label">{{ field.label }}</span>
              <div class="resource-card-field-value">
                <el-tag
                  v-if="field.type === 'status'"
                  :type="tagType(getValue(row, field.key), field)"
                  effect="dark"
                  round
                  class="resource-tag"
                >
                  <AppIcon
                    :name="statusIcon(getValue(row, field.key), field)"
                    :size="11"
                    class="tag-icon"
                  />
                  {{ cardDisplayValue(row, field) }}
                </el-tag>
                <el-tag
                  v-else-if="field.type === 'bool'"
                  :type="getValue(row, field.key) ? 'success' : 'info'"
                  effect="dark"
                  class="resource-tag"
                >
                  <AppIcon
                    :name="getValue(row, field.key) ? 'check' : 'close'"
                    :size="11"
                    class="tag-icon"
                  />
                  {{ cardDisplayValue(row, field) }}
                </el-tag>
                <a
                  v-else-if="field.type === 'link'"
                  class="table-link"
                  :href="getValue(row, field.key)"
                  target="_blank"
                  rel="noreferrer"
                >
                  {{ cardDisplayValue(row, field) }}
                </a>
                <span v-else :class="{ 'is-mono': field.mono }">
                  {{ cardDisplayValue(row, field) }}
                </span>
              </div>
            </div>
          </div>

          <footer v-if="hasRowActions" class="resource-card-actions">
            <el-button
              v-for="(action, actionIndex) in config.actions || []"
              :key="actionKey(action, actionIndex)"
              size="small"
              plain
              :type="action.type || 'primary'"
              :aria-label="`${action.labelFor?.(row) || action.label} ${rowName(row)}`"
              @click="runAction(action, row)"
            >
              {{ action.labelFor?.(row) || action.label }}
            </el-button>
            <el-button
              v-if="config.editFields?.length"
              size="small"
              plain
              type="primary"
              :aria-label="`编辑${config.itemName || '记录'} ${rowName(row)}`"
              @click="openEdit(row)"
            >
              <AppIcon name="edit" :size="13" class="button-icon" />
              {{ config.editLabel || '编辑' }}
            </el-button>
            <el-button
              v-if="config.deletePath"
              size="small"
              plain
              type="danger"
              :aria-label="`删除${config.itemName || '记录'} ${rowName(row)}`"
              @click="remove(row)"
            >
              <AppIcon name="trash" :size="13" class="button-icon" />删除
            </el-button>
          </footer>
        </article>
      </div>

      <div v-else-if="!loading" class="empty-inline resource-empty">
        <span class="resource-empty-icon">
          <AppIcon :name="emptyIcon" :size="24" />
        </span>
        <div class="resource-empty-copy">
          <strong>{{ emptyTitle }}</strong>
          <span>{{ emptyDescription }}</span>
        </div>
        <div v-if="loadError" class="resource-empty-actions">
          <el-button type="primary" @click="load()">
            <AppIcon name="refresh" :size="14" class="button-icon" />重新加载
          </el-button>
        </div>
        <div v-else-if="hasActiveFilters" class="resource-empty-actions">
          <el-button type="primary" plain @click="resetFilters">
            <AppIcon name="filter" :size="14" class="button-icon" />清除筛选
          </el-button>
        </div>
        <div v-else-if="canCreate" class="resource-empty-actions">
          <el-button type="primary" @click="openCreate">
            <AppIcon name="plus" :size="14" class="button-icon" />
            {{ config.createLabel || '新增' }}
          </el-button>
        </div>
      </div>
    </div>

    <div v-if="paged" class="pagination-wrap">
      <span>共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="sizes, prev, pager, next"
        @current-change="load"
        @size-change="load(1)"
      />
    </div>
  </section>

  <el-dialog
    v-model="dialog"
    :title="dialogTitle"
    width="min(680px, calc(100vw - 28px))"
    destroy-on-close
    class="resource-dialog"
  >
    <template #header>
      <div class="resource-dialog-heading">
        <span class="resource-dialog-icon">
          <AppIcon :name="editing ? 'edit' : 'plus'" :size="17" />
        </span>
        <div>
          <h3>{{ dialogTitle }}</h3>
          <p>
            {{ editing
              ? `更新${config.itemName || '记录'}信息，保存后会重新载入列表。`
              : `填写${config.itemName || '记录'}信息，带 * 的字段为必填项。` }}
          </p>
        </div>
      </div>
    </template>

    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="resource-form"
      @submit.prevent
    >
      <el-form-item
        v-for="field in activeFields"
        :key="field.key"
        :label="field.label"
        :prop="field.required ? field.key : undefined"
        :required="!!field.required"
        :class="{ 'resource-form-wide': isWideField(field) }"
      >
        <el-select
          v-if="field.type === 'select'"
          v-model="form[field.key]"
          :placeholder="field.placeholder || '请选择'"
          clearable
          :disabled="field.disabled || field.readonly"
          @change="field.onChange ? field.onChange($event, form) : undefined"
        >
          <el-option
            v-for="option in field.options || []"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-switch
          v-else-if="field.type === 'switch'"
          v-model="form[field.key]"
          :aria-label="field.label"
        />
        <el-input-number
          v-else-if="field.type === 'number'"
          v-model="form[field.key]"
          :min="field.min ?? 0"
          :max="field.max"
          :step="field.step || 1"
          :placeholder="field.placeholder"
        />
        <el-input
          v-else-if="field.type === 'textarea' || field.type === 'json'"
          v-model="form[field.key]"
          type="textarea"
          :rows="field.rows || 3"
          :placeholder="field.placeholder"
          resize="vertical"
        />
        <el-input
          v-else
          v-model="form[field.key]"
          :type="field.type === 'password' ? 'password' : 'text'"
          :show-password="field.type === 'password'"
          :placeholder="field.placeholder || field.label"
          :disabled="!!field.disabled"
          :readonly="!!field.readonly"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">
        <AppIcon name="check" :size="14" class="button-icon" />保存
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '../api'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ config: any }>()
const config = computed(() => props.config)
const rows = ref<any[]>([])
const loading = ref(false)
const saving = ref(false)
const dialog = ref(false)
const editing = ref(false)
const formRef = ref<any>()
const activeRow = ref<any>()
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loadError = ref('')
const loadedOnce = ref(false)

const paged = computed(() => config.value.paged !== false)
const canCreate = computed(() => Boolean(config.value.createFields?.length && !config.value.hideCreate))
const hasRowActions = computed(() =>
  Boolean(config.value.actions?.length || config.value.editFields?.length || config.value.deletePath),
)
const activeFields = computed(() => {
  const fields = editing.value
    ? (config.value.editFields || config.value.createFields || [])
    : (config.value.createFields || [])
  return (fields || []).filter((field: any) => !field.showWhen || field.showWhen(form))
})
const filters = reactive<Record<string, any>>(
  Object.fromEntries([
    ...(config.value.filters || []).map((filter: any) => [filter.key, '']),
    ...(config.value.keyword ? [['keyword', '']] : []),
  ]),
)
const form = reactive<Record<string, any>>({})
const rules = computed(() =>
  Object.fromEntries(
    (activeFields.value || [])
      .filter((field: any) => field.required)
      .map((field: any) => [
        field.key,
        [{ required: true, message: `${field.label}不能为空`, trigger: field.type === 'select' ? 'change' : 'blur' }],
      ]),
  ) as any,
)

const hasToolbarFilters = computed(() =>
  Boolean(config.value.keyword || config.value.filters?.length || config.value.statusFilter),
)
const hasActiveFilters = computed(() =>
  Object.values(filters).some((value) => value !== undefined && value !== null && value !== ''),
)
const showResultCount = computed(() => loadedOnce.value && !loading.value && !loadError.value)
const resultLabel = computed(() => {
  const count = paged.value ? Number(total.value || 0) : rows.value.length
  return `共 ${count.toLocaleString('zh-CN')} 条`
})

const cardColumns = computed(() =>
  (config.value.cardFields?.length ? config.value.cardFields : config.value.columns || []).filter(Boolean),
)
const cardTitleKey = computed(
  () => config.value.cardTitleKey || cardColumns.value[0]?.key || config.value.nameKey || 'name',
)
const cardTitleField = computed(() =>
  cardColumns.value.find((field: any) => field.key === cardTitleKey.value),
)
const cardSubtitleKey = computed(
  () => config.value.cardSubtitleKey || (cardColumns.value.length > 1 ? cardColumns.value[1].key : ''),
)
const cardSubtitleField = computed(() =>
  cardColumns.value.find((field: any) => field.key === cardSubtitleKey.value),
)
const cardDetailFields = computed(() =>
  cardColumns.value.filter(
    (field: any) => field.key !== cardTitleKey.value && field.key !== cardSubtitleKey.value,
  ),
)

const emptyTitle = computed(() => {
  if (loadError.value) return '数据加载失败'
  if (hasActiveFilters.value) return '没有匹配的结果'
  return config.value.emptyText || '暂无数据'
})
const emptyDescription = computed(() => {
  if (loadError.value) return loadError.value
  if (hasActiveFilters.value) {
    return config.value.filteredEmptyHint || '当前筛选条件下没有记录，清除筛选后可查看全部数据。'
  }
  if (config.value.emptyHint) return config.value.emptyHint
  if (canCreate.value) {
    return `还没有${config.value.itemName || '记录'}，点击下方按钮创建第一条记录。`
  }
  return `当前没有可显示的${config.value.itemName || '记录'}，请稍后刷新或检查筛选条件。`
})
const emptyIcon = computed(() => {
  if (loadError.value) return 'alert'
  if (hasActiveFilters.value) return 'filter'
  return config.value.emptyIcon || 'inbox'
})
const dialogTitle = computed(() =>
  editing.value
    ? `编辑${config.value.itemName || ''}`
    : `${config.value.rawCreateLabel || config.value.createLabel || '新增'}${config.value.itemName || ''}`,
)

function params() {
  const query: Record<string, any> = {}
  if (paged.value) {
    query.page = page.value
    query.page_size = pageSize.value
  }
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '' && value !== null) {
      const filter = config.value.filters?.find((item: any) => item.key === key)
      query[filter?.param || key] = value
    }
  }
  if (config.value.keyword && filters.keyword) query.keyword = filters.keyword
  return query
}

function errorText(error: any) {
  const raw = error?.response?.data?.detail
  return typeof raw === 'string' && raw ? raw : '请求失败，请检查连接后重试'
}

async function load(target?: number) {
  if (target) page.value = target
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get(config.value.endpoint, { params: params() })
    const payload = data?.items ? data : data?.data?.items ? data.data : data
    rows.value = Array.isArray(payload) ? payload : (payload.items || [])
    total.value = Array.isArray(payload) ? rows.value.length : (payload.total ?? rows.value.length)
    loadedOnce.value = true
  } catch (error) {
    loadError.value = errorText(error)
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  for (const key of Object.keys(filters)) filters[key] = ''
  load(1)
}

function resetForm(row?: any) {
  Object.keys(form).forEach((key) => delete form[key])
  const fields = row
    ? (config.value.editFields || config.value.createFields || [])
    : (config.value.createFields || [])
  for (const field of fields) {
    let value = row?.[field.payloadKey || field.key]
    if (value === undefined || value === null) {
      value = field.default ?? (field.type === 'switch' ? false : field.type === 'number' ? 0 : '')
    }
    if (field.type === 'json' && typeof value !== 'string') {
      value = JSON.stringify(value, null, 2)
    }
    form[field.key] = value
  }
}

function openCreate() {
  if (config.value.onCreate) {
    config.value.onCreate()
    return
  }
  openRawCreate()
}

function runExtraCreate() {
  config.value.onExtraCreate?.()
}

function openRawCreate() {
  editing.value = false
  activeRow.value = null
  resetForm()
  dialog.value = true
  config.value.onDialogOpen?.(false, null, form)
}

function openEdit(row: any) {
  editing.value = true
  activeRow.value = row
  resetForm(row)
  dialog.value = true
  config.value.onDialogOpen?.(true, row, form)
}

async function save() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  saving.value = true
  try {
    const payload: Record<string, any> = {}
    for (const field of activeFields.value) {
      if (field.readonly) continue
      let value = form[field.key]
      if (field.type === 'json' && typeof value === 'string') {
        try {
          value = JSON.parse(value)
        } catch {
          ElMessage.error(`${field.label}必须是合法 JSON`)
          return
        }
      }
      payload[field.payloadKey || field.key] = value
    }
    if (editing.value) {
      await api.put(`${config.value.endpoint}/${activeRow.value.id}`, payload)
    } else {
      await api.post(config.value.createEndpoint || config.value.endpoint, payload)
    }
    ElMessage.success('已保存')
    dialog.value = false
    await load()
  } catch (error) {
    ElMessage.error(errorText(error))
  } finally {
    saving.value = false
  }
}

function rowName(row: any) {
  return row[config.value.nameKey || 'name'] || row.id
}

async function remove(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除${config.value.itemName}「${rowName(row)}」吗？此操作不可撤销。`,
      '确认删除',
      { type: 'warning' },
    )
    await api.delete(`${config.value.deletePath || config.value.endpoint}/${row.id}`)
    ElMessage.success('已删除')
    await load()
  } catch {
    /* cancelled */
  }
}

async function runAction(action: any, row: any) {
  try {
    if (action.handler) {
      await action.handler(row, load)
      return
    }
    if (action.confirm) {
      await ElMessageBox.confirm(
        action.confirm.replace('{name}', rowName(row)),
        '确认操作',
        { type: action.type === 'danger' ? 'warning' : 'info' },
      )
    }
    const url = action.path
      ? (typeof action.path === 'function' ? action.path(row) : action.path.replace('{id}', row.id))
      : `${config.value.endpoint}/${row.id}/${action.suffix}`
    const body = typeof action.body === 'function' ? action.body(row) : action.body
    const { data } = await api.request({ url, method: action.method || 'POST', data: body })
    ElMessage.success(action.success?.(data) || data?.detail || data?.message || '操作已完成')
    await load()
  } catch {
    /* cancelled or handled by the API interceptor */
  }
}

async function runSecondary() {
  const action = config.value.secondaryAction
  if (!action) return
  try {
    if (action.confirm) await ElMessageBox.confirm(action.confirm, '确认操作')
    const { data } = await api.request({
      url: action.path || `${config.value.endpoint}${action.suffix || ''}`,
      method: action.method || 'POST',
      data: action.body || {},
    })
    ElMessage.success(
      action.success?.(data) || data?.detail || data?.message || '操作已完成',
    )
    await load()
  } catch {
    /* cancelled or handled by the API interceptor */
  }
}

function getValue(row: any, key: string) {
  return key.split('.').reduce((value, part) => value?.[part], row)
}

function display(value: any, col: any) {
  if (value === undefined || value === null || value === '') return '—'
  if (col.options) return col.options.find((option: any) => option.value === value)?.label || value
  if (typeof value === 'object') return JSON.stringify(value)
  return value
}

function tagType(value: any, col: any) {
  const mapped = col.statusMap?.[value]
  if (mapped && typeof mapped === 'object' && mapped.type) return mapped.type
  if (typeof mapped === 'string') return mapped
  return ({
    online: 'success',
    success: 'success',
    running: 'warning',
    loaded: 'success',
    enabled: 'success',
    error: 'danger',
    failed: 'danger',
    offline: 'info',
    stopped: 'info',
    pending: 'warning',
    connecting: 'warning',
  } as Record<string, string>)[value] || 'info'
}

function statusIcon(value: any, col: any) {
  const mapped = col.statusMap?.[value]
  if (mapped && typeof mapped === 'object' && mapped.icon) return mapped.icon
  return ({
    online: 'check-circle',
    success: 'check-circle',
    enabled: 'check-circle',
    loaded: 'check-circle',
    running: 'play',
    error: 'alert',
    failed: 'alert',
    pending: 'clock',
    connecting: 'loader',
    starting: 'loader',
    stopping: 'loader',
    offline: 'server-off',
    stopped: 'server-off',
    closed: 'server-off',
  } as Record<string, string>)[value] || 'info'
}

function formatDate(value: any) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

function formatCardValue(row: any, field: any) {
  const raw = getValue(row, field.key)
  if (typeof field.format === 'function') {
    const formatted = field.format(raw, row)
    if (formatted !== undefined && formatted !== null && formatted !== '') return formatted
  }
  if (field.type === 'date') return formatDate(raw)
  if (field.type === 'bool') {
    if (raw === undefined || raw === null) return '—'
    return raw ? '启用' : '关闭'
  }
  if (field.type === 'status' || field.options) return display(raw, field)
  if (raw === undefined || raw === null || raw === '') return '—'
  if (typeof raw === 'object') return JSON.stringify(raw)
  return raw
}

function cardDisplayValue(row: any, field: any) {
  const value = formatCardValue(row, field)
  return value === undefined || value === null || value === '' ? '—' : value
}

function cardTitle(row: any) {
  if (cardTitleField.value) return cardDisplayValue(row, cardTitleField.value)
  return getValue(row, cardTitleKey.value) || rowName(row) || '—'
}

function cardSubtitle(row: any) {
  if (cardSubtitleField.value) return cardDisplayValue(row, cardSubtitleField.value)
  return cardSubtitleKey.value ? getValue(row, cardSubtitleKey.value) || '' : ''
}

function actionKey(action: any, index: number) {
  return action.label || action.suffix || `action-${index}`
}

function isWideField(field: any) {
  return Boolean(field.fullWidth || field.type === 'textarea' || field.type === 'json')
}

onMounted(() => load())

defineExpose({ openCreate, load, rows })
</script>

<style scoped>
.resource-page-heading {
  margin-bottom: 18px;
}

.resource-heading-copy {
  min-width: 0;
}

.resource-heading-copy p {
  overflow-wrap: anywhere;
}

.resource-heading-actions {
  max-width: 100%;
}

.button-icon {
  margin-right: 5px;
}

.resource-surface {
  border-radius: var(--radius-lg);
}

.resource-surface:hover {
  border-color: var(--line-strong);
}

.resource-toolbar {
  min-width: 0;
  background: color-mix(in srgb, var(--surface-2) 62%, transparent);
}

.resource-toolbar-main {
  flex: 1;
  min-width: 0;
}

.resource-filter-row {
  gap: 8px;
}

.resource-keyword {
  width: 250px;
}

.resource-filter-input {
  width: 168px;
}

.resource-filter-select {
  width: 158px;
}

.resource-toolbar-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex: none;
}

.resource-count {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-inset);
  color: var(--text-3);
  font: 550 10px/1 var(--font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.resource-error {
  margin: 14px 18px 0;
}

.resource-table-wrap {
  min-width: 0;
  overflow: hidden;
}

.resource-table-wrap :deep(.el-table__fixed-right) {
  box-shadow: -14px 0 26px color-mix(in srgb, var(--canvas) 18%, transparent);
}

.resource-table-wrap :deep(.el-table__fixed-right-patch) {
  background: var(--surface);
}

.resource-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tag-icon {
  margin-right: 1px;
}

.row-actions {
  align-items: center;
  justify-content: flex-start;
  gap: 2px 10px;
  flex-wrap: wrap;
  white-space: normal;
}

.row-actions :deep(.el-button) {
  margin-left: 0;
  padding-inline: 0;
}

.table-link {
  color: var(--brand-strong);
  font-weight: 550;
  text-decoration: none;
  overflow-wrap: anywhere;
}

.table-link:hover {
  color: var(--brand);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.resource-card-stage {
  min-height: 240px;
  padding: 16px;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 42%, transparent), transparent 36%),
    color-mix(in srgb, var(--surface-inset) 46%, transparent);
}

.resource-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
  gap: 12px;
}

.resource-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 15px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--brand-soft) 34%, transparent), transparent 52%),
    var(--surface);
  box-shadow: var(--shadow-xs);
  transition:
    border-color var(--duration) var(--ease),
    box-shadow var(--duration) var(--ease),
    transform var(--duration) var(--ease);
}

.resource-card:hover {
  border-color: var(--brand-line);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.resource-card-head {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  min-width: 0;
}

.resource-card-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.resource-card-heading {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.resource-card-heading > b {
  color: var(--text);
  font-size: 13.5px;
  font-weight: 650;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.resource-card-subtitle {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  color: var(--text-3);
  font: 500 10.5px/1.55 var(--font-mono);
  overflow-wrap: anywhere;
}

.resource-card-subtitle-label {
  flex: none;
  color: var(--text-4);
  font-family: var(--font-sans);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.resource-card-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 8px;
  margin-top: 13px;
}

.resource-card-field {
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--surface-2) 52%, transparent);
}

.resource-card-field-label {
  display: block;
  margin-bottom: 4px;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.35;
}

.resource-card-field-value {
  min-width: 0;
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 550;
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.resource-card-field-value .is-mono {
  font-family: var(--font-mono);
}

.resource-card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line-soft);
}

.resource-card-actions :deep(.el-button) {
  margin-left: 0;
}

.resource-empty {
  min-height: 230px;
  gap: 11px;
}

.resource-empty-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border: 1px solid var(--brand-line);
  border-radius: 14px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.resource-empty-copy {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  max-width: 560px;
}

.resource-empty-copy strong {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 620;
}

.resource-empty-copy span {
  color: var(--text-3);
  font-size: 11px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.resource-empty-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pagination-wrap {
  background: color-mix(in srgb, var(--surface-2) 42%, transparent);
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.pagination-wrap :deep(.el-pagination) {
  max-width: 100%;
  flex-wrap: wrap;
  row-gap: 6px;
}

:global(.resource-dialog) {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 28px);
  max-height: calc(100dvh - 28px);
  margin: 14px auto !important;
}

:global(.resource-dialog .el-dialog__header) {
  padding: 20px 24px 0;
}

:global(.resource-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 24px 8px;
}

:global(.resource-dialog .el-dialog__footer) {
  flex: none;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 45%, transparent);
}

.resource-dialog-heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding-right: 34px;
}

.resource-dialog-icon {
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

.resource-dialog-heading h3 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.resource-dialog-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.6;
}

.resource-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
  align-items: start;
}

.resource-form :deep(.el-form-item) {
  min-width: 0;
  margin-bottom: 16px;
}

.resource-form :deep(.el-form-item__label) {
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 580;
  line-height: 1.5;
}

.resource-form :deep(.el-select),
.resource-form :deep(.el-input-number) {
  width: 100%;
}

.resource-form :deep(.el-textarea__inner) {
  min-height: 92px !important;
  line-height: 1.65;
}

.resource-form-wide {
  grid-column: 1 / -1;
}

@media (max-width: 840px) {
  .resource-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .resource-toolbar-actions {
    justify-content: space-between;
    width: 100%;
  }

  .resource-filter-row {
    width: 100%;
  }

  .resource-keyword,
  .resource-filter-input,
  .resource-filter-select {
    width: 100%;
  }
}

@media (max-width: 700px) {
  .resource-page-heading {
    margin-bottom: 15px;
  }

  .resource-card-stage {
    padding: 12px;
  }

  .resource-cards {
    grid-template-columns: 1fr;
  }

  .resource-form {
    grid-template-columns: 1fr;
  }

  .resource-form-wide {
    grid-column: 1;
  }

  .resource-empty {
    min-height: 210px;
    padding: 24px 16px;
  }
}

@media (max-width: 600px) {
  .pagination-wrap {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
