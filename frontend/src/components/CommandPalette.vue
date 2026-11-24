<template>
  <Teleport to="body">
    <div v-if="modelValue" class="cmd-overlay" role="presentation" @mousedown.self="close">
      <section class="cmd-panel" role="dialog" aria-modal="true" aria-label="快捷命令">
        <div class="cmd-search">
          <AppIcon name="search" :size="18" />
          <input
            ref="inputRef"
            v-model="query"
            type="text"
            placeholder="搜索页面、功能或快捷操作…"
            aria-label="搜索页面与操作"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="choose(selectedIndex)"
            @keydown.esc.prevent="close"
          />
          <kbd>ESC</kbd>
        </div>
        <div class="cmd-list" ref="listRef">
          <template v-if="filteredGroups.length">
            <div v-for="group in filteredGroups" :key="group.label">
              <p class="cmd-group">{{ group.label }}</p>
              <button
                v-for="item in group.items"
                :key="item.id"
                type="button"
                class="cmd-item"
                :class="{ selected: flatItems[selectedIndex]?.id === item.id }"
                @mouseenter="focusItem(item)"
                @click="chooseById(item.id)"
              >
                <span class="cmd-item-icon"><AppIcon :name="item.icon || 'command'" :size="16" /></span>
                <span class="cmd-item-copy">
                  <b>{{ item.title }}</b>
                  <small v-if="item.description">{{ item.description }}</small>
                </span>
                <span v-if="item.meta" class="cmd-item-meta">{{ item.meta }}</span>
              </button>
            </div>
          </template>
          <div v-else class="cmd-empty">
            <AppIcon name="search" :size="24" />
            <span>没有匹配的页面或操作</span>
          </div>
        </div>
        <div class="cmd-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> 浏览</span>
          <span><kbd>↵</kbd> 打开</span>
          <span><kbd>ESC</kbd> 关闭</span>
          <span style="margin-left:auto">QBOT AI COMMAND</span>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

export type CommandItem = {
  id: string
  title: string
  description?: string
  icon?: string
  meta?: string
  group: string
  keywords?: string
}

const props = defineProps<{
  modelValue: boolean
  items: CommandItem[]
}>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'select', item: CommandItem): void
}>()

const query = ref('')
const inputRef = ref<HTMLInputElement>()
const listRef = ref<HTMLElement>()
const selectedIndex = ref(0)

const filteredItems = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return props.items
  return props.items.filter((item) => {
    const haystack = `${item.title} ${item.description || ''} ${item.keywords || ''} ${item.group}`.toLowerCase()
    return haystack.includes(keyword)
  })
})

const filteredGroups = computed(() => {
  const groups: { label: string; items: CommandItem[] }[] = []
  for (const item of filteredItems.value) {
    let group = groups.find((entry) => entry.label === item.group)
    if (!group) {
      group = { label: item.group, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
})

const flatItems = computed(() => filteredGroups.value.flatMap((group) => group.items))

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    query.value = ''
    selectedIndex.value = 0
    await nextTick()
    inputRef.value?.focus()
  },
)

watch(query, () => {
  selectedIndex.value = 0
})

function close() {
  emit('update:modelValue', false)
}

function move(step: number) {
  const total = flatItems.value.length
  if (!total) return
  selectedIndex.value = (selectedIndex.value + step + total) % total
  nextTick(() => {
    const selected = listRef.value?.querySelector('.cmd-item.selected')
    selected?.scrollIntoView({ block: 'nearest' })
  })
}

function focusItem(item: CommandItem) {
  const index = flatItems.value.findIndex((entry) => entry.id === item.id)
  if (index >= 0) selectedIndex.value = index
}

function chooseById(id: string) {
  const item = props.items.find((entry) => entry.id === id)
  if (item) chooseByIdInternal(item)
}

function chooseByIdInternal(item: CommandItem) {
  emit('select', item)
  close()
}

function choose(index: number) {
  const item = flatItems.value[index]
  if (item) chooseByIdInternal(item)
}
</script>
