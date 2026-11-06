<template><div class="page-heading"><div><div class="eyebrow">MESSAGE CENTER <span class="realtime-badge"><i :class="`socket-led ${realtime.state.value}`"></i>{{ realtime.state.value === 'open' ? 'LIVE' : '离线' }}</span></div><h1>消息管理</h1><p>选择账号和群聊即可查看与发送消息，无需手动输入群号</p></div><div class="heading-actions"><el-button v-if="realtime.state.value !== 'open'" text type="primary" @click="realtime.reconnect">重新连接</el-button><el-button type="primary" :icon="Position" @click="openSend">发送消息</el-button></div></div>
  <section class="surface resource-surface"><div class="message-workspace"><aside class="message-panel account-panel"><div class="panel-title"><b>账号</b><small>{{ accounts.length }} 个</small></div><button class="message-nav-item" :class="{ active: !filters.account_id }" type="button" @click="selectAccount(null)"><span class="nav-avatar all">ALL</span><span class="nav-copy"><b>全部账号</b><small>所有消息</small></span></button><button v-for="a in accounts" :key="a.id" class="message-nav-item" :class="{ active: filters.account_id === a.id }" type="button" @click="selectAccount(a.id)"><span class="nav-avatar">{{ (a.name || 'Q').slice(0, 1).toUpperCase() }}</span><span class="nav-copy"><b>{{ a.name }}</b><small>{{ accountStatus(a.id) }}</small></span><i :class="['status-led', accountStatus(a.id) === '在线' ? 'online' : 'offline']"></i></button></aside><aside class="message-panel group-panel"><div class="panel-title"><b>会话</b><small>{{ filters.account_id ? accountGroups.length : '—' }}</small></div><button class="message-nav-item" :class="{ active: !filters.qq_group }" type="button" @click="selectGroup(null)"><span class="nav-avatar all">#</span><span class="nav-copy"><b>全部群聊</b><small>账号消息</small></span></button><button v-for="g in accountGroups" :key="g.id" class="message-nav-item" :class="{ active: filters.qq_group === g.group_number }" type="button" @click="selectGroup(g.group_number)"><span class="nav-avatar group">#</span><span class="nav-copy"><b>{{ g.name || '未命名群' }}</b><small>{{ g.group_number }} · {{ g.member_count || 0 }} 人</small></span></button><div v-if="!filters.account_id" class="panel-empty">选择左侧账号查看群聊</div><div v-else-if="groupsLoading" class="panel-empty">正在加载群聊…</div><div v-else-if="!accountGroups.length" class="panel-empty">暂无群聊数据</div></aside><main class="message-panel message-thread"><div class="resource-toolbar"><div class="filter-row">
    <el-select v-model="filters.account_id" clearable placeholder="全部账号" class="w-account" @change="onAccountChange"><el-option v-for="a in accounts" :key="a.id" :label="`${a.name}${a.qq_number ? ' · ' + a.qq_number : ''}`" :value="a.id"/></el-select>
    <el-select v-model="filters.qq_group" clearable filterable placeholder="全部群聊" class="w-group" :disabled="!filters.account_id" :loading="groupsLoading" @change="load(1)"><el-option v-for="g in accountGroups" :key="g.id" :label="`${g.name || '未命名群'} · ${g.group_number}`" :value="g.group_number"/></el-select>
    <el-select v-model="filters.direction" clearable placeholder="消息方向" class="w-dir" @change="load(1)"><el-option label="收到" value="in"/><el-option label="发出" value="out"/></el-select>
    <el-input v-model="keyword" clearable placeholder="搜索消息内容" :prefix-icon="Search" @keyup.enter="load(1)" @clear="load(1)"/>
    <el-button :icon="Search" @click="load(1)">查询</el-button></div>
    <div style="display:flex;align-items:center;gap:10px">
      <el-radio-group v-model="viewMode" size="small">
        <el-radio-button value="table">表格模式</el-radio-button>
        <el-radio-button value="chat">会话气泡</el-radio-button>
      </el-radio-group>
      <el-button text :icon="Refresh" @click="load()">刷新</el-button>
    </div>
  </div>
  <el-alert v-if="filters.account_id && !groupsLoading && accountGroups.length===0" type="info" :closable="false" show-icon title="该账号还没有群聊数据" description="请先在「群聊管理」点击「同步群列表」从协议端拉取群信息；或检查账号是否已成功连接。"/><div v-if="realtime.lastMessage.value" class="message-live-hint"><i class="socket-led open"></i> 账号实时状态：{{ realtime.lastMessage.value.online ?? 0 }} 个在线 · 今日消息 {{ realtime.lastMessage.value.messages_today ?? 0 }} 条</div>
  
  <!-- 表格视图 -->
  <el-table v-if="viewMode === 'table'" v-loading="loading" :data="rows" stripe>
    <el-table-column prop="created_at" label="时间" width="165"><template #default="s">{{ formatDate(s.row.created_at) }}</template></el-table-column>
    <el-table-column label="账号" width="130"><template #default="s">{{ accountLabel(s.row.account_id) }}</template></el-table-column>
    <el-table-column prop="qq_group" label="群聊 / 私聊" width="150"><template #default="s">{{ s.row.qq_group ? (groupLabel(s.row.qq_group)) : '私聊' }}</template></el-table-column>
    <el-table-column prop="direction" label="方向" width="85"><template #default="s"><el-tag :type="s.row.direction==='in'?'info':'success'" effect="dark">{{ s.row.direction==='in'?'收到':'发出' }}</el-tag></template></el-table-column>
    <el-table-column prop="sender_name" label="发送者" width="130"/>
    <el-table-column prop="content" label="消息内容" min-width="280" show-overflow-tooltip/>
    <el-table-column prop="blocked" label="拦截" width="85"><template #default="s"><el-tag v-if="s.row.blocked" type="danger" effect="dark">已拦截</el-tag><span v-else>—</span></template></el-table-column>
  </el-table>

  <!-- 真实会话气泡流视图 -->
  <div v-else class="chat-feed-view" v-loading="loading">
    <div v-if="!rows.length" class="panel-empty" style="text-align:center;padding:40px 0">暂无消息记录</div>
    <div v-for="item in rows" :key="item.id" class="feed-item" :class="item.direction">
      <div class="feed-avatar">
        {{ (item.sender_name || (item.direction === 'out' ? 'BOT' : 'QQ')).slice(0, 1).toUpperCase() }}
      </div>
      <div class="feed-bubble-wrap">
        <div class="feed-header">
          <span class="feed-author">{{ item.sender_name || (item.direction === 'out' ? '机器人回复' : '用户') }}</span>
          <span class="feed-target">{{ item.qq_group ? groupLabel(item.qq_group) : '私聊' }}</span>
          <span class="feed-time">{{ formatDate(item.created_at) }}</span>
          <el-tag v-if="item.blocked" size="small" type="danger" effect="dark">已拦截</el-tag>
        </div>
        <div class="feed-content" :class="{ blocked: item.blocked }">
          {{ item.content }}
        </div>
      </div>
    </div>
  </div><div class="pagination-wrap"><span>共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50]" layout="sizes,prev,pager,next" @current-change="load" @size-change="load(1)"/></div></main></div></section>
  <el-dialog v-model="sendDialog" title="发送消息" width="min(520px,calc(100vw - 28px))"><el-form ref="formRef" :model="form" :rules="rules" label-position="top"><el-form-item label="发送账号" prop="account_id"><el-select v-model="form.account_id" placeholder="选择 QQ 账号" style="width:100%" @change="onSendAccountChange"><el-option v-for="a in accounts" :key="a.id" :label="`${a.name}${a.qq_number ? ' · ' + a.qq_number : ''}${a.runtime_state==='online' ? ' · 在线' : ' · 离线'}`" :value="a.id"/></el-select></el-form-item><el-form-item label="发送目标" prop="target"><el-radio-group v-model="targetType"><el-radio-button value="group">QQ 群（下拉选择）</el-radio-button><el-radio-button value="private">私聊用户</el-radio-button></el-radio-group></el-form-item><el-form-item v-if="targetType==='group'" label="选择群聊" prop="target"><el-select v-model="form.target" filterable placeholder="先选账号，再选择群聊" :loading="groupsLoading" style="width:100%"><el-option v-for="g in accountGroups" :key="g.id" :label="`${g.name || '未命名群'} · ${g.group_number}`" :value="String(g.group_number)"/></el-select></el-form-item><el-form-item v-else label="用户 QQ 号" prop="target"><el-input v-model="form.target" placeholder="输入对方 QQ 号"/></el-form-item><el-form-item label="消息内容" prop="content"><el-input v-model="form.content" type="textarea" :rows="5" maxlength="4000" show-word-limit placeholder="输入要发送的消息"/></el-form-item></el-form><template #footer><el-button @click="sendDialog=false">取消</el-button><el-button type="primary" :loading="sending" @click="send">发送</el-button></template></el-dialog>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Position, Refresh, Search } from '@element-plus/icons-vue'
import { api, useRealtimeSocket } from '../api'
const realtime = useRealtimeSocket<any>('/ws/status')
const rows=ref<any[]>([]),accounts=ref<any[]>([]),accountGroups=ref<any[]>([]),groupsLoading=ref(false),loading=ref(false),sending=ref(false),sendDialog=ref(false),formRef=ref(),page=ref(1),pageSize=ref(20),total=ref(0),keyword=ref(''),targetType=ref('group')
const viewMode = ref<'table' | 'chat'>('table')
const filters=reactive({account_id:null as number|null,qq_group:null as number|null,direction:''}),form=reactive({account_id:null as number|null,target:'',content:''})
const rules={account_id:[{required:true,message:'请选择账号',trigger:'change'}],target:[{required:true,message:'请选择或输入目标',trigger:'change'}],content:[{required:true,message:'请输入消息内容',trigger:'blur'}]}
function groupMap(){const m=new Map<number,string>();for(const g of accountGroups.value)m.set(g.group_number,g.name||'未命名群');return m}
function groupLabel(num:number){return groupMap().get(num)||`群 ${num}`}
function accountLabel(id:number){const a=accounts.value.find((x:any)=>x.id===id);return a?a.name:`账号 ${id}`}
function accountStatus(id:number){const live = realtime.lastMessage.value?.accounts?.find((x:any) => x.id === id); return live?.state === 'online' ? '在线' : '离线'}
async function selectAccount(id:number|null){filters.account_id=id;filters.qq_group=null;await Promise.all([loadGroups(id),load(1)])}
async function selectGroup(group:number|null){filters.qq_group=group;await load(1)}
async function loadGroups(accountId:number|null){accountGroups.value=[];if(!accountId)return;groupsLoading.value=true;try{const {data}=await api.get('/groups',{params:{account_id:accountId,page:1,page_size:200}});accountGroups.value=data.items||[]}finally{groupsLoading.value=false}}
async function onAccountChange(){filters.qq_group=null;await Promise.all([loadGroups(filters.account_id),load(1)])}
function onSendAccountChange(){form.target='';loadGroups(form.account_id)}
async function load(p?:number){if(p)page.value=p;loading.value=true;try{const {data}=await api.get('/messages',{params:{page:page.value,page_size:pageSize.value,keyword:keyword.value||undefined,direction:filters.direction||undefined,account_id:filters.account_id||undefined,qq_group:filters.qq_group||undefined}});rows.value=data.items||[];total.value=data.total||0}finally{loading.value=false}}
function openSend(){sendDialog.value=true;if(!form.account_id&&accounts.value.length===1){form.account_id=accounts.value[0].id;loadGroups(form.account_id)}}
async function send(){await formRef.value?.validate(async(valid:boolean)=>{if(!valid)return;sending.value=true;try{const payload:any={account_id:form.account_id,content:form.content};payload[targetType.value==='group'?'qq_group':'user_id']=Number(form.target);const {data}=await api.post('/messages/send',payload);ElMessage.success(data.message||'消息已发送');sendDialog.value=false;form.target='';form.content='';await load(1)}finally{sending.value=false}})}
function formatDate(v:string){return v?new Date(v).toLocaleString('zh-CN'):'—'}
onMounted(async()=>{const [a]=await Promise.all([api.get('/accounts'),load()]);accounts.value=a.data})
</script>
<style scoped>.resource-surface{padding:0;overflow:hidden}.message-workspace{display:grid;grid-template-columns:190px 230px minmax(0,1fr);min-height:490px}.message-panel{min-width:0;background:#101722}.account-panel,.group-panel{border-right:1px solid #273141;padding:12px 8px}.panel-title{display:flex;justify-content:space-between;align-items:center;padding:2px 8px 10px;color:#dbe3ef;font-size:11px}.panel-title small{color:#7e8ba0;font-size:9px}.message-nav-item{display:flex;align-items:center;gap:8px;width:100%;padding:9px 8px;border:0;border-radius:8px;background:transparent;color:#cbd4e2;text-align:left;cursor:pointer}.message-nav-item:hover,.message-nav-item.active{background:#26213d;color:#f3f5fa}.nav-avatar{width:27px;height:27px;display:grid;place-items:center;flex:none;border-radius:8px;background:#263652;color:#8fc6e6;font:11px 'DM Mono',monospace}.nav-avatar.all{background:#332c58;color:#c0b0ff}.nav-avatar.group{background:#203847;color:#8bd4e7}.nav-copy{display:flex;flex-direction:column;gap:3px;overflow:hidden;min-width:0}.nav-copy b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px}.nav-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#7f8ba1;font-size:9px}.message-nav-item.active .nav-copy small{color:#a89cff}.status-led{width:6px;height:6px;border-radius:50%;margin-left:auto;background:#6d788b;flex:none}.status-led.online{background:#4bd4a0;box-shadow:0 0 0 3px #4bd4a020}.panel-empty{padding:20px 8px;color:#77859a;font-size:10px;line-height:1.6}.message-thread{background:#0f151f}.message-thread .resource-toolbar{border-top:0}.message-live-hint{padding:7px 16px;border-bottom:1px solid #273141;background:#111b1b;color:#88d6bc;font-size:10px}.message-live-hint .socket-led{margin-right:4px}.resource-toolbar{padding:14px 16px;display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #273141}.filter-row{display:flex;gap:8px;flex-wrap:wrap}.w-account{width:190px}.w-group{width:230px}.w-dir{width:120px}.filter-row .el-input{width:190px}.pagination-wrap{display:flex;align-items:center;justify-content:space-between;padding:14px 17px;color:#8390a4;font-size:11px}
.chat-feed-view{padding:18px 20px;height:450px;overflow-y:auto;display:flex;flex-direction:column;gap:16px;background:#0d131d}
.feed-item{display:flex;gap:12px;max-width:85%}
.feed-item.out{margin-left:auto;flex-direction:row-reverse}
.feed-avatar{width:32px;height:32px;border-radius:10px;background:#233247;color:#7ec2eb;display:grid;place-items:center;font-size:11px;font-weight:bold;flex:none}
.feed-item.out .feed-avatar{background:#352c5c;color:#bca9ff}
.feed-bubble-wrap{display:flex;flex-direction:column;gap:5px}
.feed-item.out .feed-bubble-wrap{align-items:flex-end}
.feed-header{display:flex;align-items:center;gap:8px;font-size:10px;color:#768498}
.feed-author{font-weight:600;color:#cbd5e3}
.feed-target{background:#1a2332;padding:1px 6px;border-radius:4px;color:#8ca0ba}
.feed-content{background:#182232;border:1px solid #28374d;color:#e1e7f0;padding:10px 14px;border-radius:4px 12px 12px 12px;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-word}
.feed-item.out .feed-content{background:#282245;border-color:#3f356d;border-radius:12px 4px 12px 12px;color:#f0ecfc}
.feed-content.blocked{border-color:#7f2323;background:#311515;color:#fca5a5}
@media(max-width:900px){.message-workspace{grid-template-columns:155px 190px minmax(0,1fr)}}@media(max-width:700px){.message-workspace{display:block}.account-panel,.group-panel{display:flex;overflow:auto;border-right:0;border-bottom:1px solid #273141;padding:8px}.account-panel .panel-title,.group-panel .panel-title,.panel-empty{display:none}.message-nav-item{width:auto;min-width:125px}.message-nav-item .nav-copy small,.message-nav-item .status-led{display:none}.message-thread{min-height:400px}.w-account,.w-group,.w-dir,.filter-row .el-input{width:100%}.pagination-wrap{flex-wrap:wrap;gap:10px}}</style>
