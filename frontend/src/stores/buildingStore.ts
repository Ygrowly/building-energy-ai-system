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

  /**
   * 根据 building_type 返回中文显示名。
   * 优先用 API 返回的 display_name，未加载时降级到 building_type 本身。
   */
  function getBuildingName(buildingType: string): string {
    return buildings.value.find(b => b.building_type === buildingType)?.display_name ?? buildingType
  }

  return {
    buildings,
    selectedType,
    selectedBuilding,
    loading,
    error,
    fetchBuildings,
    select,
    getBuildingName,
  }
})
