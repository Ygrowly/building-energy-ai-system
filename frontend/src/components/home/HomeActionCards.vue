<script setup lang="ts">
import { computed } from 'vue'
import { Icon } from '@iconify/vue'
import { getBuildingLabel, type BuildingFilterValue } from '@/constants/buildings'

const props = withDefaults(
  defineProps<{
    tab: BuildingFilterValue
    anomalies?: any[]
    ratedAnomalyHours?: number | null
    nightAbnormalHours?: number | null
    deltaTSupplyReturn?: number | null
    euiRatio?: number | null
  }>(),
  { anomalies: () => [] },
)

function labelType(bt: string) {
  return getBuildingLabel(bt, bt)
}

const items = computed(() => {
  const out: string[] = []
  const ax = props.anomalies || []

  if (props.tab === 'all') {
    ax.slice(0, 4).forEach((a: any) => {
      const msg = (a.message || a.rule || '异常').toString()
      out.push(`${labelType(a.building_type || '')} ${msg}`.slice(0, 44))
    })
    if (!out.length) out.push('暂无待处理告警，继续监测各楼分项')
    return out.slice(0, 4)
  }

  if (props.tab === 'Education') {
    if ((props.ratedAnomalyHours ?? 0) > 3)
      out.push('授课外时段偏差小时偏多，核查空调与新风排程')
    if ((props.deltaTSupplyReturn ?? 99) < 3)
      out.push('供回水温差偏小，巡检末端水力平衡与阀门')
    if (!out.length) out.push('节律与暖通指标正常，保持当前运行策略')
    return out.slice(0, 4)
  }

  if (props.tab === 'Office') {
    if ((props.nightAbnormalHours ?? 0) > 0)
      out.push('夜间高耗采样偏多，检查照明与空调关停策略')
    if ((props.euiRatio ?? 0) > 1.05)
      out.push('EUI 相对国标偏高，核查空置楼层与排程')
    if (!out.length) out.push('办公负荷与峰谷结构正常，维持巡检节奏')
    return out.slice(0, 4)
  }

  // Public services
  const waterHit = ax.some((a: any) => String(a.rule || '').includes('water'))
  if (waterHit) out.push('水耗类告警活跃，优先排查卫生间与食堂支路')
  if ((props.ratedAnomalyHours ?? 0) > 2)
    out.push('连续服务时段偏差上升，检查新风与除湿联动')
  if (!out.length) out.push('公共楼运行平稳，关注舒适度与水耗联动')
  return out.slice(0, 4)
})
</script>

<template>
  <div class="home-action-cards">
    <div class="home-action-cards-hd">
      <Icon icon="mdi:clipboard-text-outline" width="16" />
      建议动作
    </div>
    <ul>
      <li v-for="(t, i) in items" :key="i">{{ t }}</li>
    </ul>
  </div>
</template>
