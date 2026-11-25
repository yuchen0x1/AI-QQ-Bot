export function groupNumberText(group: any): string {
  return group.display_number ? `群号标签 ${group.display_number}` : `内部映射 ID ${group.group_number}`
}

export function groupTitle(group: any): string {
  return group.display_name || group.name || (group.display_number ? `QQ群 ${group.display_number}` : `群聊 · 内部 ID ${group.group_number}`)
}
