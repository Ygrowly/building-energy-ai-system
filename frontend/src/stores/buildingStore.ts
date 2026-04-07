/**
 * 楼宇状态管理 (Pinia)。
 *
 * 管理：
 * - 楼宇列表（从 /api/buildings 动态加载）
 * - 当前选中楼宇（供各页面共享）
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiFetch } from '@/api/http'

export interface BuildingInfo {
  building_id: string
  building_type: string
  display_name: string
  icon: string
  sqm: number
  meter_device_id: string
}

const BUILDING_NAME_ALIASES: Record<string, string> = {
  Fox_education_Louie: '教学楼',
  Education: '教学楼',
  'Louie 教学楼': '教学楼',
  Fox_office_Alice: '办公楼',
  Office: '办公楼',
  'Alice 办公楼': '办公楼',
  Fox_public_Henry: '公共楼',
  Public: '公共楼',
  'Public services': '公共楼',
  'Henry 公共服务楼': '公共楼',
  公共服务楼: '公共楼',
  公共楼: '公共楼',
}

export const useBuildingStore = defineStore('building', () => {
  const buildings = ref<BuildingInfo[]>([])
  const selectedType = ref<string>('Office')
  const loading = ref(false)
  const error = ref('')

  const selectedBuilding = computed(
    () => buildings.value.find(b => b.building_type === selectedType.value) ?? null,
  )

  async function fetchBuildings() {
    if (buildings.value.length > 0) return
    loading.value = true
    error.value = ''
    try {
      const data = await apiFetch<BuildingInfo[]>('/api/buildings')
      buildings.value = data
      // 如果当前选中的楼宇不在列表中，自动选第一个
      if (data.length > 0 && !data.find(b => b.building_type === selectedType.value)) {
        selectedType.value = data[0].building_type
      }
    } catch (e: unknown) {
      error.value = (e as Error).message
      console.error('[buildingStore] 加载楼宇列表失败:', e)
    } finally {
      loading.value = false
    }
  }

  function select(buildingType: string) {
    selectedType.value = buildingType
  }

  function normalizeBuildingName(raw?: string | null): string {
    const value = String(raw || '').trim()
    if (!value) return '—'

    if (BUILDING_NAME_ALIASES[value]) {
      return BUILDING_NAME_ALIASES[value]
    }

    const matched = buildings.value.find(b => (
      b.building_id === value
      || b.building_type === value
      || b.display_name === value
    ))

    if (matched) {
      return BUILDING_NAME_ALIASES[matched.display_name]
        || BUILDING_NAME_ALIASES[matched.building_id]
        || BUILDING_NAME_ALIASES[matched.building_type]
        || matched.display_name
    }

    return value
  }

  /**
   * 根据 building_type 返回中文显示名。
   * 优先用 API 返回的 display_name，未加载时降级到 building_type 本身。
   */
  function getBuildingName(buildingKey: string): string {
    return normalizeBuildingName(buildingKey)
  }

  return {
    buildings,
    selectedType,
    selectedBuilding,
    loading,
    error,
    fetchBuildings,
    select,
    normalizeBuildingName,
    getBuildingName,
  }
})
