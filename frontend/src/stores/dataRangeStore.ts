/**
 * 数据库有效时间范围 Store。
 * 从 /api/data-range 获取 MIN/MAX timestamp，缓存在内存中。
 * 供所有页面的日期选择器动态设置 min/max 和默认值。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch } from '@/api/http'

interface DataRange {
  min_date: string
  max_date: string
  default_start: string
  default_end: string
}

export const useDataRangeStore = defineStore('dataRange', () => {
  const minDate = ref('')
  const maxDate = ref('')
  const defaultStart = ref('')
  const defaultEnd = ref('')
  const loaded = ref(false)

  async function fetch() {
    if (loaded.value) return
    try {
      const data = await apiFetch<DataRange>('/api/data-range')
      minDate.value = data.min_date
      maxDate.value = data.max_date
      defaultStart.value = data.default_start
      defaultEnd.value = data.default_end
      loaded.value = true
    } catch (e) {
      console.warn('[dataRangeStore] 获取数据范围失败，使用默认值', e)
      minDate.value = '2026-01-01'
      maxDate.value = '2026-12-31'
      defaultStart.value = '2026-01-01'
      defaultEnd.value = '2026-01-31'
      loaded.value = true
    }
  }

  return { minDate, maxDate, defaultStart, defaultEnd, loaded, fetch }
})
