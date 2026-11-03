<template><ResourceView :config="config" /></template>
<script setup lang="ts">
import ResourceView from '../components/ResourceView.vue'
const config={kicker:'EXTENSIONS',title:'插件管理',description:'管理隔离运行的扩展能力，并查看权限声明与账号 / 群绑定',endpoint:'/plugins',itemName:'插件',nameKey:'name',paged:false,actionWidth:165,
  columns:[{key:'name',label:'插件名称',width:165},{key:'plugin_id',label:'插件 ID',width:150},{key:'version',label:'版本',width:85},{key:'author',label:'作者',width:110},{key:'description',label:'说明',width:210},{key:'commands',label:'命令',width:140},{key:'permissions',label:'权限声明',width:175},{key:'binding_count',label:'绑定数',width:80},{key:'load_status',label:'加载状态',type:'status',width:100,options:[{value:'loaded',label:'已加载'},{value:'disabled',label:'已禁用'},{value:'error',label:'错误'}]},{key:'enabled',label:'启用',type:'bool',width:75}],
  createFields:[],editFields:[{key:'enabled',label:'启用插件',type:'switch'},{key:'config',label:'插件配置 JSON',type:'json',rows:6}],
  actions:[{label:'重新加载',suffix:'reload',method:'POST',type:'warning'}],secondaryAction:{label:'扫描插件目录',path:'/plugins/sync',method:'POST',success:(d:any)=>`已同步 ${Array.isArray(d)?d.length:0} 个插件`}}
</script>
