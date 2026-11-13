<template>
  <section class="qq-illustrations" aria-label="QQ 群机器人设置图解">
    <div class="illustration-heading"><h3>对照手机 QQ 设置</h3><span>点击图片放大，可切换查看三张原图</span></div>
    <div class="illustration-grid">
      <figure v-for="(item, index) in illustrations" :key="item.title" class="illustration-card">
        <figcaption><span class="illustration-number">{{ index + 1 }}</span><strong>{{ item.title }}</strong></figcaption>
        <button class="illustration-preview" type="button" :aria-label="`放大查看：${item.title}`" @click="openPreview(index)">
          <img :src="item.src" :alt="item.alt" loading="lazy" :style="{ objectPosition: item.position }" />
          <span class="zoom-label">放大查看</span>
        </button>
        <p>{{ item.caption }}</p>
      </figure>
    </div>
    <p class="illustration-note">接收消息范围与主动发送权限是独立设置。图中管理员等其他选项请按所需功能授权；完成后回后台点击「检查群权限」和「测试主动通知」。截图为界面示例，具体位置和文案以你使用的 QQ 版本为准。</p>
    <el-image-viewer v-if="previewVisible" :url-list="illustrations.map(item => item.src)" :initial-index="previewIndex" teleported @close="closePreview" />
  </section>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import groupSettings from '../assets/help/qq-group-bot-settings.jpg'
import proactivePermission from '../assets/help/qq-proactive-message-permission.jpg'
import messageScope from '../assets/help/qq-group-message-scope.jpg'

const illustrations = [
  { src: groupSettings, title: '打开群机器人的设置', position: 'center 32%',
    alt: 'QQ 群机器人设置页，可看到「机器人主动在群聊内发言」开关和「机器人权限设置」入口',
    caption: '在群内打开机器人的「设置」，确认「机器人主动在群聊内发言」已开启，再点击下方「机器人权限设置」。' },
  { src: proactivePermission, title: '允许主动发送消息', position: 'top',
    alt: '机器人权限设置页，「允许主动发送消息」开关处于开启状态',
    caption: '进入「机器人权限设置」，打开「允许主动发送消息」，让仓库更新能在群里主动推送。' },
  { src: messageScope, title: '按需选择接收消息范围', position: 'bottom',
    alt: '群聊消息范围选项，包括全部消息、@机器人的最近10条消息和仅@机器人的消息',
    caption: '「机器人可获取的群聊消息范围」决定它接收哪些消息。按需求选择，绑定时仍请 @ 机器人并发送口令；这里的选项与主动发送权限分开设置。' },
]
const previewVisible = ref(false), previewIndex = ref(0)
let trigger: HTMLButtonElement | null = null
function openPreview(index: number) {
  trigger = document.activeElement instanceof HTMLButtonElement ? document.activeElement : null
  previewIndex.value = index
  previewVisible.value = true
}
async function closePreview() { previewVisible.value = false; await nextTick(); trigger?.focus() }
</script>

<style scoped>
.qq-illustrations{margin:28px 0;padding-top:22px;border-top:1px solid #2c3e57;min-width:0}.illustration-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:16px}.illustration-heading h3{margin:0;color:#e8f1fd;font-size:16px}.illustration-heading span{font-size:12px;color:#9cb4d0}.illustration-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.illustration-card{margin:0;min-width:0;background:#131f31;border:1px solid #32465f;border-radius:10px;padding:12px}.illustration-card figcaption{display:flex;gap:8px;align-items:center;min-height:42px;margin-bottom:10px}.illustration-card strong{color:#dceafb;font-size:13px;line-height:1.6}.illustration-number{flex-shrink:0;display:grid;place-items:center;width:23px;height:23px;border:1px solid #56718e;border-radius:50%;color:#9ae0ea;font-size:12px}.illustration-preview{position:relative;display:block;width:100%;height:230px;overflow:hidden;border:0;border-radius:6px;padding:0;background:#ebedf1;cursor:zoom-in}.illustration-preview img{display:block;width:100%;height:100%;object-fit:cover}.zoom-label{position:absolute;bottom:8px;right:8px;padding:5px 9px;border-radius:5px;background:#11223de8;color:#eef7ff;font-size:12px}.illustration-card p{font-size:12px;line-height:1.85;color:#acbfd8;margin:12px 0 0}.illustration-note{font-size:12px;line-height:1.9;color:#9cb2cc;margin:16px 0 0;max-width:80ch}.illustration-preview:focus-visible{outline:2px solid #96dfec;outline-offset:4px}@media(max-width:700px){.illustration-grid{grid-template-columns:1fr}.illustration-preview{height:250px}.illustration-card figcaption{min-height:0}.illustration-card p{font-size:13px}}
</style>
