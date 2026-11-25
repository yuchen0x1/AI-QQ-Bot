<template><ResourceView :config="config" /></template>
<script setup lang="ts">
import ResourceView from '../components/ResourceView.vue'
import { groupNumberText } from '../groupDisplay'
const config={kicker:'DELIVERY HISTORY',title:'推送记录',description:'查看仓库动态与版本通知的目标、发送内容、状态与重试情况；失败记录可在确认后重新推送。',endpoint:'/github/push-records',itemName:'推送记录',nameKey:'release_tag',keyword:null,
  emptyText:'暂无推送记录',
  emptyHint:'仓库产生新版本或动态后，通知会在这里显示。若长期为空，请检查推送规则与目标群聊配置。',
  filters:[{key:'status',label:'推送状态',options:[{value:'success',label:'成功'},{value:'failed',label:'失败'},{value:'pending',label:'待发送'}]},{key:'qq_group',label:'群号',type:'input',placeholder:'输入群号或映射 ID'}],
  columns:[{key:'created_at',label:'创建时间',type:'date',width:160},{key:'repo_full_name',label:'仓库',width:160},{key:'release_tag',label:'版本 / 动态',width:240},{key:'content',label:'通知内容',width:300},{key:'qq_group',label:'目标 QQ 群',width:180,format:(_value: any,row: any)=>groupNumberText({display_number:row.qq_group_display,group_number:row.qq_group})},{key:'status',label:'状态',type:'status',width:90,options:[{value:'success',label:'成功'},{value:'failed',label:'失败'},{value:'pending',label:'待发送'}]},{key:'retries',label:'重试次数',width:90},{key:'error_category',label:'错误分类',width:120,options:[{value:'timeout',label:'执行超时'},{value:'connection',label:'连接异常'},{value:'authorization',label:'授权异常'},{value:'configuration',label:'配置异常'},{value:'rate_limit',label:'平台限流'},{value:'execution',label:'执行失败'},{value:'cancelled',label:'已取消'}]},{key:'retries_exhausted',label:'重试状态',width:110,format:(value: boolean,row: any)=>value?'已耗尽':row.status==='success'?'—':'未耗尽'},{key:'error',label:'失败原因',width:200},{key:'next_action',label:'处理建议',width:300,overflow:false}],
  actions:[{label:'重新推送',suffix:'retry',method:'POST',type:'warning',confirm:'确定重新发送版本 {name} 的通知吗？',success:(d:any)=>d.message||'处理完成'}],actionWidth:110}
</script>
