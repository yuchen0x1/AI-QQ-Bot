<template><div class="page-heading"><div><div class="eyebrow">PLATFORM CONFIGURATION</div><h1>系统设置</h1><p>账号安全、系统配置、用户权限与审计记录</p></div></div>
  <div class="settings-grid">
    <section class="surface settings-panel">
      <div class="surface-head"><div><h3>数据与生命周期</h3><p>历史消息、日志与运行数据归档</p></div></div>
      <el-form label-position="top">
        <el-form-item label="数据保留周期（天）" extra="超过该天数的消息、系统日志和任务记录将被自动清理；设为 0 表示永久保留。">
          <div style="display:flex;gap:12px;width:100%">
            <el-input-number v-model="retentionDays" :min="0" :max="365" style="width:180px"/>
            <el-button type="primary" :loading="savingRetention" @click="saveRetention">保存设置</el-button>
          </div>
        </el-form-item>
      </el-form>
      <el-alert class="security-note" title="系统每日凌晨自动执行归档清理，也可在「定时任务」中手动触发一次 clean_expired_data 任务。" type="info" :closable="false" show-icon/>
    </section>
    <section class="surface settings-panel">
      <div class="surface-head"><div><h3>告警通知</h3><p>系统严重错误第三方推送</p></div></div>
      <el-form label-position="top">
        <el-form-item label="通道类型">
          <el-select v-model="alertChannelType" style="width:100%">
            <el-option label="自动检测 (根据 Webhook URL)" value="auto"/>
            <el-option label="飞书 (Feishu/Lark)" value="feishu"/>
            <el-option label="钉钉 (DingTalk)" value="dingtalk"/>
            <el-option label="企业微信 (WeCom)" value="wechat"/>
            <el-option label="通用 Webhook (JSON)" value="custom"/>
          </el-select>
        </el-form-item>
        <el-form-item label="Webhook URL" extra="支持飞书/钉钉/企业微信群机器人 Webhook 地址">
          <el-input v-model="alertWebhookUrl" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."/>
        </el-form-item>
        <div style="display:flex;gap:10px">
          <el-button type="primary" :loading="savingAlert" @click="saveAlertConfig">保存配置</el-button>
          <el-button :loading="testingAlert" @click="testAlertWebhook">测试推送</el-button>
        </div>
      </el-form>
      <el-alert class="security-note" title="当机器人离线、关键接口异常时，系统将自动抑制高频刷屏并在 10 秒内推送到群。" type="info" :closable="false" show-icon/>
    </section>
    <section class="surface settings-panel"><div class="surface-head"><div><h3>安全设置</h3><p>保护管理后台凭据</p></div></div><el-form ref="passwordRef" :model="password" :rules="passwordRules" label-position="top"><el-form-item label="当前密码" prop="old_password"><el-input v-model="password.old_password" type="password" show-password autocomplete="current-password"/></el-form-item><el-form-item label="新密码" prop="new_password"><el-input v-model="password.new_password" type="password" show-password autocomplete="new-password"/></el-form-item><el-form-item label="确认新密码" prop="confirm"><el-input v-model="password.confirm" type="password" show-password autocomplete="new-password"/></el-form-item><el-button type="primary" :loading="passwordLoading" @click="changePassword">修改密码</el-button></el-form><el-alert class="security-note" title="API Key、OneBot Token 等敏感配置仅加密存储，查询接口不会返回完整密钥。" type="info" :closable="false" show-icon/></section>
  <section class="surface settings-panel users-panel"><div class="surface-head"><div><h3>后台用户</h3><p>RBAC 角色与访问权限</p></div><el-button type="primary" :icon="Plus" @click="userDialog=true">添加用户</el-button></div><el-table :data="users" v-loading="userLoading" stripe><el-table-column prop="username" label="用户名" min-width="120"/><el-table-column prop="display_name" label="显示名称" min-width="120"/><el-table-column label="角色" width="115"><template #default="s">{{s.row.role?.name||'—'}}</template></el-table-column><el-table-column prop="is_active" label="状态" width="85"><template #default="s"><el-tag :type="s.row.is_active?'success':'info'" effect="dark">{{s.row.is_active?'启用':'停用'}}</el-tag></template></el-table-column><el-table-column prop="last_login_at" label="最近登录" width="165"><template #default="s">{{formatDate(s.row.last_login_at)}}</template></el-table-column><el-table-column label="操作" width="110"><template #default="s"><el-button link type="primary" @click="toggleUser(s.row)">{{s.row.is_active?'停用':'启用'}}</el-button></template></el-table-column></el-table></section>
  <section class="surface settings-panel audit-panel"><div class="surface-head"><div><h3>操作审计</h3><p>记录后台用户的关键操作</p></div><el-button text :icon="Refresh" @click="loadAudit">刷新</el-button></div><el-table :data="audits" v-loading="auditLoading" stripe><el-table-column prop="created_at" label="时间" width="165"><template #default="s">{{formatDate(s.row.created_at)}}</template></el-table-column><el-table-column prop="username" label="用户" width="120"/><el-table-column prop="action" label="操作" width="180"/><el-table-column prop="target" label="目标" width="170"/><el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip/><el-table-column prop="ip" label="来源 IP" width="130"/></el-table><div class="pagination-wrap"><span>共 {{auditTotal}} 条</span><el-pagination v-model:current-page="auditPage" :page-size="20" :total="auditTotal" layout="prev,pager,next" @current-change="loadAudit"/></div></section></div>
  <el-dialog v-model="userDialog" title="添加后台用户" width="min(480px,calc(100vw - 28px))"><el-form ref="userRef" :model="newUser" :rules="userRules" label-position="top"><el-form-item label="用户名" prop="username"><el-input v-model="newUser.username" autocomplete="off"/></el-form-item><el-form-item label="初始密码" prop="password"><el-input v-model="newUser.password" type="password" show-password autocomplete="new-password"/></el-form-item><el-form-item label="显示名称"><el-input v-model="newUser.display_name"/></el-form-item><el-form-item label="邮箱"><el-input v-model="newUser.email"/></el-form-item><el-form-item label="角色" prop="role_id"><el-select v-model="newUser.role_id" style="width:100%"><el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id"/></el-select></el-form-item></el-form><template #footer><el-button @click="userDialog=false">取消</el-button><el-button type="primary" :loading="userSaving" @click="createUser">创建</el-button></template></el-dialog>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { api } from '../api'
const passwordRef=ref(),passwordLoading=ref(false),password=reactive({old_password:'',new_password:'',confirm:''}),passwordRules={old_password:[{required:true,message:'请输入当前密码',trigger:'blur'}],new_password:[{required:true,min:8,message:'新密码至少 8 位',trigger:'blur'}],confirm:[{validator:(_:any,v:string,cb:any)=>v===password.new_password?cb():cb(new Error('两次密码不一致')),trigger:'blur'}]}
const retentionDays=ref(30),savingRetention=ref(false)
const alertWebhookUrl=ref(''),alertChannelType=ref('auto'),savingAlert=ref(false),testingAlert=ref(false)
const users=ref<any[]>([]),roles=ref<any[]>([]),audits=ref<any[]>([]),userLoading=ref(false),auditLoading=ref(false),userSaving=ref(false),userDialog=ref(false),userRef=ref(),auditPage=ref(1),auditTotal=ref(0),newUser=reactive<any>({username:'',password:'',display_name:'',email:'',role_id:null})
const userRules={username:[{required:true,min:3,message:'用户名至少 3 位',trigger:'blur'}],password:[{required:true,min:8,message:'密码至少 8 位',trigger:'blur'}],role_id:[{required:true,message:'请选择角色',trigger:'change'}]}
async function loadRetention(){try{const {data}=await api.get('/system/settings');const found=data.find((x:any)=>x.key==='data_retention_days');if(found&&found.value!==undefined)retentionDays.value=Number(found.value);const urlFound=data.find((x:any)=>x.key==='alert_webhook_url');if(urlFound&&urlFound.value!==undefined)alertWebhookUrl.value=String(urlFound.value);const typeFound=data.find((x:any)=>x.key==='alert_channel_type');if(typeFound&&typeFound.value!==undefined)alertChannelType.value=String(typeFound.value)}catch{}}
async function saveRetention(){savingRetention.value=true;try{await api.put('/system/settings/data_retention_days',{value:retentionDays.value});ElMessage.success('数据生命周期保留配置已更新')}catch(err:any){ElMessage.error(err.response?.data?.detail||'保存失败')}finally{savingRetention.value=false}}
async function saveAlertConfig(){savingAlert.value=true;try{await Promise.all([api.put('/system/settings/alert_webhook_url',{value:alertWebhookUrl.value.trim()}),api.put('/system/settings/alert_channel_type',{value:alertChannelType.value})]);ElMessage.success('告警通道配置已保存')}catch(err:any){ElMessage.error(err.response?.data?.detail||'保存告警配置失败')}finally{savingAlert.value=false}}
async function testAlertWebhook(){if(!alertWebhookUrl.value.trim()){ElMessage.warning('请先填写 Webhook URL');return}testingAlert.value=true;try{const {data}=await api.post('/system/alert/test',{webhook_url:alertWebhookUrl.value.trim(),channel_type:alertChannelType.value});if(data.ok)ElMessage.success('测试告警推送成功，请在对应应用中查收！');else ElMessage.error(data.message||'推送失败')}catch(err:any){ElMessage.error(err.response?.data?.detail||'测试推送失败')}finally{testingAlert.value=false}}
async function changePassword(){await passwordRef.value?.validate(async(valid:boolean)=>{if(!valid)return;passwordLoading.value=true;try{const {data}=await api.post('/auth/password',{old_password:password.old_password,new_password:password.new_password});ElMessage.success(data.detail||'密码已修改');Object.assign(password,{old_password:'',new_password:'',confirm:''})}finally{passwordLoading.value=false}})}
async function loadUsers(){userLoading.value=true;try{const [u,r]=await Promise.all([api.get('/users',{params:{page:1,page_size:100}}),api.get('/roles')]);users.value=u.data.items||[];roles.value=r.data}catch{ }finally{userLoading.value=false}}
async function loadAudit(){auditLoading.value=true;try{const {data}=await api.get('/audit-logs',{params:{page:auditPage.value,page_size:20}});audits.value=data.items||[];auditTotal.value=data.total||0}finally{auditLoading.value=false}}
async function createUser(){await userRef.value?.validate(async(valid:boolean)=>{if(!valid)return;userSaving.value=true;try{const {data}=await api.post('/users',newUser);ElMessage.success(`用户 ${data.username} 已创建`);userDialog.value=false;Object.assign(newUser,{username:'',password:'',display_name:'',email:'',role_id:null});await loadUsers()}finally{userSaving.value=false}})}
async function toggleUser(u:any){try{const {data}=await api.put(`/users/${u.id}`,{is_active:!u.is_active});ElMessage.success(data.username+' 已更新');await loadUsers()}catch{}}
function formatDate(v:string){return v?new Date(v).toLocaleString('zh-CN'):'—'}
onMounted(()=>{loadUsers();loadAudit();loadRetention()})
</script>
<style scoped>.settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.settings-panel{padding:18px}.settings-panel .el-form{max-width:500px}.security-note{margin-top:18px}.users-panel{min-width:0;overflow:auto}.audit-panel{grid-column:1/-1;min-width:0;overflow:auto}.pagination-wrap{display:flex;justify-content:space-between;align-items:center;padding-top:12px;color:#8390a4;font-size:10px}@media(max-width:950px){.settings-grid{grid-template-columns:1fr}.audit-panel{grid-column:auto}}</style>
