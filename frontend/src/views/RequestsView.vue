<template>
  <div class="page-heading">
    <div><div class="eyebrow">REQUEST REVIEW</div><h1>申请审核</h1><p>查看历史申请与处理结果；审批操作按机器人实际开放的接口能力提供</p></div>
    <el-button :icon="Refresh" @click="load()">刷新</el-button>
  </div>
  <section class="surface resource-surface">
    <div class="resource-toolbar">
      <div class="filter-row">
        <el-select v-model="accountId" clearable placeholder="所有账号" @change="load(1)"><el-option v-for="item in accounts" :key="item.id" :label="`${item.name} · ${item.qq_number || '未知QQ'}`" :value="item.id" /></el-select>
        <el-select v-model="requestType" clearable placeholder="所有申请类型" @change="load(1)"><el-option label="加群申请 / 邀请" value="group"/><el-option label="好友申请" value="friend"/></el-select>
        <el-select v-model="status" placeholder="审核状态" @change="load(1)"><el-option label="待审核" value="pending"/><el-option label="已通过" value="approved"/><el-option label="已拒绝" value="rejected"/><el-option label="全部" value=""/></el-select>
        <el-button :icon="Search" @click="load(1)">查询</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column label="类型" width="125"><template #default="s"><el-tag :type="s.row.request_type === 'group' ? 'warning' : 'info'" effect="dark">{{ s.row.request_type === 'group' ? (s.row.sub_type === 'invite' ? '邀请入群' : '加群申请') : '好友申请' }}</el-tag></template></el-table-column>
      <el-table-column prop="user_id" label="申请人 QQ" width="130"/>
      <el-table-column prop="group_id" label="目标群号" width="130"><template #default="s">{{ s.row.group_id || '—' }}</template></el-table-column>
      <el-table-column prop="account_name" label="接收账号" width="150"/>
      <el-table-column prop="comment" label="验证信息" min-width="210" show-overflow-tooltip><template #default="s">{{ s.row.comment || '（未填写）' }}</template></el-table-column>
      <el-table-column prop="created_at" label="收到时间" width="175"><template #default="s">{{ formatDate(s.row.created_at) }}</template></el-table-column>
      <el-table-column label="状态" width="100"><template #default="s"><el-tag :type="statusType(s.row.status)">{{ statusLabel(s.row.status) }}</el-tag></template></el-table-column>
      <el-table-column prop="decision_reason" label="审核备注" min-width="150" show-overflow-tooltip/>
      <el-table-column label="操作" width="155" fixed="right"><template #default="s"><template v-if="s.row.status === 'pending'"><el-button link type="success" :disabled="!canManage || !supportsDecision(s.row)" @click="decide(s.row,true)">通过</el-button><el-button link type="danger" :disabled="!canManage || !supportsDecision(s.row)" @click="decide(s.row,false)">拒绝</el-button></template><span v-else>{{ s.row.handled_by || '—' }}</span></template></el-table-column>
    </el-table>
    <div class="pagination-wrap"><span>共 {{ total }} 条申请</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50]" layout="sizes,prev,pager,next" @current-change="load" @size-change="load(1)"/></div>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'
const rows=ref<any[]>([]), accounts=ref<any[]>([]), loading=ref(false), page=ref(1), pageSize=ref(20), total=ref(0), accountId=ref<number>(), requestType=ref(''), status=ref('pending'), userPermissions=ref<string[]>([])
const canManage=computed(()=>userPermissions.value.includes('*')||userPermissions.value.includes('request:manage'))
const supportsDecision=(row:any)=>accounts.value.find(a=>a.id===row.account_id)?.capabilities?.[row.request_type==='group'?'set_group_add_request':'set_friend_add_request']===true
async function load(p?:number){if(p)page.value=p;loading.value=true;try{const {data}=await api.get('/requests',{params:{page:page.value,page_size:pageSize.value,account_id:accountId.value,request_type:requestType.value||undefined,status:status.value||undefined}});rows.value=data.items||[];total.value=data.total||0}finally{loading.value=false}}
async function decide(row:any,approve:boolean){let reason='';let remark='';try{const {value}=await ElMessageBox.prompt(approve?'可填写审核备注':'请填写拒绝原因（可选）',approve?'通过申请':'拒绝申请',{inputType:'textarea',inputValue:'',confirmButtonText:approve?'确认通过':'确认拒绝',cancelButtonText:'取消',type:approve?'':'warning'});reason=value||'';remark=reason}catch{return}try{const {data}=await api.post(`/requests/${row.id}/decision`,{approve,reason,remark});Object.assign(row,data);ElMessage.success(approve?'申请已通过':'申请已拒绝')}catch{}}
function formatDate(v:string){return v?new Date(v).toLocaleString('zh-CN'):'—'}
function statusLabel(v:string){return ({pending:'待审核',approved:'已通过',rejected:'已拒绝'} as any)[v]||v}
function statusType(v:string){return ({pending:'warning',approved:'success',rejected:'danger'} as any)[v]||'info'}
onMounted(async()=>{const [a,u]=await Promise.all([api.get('/accounts'),api.get('/auth/me')]);accounts.value=a.data;userPermissions.value=u.data.permissions||[];await load()})
</script>
<style scoped>.resource-surface{padding:0;overflow:hidden}.resource-toolbar{padding:14px 16px;border-bottom:1px solid #273141}.filter-row{display:flex;gap:9px;flex-wrap:wrap}.filter-row .el-select{width:190px}.pagination-wrap{display:flex;align-items:center;justify-content:space-between;padding:14px 17px;color:#8390a4;font-size:11px}@media(max-width:700px){.filter-row .el-select{width:100%}.pagination-wrap{flex-wrap:wrap;gap:10px}}</style>
