<template><ResourceView :config="config" /></template>
<script setup lang="ts">
import { onMounted, reactive, watchEffect } from 'vue'
import { api } from '../api'
import ResourceView from '../components/ResourceView.vue'
import { useAccountDirectory } from '../composables/useAccountDirectory'
import { groupNumberText, groupTitle } from '../groupDisplay'

const directory = useAccountDirectory<any>(async (accountId, page, keyword) => (await api.get('/groups', { params: { account_id: accountId, page, keyword, page_size: 50 } })).data)
function groupField() {
  return { key:'qq_group', label:'目标 QQ 群', type:'select', required:true, options:[], placeholder:'请先选择发送账号，再选择群聊', remoteMethod:(query: string) => directory.load(directory.accountId.value, query), loadMore:directory.more }
}
const config = reactive<any>({
  kicker:'DELIVERY ROUTING',title:'推送规则',description:'配置仓库更新消息由哪个 QQ 账号发送至哪个群。官方机器人请先在群里 @ 机器人一次完成建档，再在这里下拉选择目标群聊；没有可选群聊时，请先到「群聊管理」确认映射 ID。',endpoint:'/github/push-rules',itemName:'推送规则',nameKey:'repo_full_name',paged:false,actionWidth:90,
  emptyText:'尚未配置推送规则',
  emptyHint:'先添加一条规则，选择监控仓库、发送账号和目标群聊；群聊必须先由机器人在群内完成建档。',
  columns:[{key:'repo_full_name',label:'GitHub 仓库',width:170},{key:'account_name',label:'发送账号',width:140},{key:'qq_group',label:'目标 QQ 群',width:180,format:(_value: any,row: any)=>groupNumberText({display_number:row.qq_group_display,group_number:row.qq_group})},{key:'only_stable',label:'仅正式版',type:'bool',width:95},{key:'ai_summary',label:'AI 摘要',type:'bool',width:85},{key:'markdown_card',label:'卡片',type:'bool',width:80},{key:'total_pushed',label:'已推送',width:80},{key:'enabled',label:'规则状态',type:'bool',width:95}],
  createLabel:'新增规则',
  createFields:[
    {key:'repository_id',label:'监控仓库',type:'select',required:true,options:[]},
    {key:'account_id',label:'发送 QQ 账号',type:'select',required:true,options:[],onChange:(v:number, form:any)=>loadGroupOptions(v, form)},
    groupField(),
    {key:'only_stable',label:'仅正式版本',type:'switch',default:true},
    {key:'include_changelog',label:'附带更新日志',type:'switch',default:true},
    {key:'include_downloads',label:'附带下载地址',type:'switch',default:true},
    {key:'ai_summary',label:'启用 AI 摘要',type:'switch',default:true},
    {key:'markdown_card',label:'Markdown 卡片',type:'switch',default:true},
    {key:'enabled',label:'启用此规则',type:'switch',default:true},
    {key:'template',label:'消息模板（可选）',type:'textarea',placeholder:'支持 {repo_name}、{version}、{changelog}、{release_url}、{downloads} 等字段'}],
  editFields:[
    {key:'account_id',label:'发送 QQ 账号',type:'select',options:[],onChange:(v:number, form:any)=>loadGroupOptions(v, form)},
    groupField(),
    {key:'only_stable',label:'仅正式版本',type:'switch'},
    {key:'include_changelog',label:'附带更新日志',type:'switch'},
    {key:'include_downloads',label:'附带下载地址',type:'switch'},
    {key:'ai_summary',label:'启用 AI 摘要',type:'switch'},
    {key:'markdown_card',label:'Markdown 卡片',type:'switch'},
    {key:'enabled',label:'启用此规则',type:'switch'},
    {key:'template',label:'消息模板',type:'textarea'}],
  deletePath:'/github/push-rules',
  onDialogOpen: (editing: boolean, row: any) => { loadGroupOptions(editing ? row?.account_id : undefined) },
})

async function loadGroupOptions(accountId?: number, form?: Record<string, any>) {
  if (form) form.qq_group = null
  await directory.load(accountId ? Number(accountId) : null)
}

watchEffect(() => {
  for (const fields of [config.createFields, config.editFields]) {
    const field = fields.find((item: any) => item.key === 'qq_group')
    field.options = directory.items.value.map(group => ({ value:group.group_number, label:`${groupTitle(group)} · ${groupNumberText(group)}` }))
    field.loading = directory.loading.value
    field.disabled = !directory.accountId.value
    field.hasMore = directory.items.value.length < directory.total.value
    field.error = directory.error.value
  }
})

onMounted(async () => {
  try {
    const [repos, accounts] = await Promise.all([api.get('/github/repos'), api.get('/accounts')])
    config.createFields[0].options = repos.data.map((r: any) => ({ value: r.id, label: r.full_name }))
    const accountOpts = accounts.data.map((a: any) => ({ value: a.id, label: `${a.name} · ${a.qq_number || a.app_id || '未登录'}` }))
    config.createFields[1].options = accountOpts
    config.editFields[0].options = accountOpts
  } catch {}
})
</script>
