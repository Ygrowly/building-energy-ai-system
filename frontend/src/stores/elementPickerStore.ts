/**
 * 元素选择器状态管理 (Pinia)
 *
 * 管理首页元素选择器的激活状态、悬停高亮和选中元素信息。
 * 选中的元素信息会附加到 AgentConsole 的输入中，作为提问上下文。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface PickedElement {
  id: string
  type: string        // 'kpi' | 'chart' | 'heatmap' | 'weather'
  title: string
  subtitle?: string
}

export const useElementPickerStore = defineStore('elementPicker', () => {
  const isPickerActive = ref(false)
  const selectedElement = ref<PickedElement | null>(null)

  function togglePicker() {
    isPickerActive.value = !isPickerActive.value
  }

  function deactivatePicker() {
    isPickerActive.value = false
  }

  function selectElement(el: PickedElement) {
    selectedElement.value = el
    isPickerActive.value = false
  }

  function clearSelection() {
    selectedElement.value = null
  }

  return {
    isPickerActive,
    selectedElement,
    togglePicker,
    deactivatePicker,
    selectElement,
    clearSelection,
  }
})
