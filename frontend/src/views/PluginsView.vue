<template><div class="plugin-workspace"><div class="plugin-overview"><div><div class="eyebrow">EXTENSIONS RUNTIME</div><h2>可组合的机器人能力</h2><p>插件按声明的权限运行，支持热加载与账号 / 群绑定。所有配置均通过后端接口持久化。</p></div><div class="plugin-facts"><span><b>{{ runtimeStats.total }}</b><small>已发现插件</small></span><span><b>{{ runtimeStats.enabled }}</b><small>已启用</small></span><span><b>{{ runtimeStats.loaded }}</b><small>已加载</small></span></div></div><ResourceView ref="resourceRef" :config="config" /></div>
  <el-dialog v-model="metricsDialog" :title="`${selectedPlugin?.name || '插件'} · 运行指标`" width="min(720px, calc(100vw - 28px))">
    <el-skeleton v-if="metricsLoading" :rows="5" animated />
    <template v-else-if="metrics">
      <div class="metrics-grid"><div><strong>{{ metrics.invocations }}</strong><span>调用次数</span></div><div><strong>{{ (metrics.error_rate * 100).toFixed(1) }}%</strong><span>错误率</span></div><div><strong>{{ metrics.avg_duration_ms.toFixed(1) }} ms</strong><span>平均耗时</span></div><div><strong>{{ metrics.permission_denied }}</strong><span>权限拒绝</span></div></div>
      <el-alert v-if="metrics.last_error" type="error" :closable="false" show-icon title="最近一次错误"><template #default>{{ metrics.last_error }} · {{ formatDate(metrics.last_error_at) }}</template></el-alert>
      <el-empty v-if="!metrics.permission_checks?.length" description="暂无权限调用记录" />
      <el-table v-else :data="metrics.permission_checks" stripe max-height="260"><el-table-column prop="time" label="时间" width="180"><template #default="scope">{{ formatDate(scope.row.time) }}</template></el-table-column><el-table-column prop="permission" label="权限" /><el-table-column prop="allowed" label="结果" width="90"><template #default="scope"><el-tag :type="scope.row.allowed ? 'success' : 'danger'" size="small">{{ scope.row.allowed ? '允许' : '拒绝' }}</el-tag></template></el-table-column></el-table>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ResourceView from '../components/ResourceView.vue'
import { api } from '../api'
const resourceRef = ref()
const metricsDialog = ref(false), metricsLoading = ref(false), metrics = ref<any>(null), selectedPlugin = ref<any>(null)
const runtimeStats = computed(() => { const rows = resourceRef.value?.rows || []; return { total: rows.length, enabled: rows.filter((x:any) => x.enabled).length, loaded: rows.filter((x:any) => x.load_status === 'loaded').length } })
async function showMetrics(row:any) { selectedPlugin.value = row; metrics.value = null; metricsDialog.value = true; metricsLoading.value = true; try { const { data } = await api.get(`/plugins/${row.id}/metrics`); metrics.value = data } catch (err:any) { ElMessage.error(err.response?.data?.detail || '指标加载失败') } finally { metricsLoading.value = false } }
function formatDate(v:string|null|undefined) { return v ? new Date(v).toLocaleString('zh-CN') : '—' }
const config={kicker:'EXTENSIONS',title:'插件管理',description:'管理隔离运行的扩展能力，并查看权限声明与账号 / 群绑定',endpoint:'/plugins',itemName:'插件',nameKey:'name',paged:false,actionWidth:220,
  columns:[{key:'name',label:'插件名称',width:165},{key:'plugin_id',label:'插件 ID',width:150},{key:'version',label:'版本',width:85},{key:'author',label:'作者',width:110},{key:'description',label:'说明',width:210},{key:'commands',label:'命令',width:140},{key:'permissions',label:'权限声明',width:175},{key:'binding_count',label:'绑定数',width:80},{key:'load_status',label:'加载状态',type:'status',width:100,options:[{value:'loaded',label:'已加载'},{value:'disabled',label:'已禁用'},{value:'error',label:'错误'}]},{key:'enabled',label:'启用',type:'bool',width:75}],
  createFields:[],editFields:[{key:'enabled',label:'启用插件',type:'switch'},{key:'config',label:'插件配置 JSON',type:'json',rows:6}],
  actions:[{label:'指标',handler:(row:any)=>showMetrics(row),type:'primary'},{label:'重新加载',suffix:'reload',method:'POST',type:'warning'}],secondaryAction:{label:'扫描插件目录',path:'/plugins/sync',method:'POST',success:(d:any)=>`已同步 ${Array.isArray(d)?d.length:0} 个插件`}}
</script>
<style scoped>.plugin-workspace{display:flex;flex-direction:column;gap:14px}.plugin-overview{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border:1px solid #293346;border-radius:12px;background:linear-gradient(110deg,#151b2a,#101722);gap:20px}.plugin-overview h2{margin:0 0 6px;font-size:16px;color:#edf1f8}.plugin-overview p{margin:0;color:#8c99ad;font-size:10px}.plugin-facts{display:flex;gap:10px;flex-shrink:0}.plugin-facts span{min-width:78px;padding:9px 10px;border:1px solid #2a3444;border-radius:8px;background:#121a27;display:flex;flex-direction:column;gap:4px}.plugin-facts b{font-size:11px;color:#bbaeff}.plugin-facts small{font-size:9px;color:#718096}.metrics-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}.metrics-grid>div{padding:14px;border-radius:10px;background:rgba(30,42,68,.45);border:1px solid rgba(85,105,155,.35)}.metrics-grid strong,.metrics-grid span{display:block}.metrics-grid strong{font-size:20px;color:#f1f5ff}.metrics-grid span{margin-top:4px;color:#8c9bb5;font-size:11px}@media(max-width:700px){.plugin-overview{align-items:flex-start;flex-direction:column}.plugin-facts{width:100%}.plugin-facts span{flex:1;min-width:0}.metrics-grid{grid-template-columns:repeat(2,1fr)}} </style>
