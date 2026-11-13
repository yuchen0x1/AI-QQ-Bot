export function groupNumberText(group: any): string {
  return group.display_number || '未标注群号'
}

export function groupTitle(group: any): string {
  return group.display_name || (group.display_number ? `QQ群 ${group.display_number}` : '未标注群号')
}
