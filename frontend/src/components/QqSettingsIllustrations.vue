<template>
  <section class="qq-illustrations" aria-label="QQ 群机器人设置图解">
    <div class="illustration-heading">
      <div class="heading-copy">
        <span class="heading-kicker"><AppIcon name="eye" :size="13" />SETUP REFERENCE</span>
        <h3>对照手机 QQ 设置</h3>
      </div>
      <span class="heading-hint"><AppIcon name="search" :size="12" />点击图片放大，可切换查看三张原图</span>
    </div>

    <div class="illustration-grid">
      <figure v-for="(item, index) in illustrations" :key="item.title" class="illustration-card">
        <figcaption>
          <span class="illustration-number">{{ index + 1 }}</span>
          <strong>{{ item.title }}</strong>
        </figcaption>
        <button
          class="illustration-preview"
          type="button"
          :aria-label="`放大查看：${item.title}`"
          aria-haspopup="dialog"
          @click="openPreview(index)"
        >
          <img
            :src="item.src"
            :alt="item.alt"
            loading="lazy"
            :style="{ objectPosition: item.position }"
          />
          <span class="zoom-label"><AppIcon name="eye" :size="12" />放大查看</span>
        </button>
        <p>{{ item.caption }}</p>
      </figure>
    </div>

    <div class="illustration-note" role="note">
      <span class="note-mark"><AppIcon name="info" :size="15" /></span>
      <p>接收消息范围与主动发送权限是独立设置。图中管理员等其他选项请按所需功能授权；完成后回后台点击「检查群权限」和「测试主动通知」。截图为界面示例，具体位置和文案以你使用的 QQ 版本为准。</p>
    </div>

    <el-image-viewer
      v-if="previewVisible"
      :url-list="illustrations.map((item) => item.src)"
      :initial-index="previewIndex"
      teleported
      @close="closePreview"
    />
  </section>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import groupSettings from '../assets/help/qq-group-bot-settings.jpg'
import proactivePermission from '../assets/help/qq-proactive-message-permission.jpg'
import messageScope from '../assets/help/qq-group-message-scope.jpg'

const illustrations = [
  {
    src: groupSettings,
    title: '打开群机器人的设置',
    position: 'center 32%',
    alt: 'QQ 群机器人设置页，可看到「机器人主动在群聊内发言」开关和「机器人权限设置」入口',
    caption: '在群内打开机器人的「设置」，确认「机器人主动在群聊内发言」已开启，再点击下方「机器人权限设置」。',
  },
  {
    src: proactivePermission,
    title: '允许主动发送消息',
    position: 'top',
    alt: '机器人权限设置页，「允许主动发送消息」开关处于开启状态',
    caption: '进入「机器人权限设置」，打开「允许主动发送消息」，让仓库更新能在群里主动推送。',
  },
  {
    src: messageScope,
    title: '按需选择接收消息范围',
    position: 'bottom',
    alt: '群聊消息范围选项，包括全部消息、@机器人的最近10条消息和仅@机器人的消息',
    caption: '「机器人可获取的群聊消息范围」决定它接收哪些消息。按需求选择，绑定时仍请 @ 机器人并发送口令；这里的选项与主动发送权限分开设置。',
  },
]

const previewVisible = ref(false), previewIndex = ref(0)
let trigger: HTMLButtonElement | null = null

function openPreview(index: number) {
  trigger = document.activeElement instanceof HTMLButtonElement ? document.activeElement : null
  previewIndex.value = index
  previewVisible.value = true
}

async function closePreview() {
  previewVisible.value = false
  await nextTick()
  trigger?.focus()
}
</script>

<style scoped>
.qq-illustrations {
  min-width: 0;
  margin: 26px 0 0;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}

.illustration-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.heading-copy {
  min-width: 0;
}

.heading-kicker {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 5px;
  color: var(--brand-strong);
  font: 650 8.5px/1.4 var(--font-mono);
  letter-spacing: 0.13em;
}

.illustration-heading h3 {
  margin: 0;
  color: var(--text);
  font-size: 14px;
  font-weight: 630;
  letter-spacing: -0.01em;
}

.heading-hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 7px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9px;
}

.heading-hint .app-icon {
  color: var(--text-4);
}

.illustration-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.illustration-card {
  min-width: 0;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
  box-shadow: var(--shadow-xs);
  transition: border-color var(--duration) var(--ease), box-shadow var(--duration) var(--ease), transform var(--duration) var(--ease);
}

.illustration-card:hover,
.illustration-card:focus-within {
  border-color: var(--line-strong);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.illustration-card figcaption {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-height: 42px;
  margin-bottom: 9px;
}

.illustration-number {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex: none;
  border: 1px solid var(--brand-line);
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font: 650 9px/1 var(--font-mono);
}

.illustration-card strong {
  color: var(--text);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1.6;
}

.illustration-preview {
  position: relative;
  display: block;
  width: 100%;
  aspect-ratio: 16 / 10;
  overflow: hidden;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-inset);
  cursor: zoom-in;
}

.illustration-preview img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform var(--duration-slow) var(--ease);
}

.illustration-preview:hover img {
  transform: scale(1.018);
}

.zoom-label {
  position: absolute;
  right: 8px;
  bottom: 8px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 7px;
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  color: var(--text-2);
  font-size: 9px;
  font-weight: 550;
  backdrop-filter: blur(8px);
}

.illustration-card p {
  margin: 10px 1px 0;
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.8;
}

.illustration-note {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 13px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-inset);
}

.note-mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border: 1px solid var(--info-line);
  border-radius: 7px;
  background: var(--info-soft);
  color: var(--info);
}

.illustration-note p {
  margin: 0;
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1.85;
}

.illustration-preview:focus-visible {
  outline: 2px solid var(--brand-strong);
  outline-offset: 3px;
}

@media (max-width: 1100px) {
  .illustration-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .qq-illustrations {
    margin-top: 22px;
    padding-top: 17px;
  }

  .illustration-grid {
    grid-template-columns: 1fr;
  }

  .illustration-card {
    padding: 11px;
  }

  .illustration-card figcaption {
    min-height: 0;
  }

  .illustration-preview {
    aspect-ratio: 4 / 3;
  }

  .illustration-card p {
    font-size: 10.5px;
  }

  .illustration-note p {
    font-size: 10px;
  }
}
</style>
