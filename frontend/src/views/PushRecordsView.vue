<template><ResourceView :config="config" /></template>
<script setup lang="ts">
import ResourceView from '../components/ResourceView.vue'
const config={kicker:'DELIVERY HISTORY',title:'推送记录',description:'查看每次版本通知的目标、发送内容、状态与重试情况',endpoint:'/github/push-records',itemName:'推送记录',nameKey:'release_tag',keyword:null,
  filters:[{key:'status',label:'推送状态',options:[{value:'success',label:'成功'},{value:'failed',label:'失败'},{value:'pending',label:'待发送'}]},{key:'qq_group',label:'群号'}],
  columns:[{key:'created_at',label:'创建时间',type:'date',width:160},{key:'repo_full_name',label:'仓库',width:160},{key:'release_tag',label:'版本',width:100},{key:'qq_group',label:'目标群',width:100},{key:'status',label:'状态',type:'status',width:90,options:[{value:'success',label:'成功'},{value:'failed',label:'失败'},{value:'pending',label:'待发送'}]},{key:'retries',label:'重试次数',width:90},{key:'error',label:'失败原因',width:200}],
  actions:[{label:'重新推送',suffix:'retry',method:'POST',type:'warning',confirm:'确定重新发送版本 {name} 的通知吗？',success:(d:any)=>d.message||'处理完成'}],actionWidth:110}
</script>
