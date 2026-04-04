export interface ConversationReportTemplateOption {
  id: string
  label: string
  description: string
  mode: 'formal' | 'snapshot'
  default?: boolean
}

export const conversationReportTemplates: ConversationReportTemplateOption[] = [
  {
    id: 'formal-management-brief',
    label: 'AI辅助研判会话纪要',
    description: '围绕一次会话总结问题、过程、结论和行动项，适合正式会议导出。',
    mode: 'formal',
    default: true,
  },
]

export const defaultConversationReportTemplate =
  conversationReportTemplates.find(template => template.default) ?? conversationReportTemplates[0]
