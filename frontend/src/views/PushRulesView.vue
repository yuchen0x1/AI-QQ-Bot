<template><ResourceView :config="config" /></template>
<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { api } from '../api'
import ResourceView from '../components/ResourceView.vue'

// 「目标群聊」按所选账号联动下拉：官方机器人只有平台映射 ID、没有真实群号，
// 手填群号几乎必错，所以改成选账号 → 自动拉取该账号已建档群聊 → 下拉直接选。
const config = reactive<any>({
  kicker:'DELIVERY ROUTING',title:'推送规则',description:'配置仓库更新消息应由哪个 QQ 账号发送至哪个群。官方机器人请先在群里 @ 机器人一次完成建档，再在这里下拉选择目标群聊',endpoint:'/github/push-rules',itemName:'推送规则',nameKey:'repo_full_name',paged:false,actionWidth:90,
  columns:[{key:'repo_full_name',label:'GitHub 仓库',width:170},{key:'account_name',label:'发送账号',width:140},{key:'qq_group_display',label:'目标 QQ 群',width:170},{key:'only_stable',label:'仅正式版',type:'bool',width:95},{key:'ai_summary',label:'AI 摘要',type:'bool',width:85},{key:'total_pushed',label:'已推送',width:80},{key:'enabled',label:'规则状态',type:'bool',width:95}],
  createLabel:'新增规则',
  createFields:[
    {key:'repository_id',label:'监控仓库',type:'select',required:true,options:[]},
    {key:'account_id',label:'发送 QQ 账号',type:'select',required:true,options:[],onChange:(v:number)=>loadGroupOptions(v)},
    {key:'qq_group_display',label:'目标 QQ 群',type:'select',required:true,options:[],placeholder:'请先选择发送账号，再选择群聊'},
    {key:'only_stable',label:'仅正式版本',type:'switch',default:true},
    {key:'include_changelog',label:'附带更新日志',type:'switch',default:true},
    {key:'include_downloads',label:'附带下载地址',type:'switch',default:true},
    {key:'ai_summary',label:'启用 AI 摘要',type:'switch',default:true},
    {key:'enabled',label:'启用此规则',type:'switch',default:true},
    {key:'template',label:'消息模板（可选）',type:'textarea',placeholder:'支持 {repo_name}、{version}、{changelog}、{release_url}、{downloads} 等字段'}],
  editFields:[
    {key:'account_id',label:'发送 QQ 账号',type:'select',options:[],onChange:(v:number)=>loadGroupOptions(v)},
    {key:'qq_group_display',label:'目标 QQ 群',type:'select',options:[],placeholder:'请先选择发送账号，再选择群聊'},
    {key:'only_stable',label:'仅正式版本',type:'switch'},
    {key:'include_changelog',label:'附带更新日志',type:'switch'},
    {key:'include_downloads',label:'附带下载地址',type:'switch'},
    {key:'ai_summary',label:'启用 AI 摘要',type:'switch'},
    {key:'enabled',label:'启用此规则',type:'switch'},
    {key:'template',label:'消息模板',type:'textarea'}],
  deletePath:'/github/push-rules',
  onDialogOpen: (editing: boolean, row: any) => { loadGroupOptions(editing ? row?.account_id : undefined) },
})

function groupLabel(g: any) { return `${g.display_name || '未标注群号'}（${g.display_number || '群号待标注'}）` }

async function loadGroupOptions(accountId?: number) {
  const createField = config.createFields.find((f: any) => f.key === 'qq_group')
  const editField = config.editFields.find((f: any) => f.key === 'qq_group')
  try {
    if (!accountId) { createField.options = []; editField.options = []; return }
    const { data } = await api.get('/groups', { params: { account_id: accountId, page: 1, page_size: 200 } })
    const opts = (data.items || []).map((g: any) => ({ value: g.group_number, label: groupLabel(g) }))
    createField.options = opts
    editField.options = opts
  } catch {
    createField.options = []
    editField.options = []
  }
}

onMounted(async () => {
  try {
    const [repos, accounts] = await Promise.all([api.get('/github/repos'), api.get('/accounts')])
    config.createFields[0].options = repos.data.map((r: any) => ({ value: r.id, label: r.full_name }))
    const accountOpts = accounts.data.map((a: any) => ({ value: a.id, label: `${a.name} · ${a.qq_number || a.app_id || '未登录'}` }))
    config.createFields[1].options = accountOpts
    config.editFields[0].options = accountOpts
    // 列表列：把所有账号已建档群聊映射成「群名（ID）」展示，无需用户认识映射群号
    const all: any[] = []
    for (const a of accounts.data) {
      try { const { data } = await api.get('/groups', { params: { account_id: a.id, page: 1, page_size: 200 } }); all.push(...(data.items || [])) } catch {}
    }
    const col = config.columns.find((c: any) => c.key === 'qq_group_display')
    if (col) col.options = all.map((g: any) => ({ value: g.display_number, label: groupLabel(g) }))
  } catch {}
})
</script>
