<template>
  <Teleport to="body">
    <Transition name="picker-overlay">
      <div
        v-if="pickerStore.isPickerActive"
        class="picker-overlay"
        @mousemove="onMouseMove"
        @click="onClickSelect"
        @keydown.esc="pickerStore.deactivatePicker()"
        tabindex="-1"
        ref="overlayEl"
      >
        <!-- 高亮框 -->
        <div v-if="hoverRect" class="picker-highlight" :style="highlightStyle">
          <span class="picker-label">{{ hoverTitle }}</span>
        </div>

        <!-- 顶部提示 -->
        <div class="picker-hint">
          <span>点击选择页面元素</span>
          <kbd>ESC</kbd>
          <span>取消</span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useElementPickerStore } from '@/stores/elementPickerStore'
import { buildPickedElementContext } from '@/utils/elementPickerContext'

const pickerStore = useElementPickerStore()
const overlayEl = ref<HTMLElement>()

const hoverRect = ref<DOMRect | null>(null)
const hoverTitle = ref('')
const hoveredDom = ref<HTMLElement | null>(null)

// 激活时自动聚焦以接收键盘事件
watch(() => pickerStore.isPickerActive, async (active) => {
  if (active) {
    await nextTick()
    overlayEl.value?.focus()
  } else {
    hoverRect.value = null
    hoveredDom.value = null
  }
})

function findPickable(target: HTMLElement): HTMLElement | null {
  return target.closest<HTMLElement>('[data-pick-id]')
}

function onMouseMove(e: MouseEvent) {
  // 暂时隐藏 overlay 以获取下方实际元素
  const overlay = overlayEl.value
  if (!overlay) return
  overlay.style.pointerEvents = 'none'
  const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null
  overlay.style.pointerEvents = ''

  if (!el) {
    hoverRect.value = null
    hoveredDom.value = null
    return
  }

  const pickable = findPickable(el)
  if (!pickable) {
    hoverRect.value = null
    hoveredDom.value = null
    return
  }

  hoveredDom.value = pickable
  hoverRect.value = pickable.getBoundingClientRect()
  hoverTitle.value = pickable.dataset.pickTitle ?? ''
}

function onClickSelect(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()

  if (!hoveredDom.value) {
    // 点击空白区域，取消选择器
    pickerStore.deactivatePicker()
    return
  }

  const el = hoveredDom.value
  pickerStore.selectElement(buildPickedElementContext(el))
}

const highlightStyle = ref<Record<string, string>>({})

watch(hoverRect, (rect) => {
  if (!rect) {
    highlightStyle.value = { display: 'none' }
    return
  }
  highlightStyle.value = {
    display: 'block',
    top: `${rect.top}px`,
    left: `${rect.left}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
  }
})
</script>

<style scoped>
.picker-overlay {
  position: fixed;
  inset: 0;
  z-index: 9998;
  cursor: crosshair;
  background: rgba(0, 0, 0, 0.08);
  outline: none;
}

.picker-highlight {
  position: fixed;
  border: 2px solid var(--accent, #60a5fa);
  border-radius: 8px;
  background: rgba(96, 165, 250, 0.08);
  pointer-events: none;
  transition: top 0.12s ease, left 0.12s ease, width 0.12s ease, height 0.12s ease;
  box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.25), 0 0 20px rgba(96, 165, 250, 0.15);
}

.picker-label {
  position: absolute;
  left: 0;
  top: -28px;
  background: var(--accent, #60a5fa);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 6px;
  white-space: nowrap;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  pointer-events: none;
}

.picker-hint {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-card, #1e2030);
  color: var(--text-secondary, #a0a8c0);
  font-size: 13px;
  padding: 8px 16px;
  border-radius: 10px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  pointer-events: none;
  z-index: 9999;
}

.picker-hint kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 20px;
  padding: 0 6px;
  background: var(--bg-hover, #2a2e40);
  border: 1px solid var(--border, #3a3e50);
  border-radius: 4px;
  font-size: 11px;
  font-family: inherit;
  color: var(--text-primary, #e0e4f0);
}

/* Transition */
.picker-overlay-enter-active {
  transition: opacity 0.18s ease;
}
.picker-overlay-leave-active {
  transition: opacity 0.12s ease;
}
.picker-overlay-enter-from,
.picker-overlay-leave-to {
  opacity: 0;
}
</style>
