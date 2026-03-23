<template>
  <div class="home-page">
    <header class="pg-header">
      <div class="pg-greeting">
        <h1 class="pg-title">
          你好，{{ displayName }}！
          <DotLottieVue class="pg-wave-lottie" src="/Hello%20World.json" autoplay loop />
        </h1>
        <p class="pg-sub">今天有什么可以为你效劳的？</p>
      </div>
      <div class="capsule-switcher" ref="capsuleRef">
        <div class="capsule-slider" :style="sliderStyle" />
        <button
          v-for="opt in buildingOptions"
          :key="opt.key"
          :ref="(el) => setBtnRef(el, opt.key)"
          class="capsule-btn"
          :class="{ active: activeBuilding === opt.key }"
          type="button"
          @click="activeBuilding = opt.key"
        >
          {{ opt.label }}
        </button>
      </div>
      <!-- 右侧：天气 + 铃铛 合并卡片 -->
      <div class="header-right-group">
        <div class="weather-widget"
            data-pick-id="weather"
            data-pick-type="weather"
            data-pick-title="天气信息"
            :data-pick-subtitle="`温度 ${weatherTemp != null ? Number(weatherTemp).toFixed(1) + '°C' : '--'}，湿度 ${weatherHumi ?? '--'}%`">
          <div class="weather-date">
            <Icon icon="mdi:calendar-month" width="13" />
            <span>{{ dataDate || '...' }}</span>
          </div>
          <div class="weather-divider"></div>
          <div class="weather-metrics">
            <div class="weather-item">
              <Icon icon="mdi:thermometer" width="14" class="weather-icon temp-icon" />
              <span class="weather-val">{{ weatherTemp != null ? Number(weatherTemp).toFixed(1) : '--' }}<small>°C</small></span>
            </div>
            <div class="weather-item">
              <Icon icon="mdi:water-percent" width="14" class="weather-icon humi-icon" />
              <span class="weather-val">{{ weatherHumi ?? '--' }}<small>%</small></span>
            </div>
          </div>
        </div>

        <div class="header-group-divider"></div>

        <button class="home-bell-btn" @click="notifStore.requestOpenMessages()" aria-label="消息中心">
          <Icon icon="mdi:bell-outline" width="17" />
          <span v-if="notifStore.unreadCount > 0" class="home-bell-dot"></span>
        </button>
      </div>
    </header>

    <section class="kpi-strip">
      <div
        v-for="k in kpis"
        :key="k.label"
        class="kpi-card"
        :data-pick-id="'kpi-' + k.label"
        data-pick-type="kpi"
        :data-pick-title="k.label"
        :data-pick-subtitle="String(k.value)"
      >
        <div class="kpi-ico" :class="k.anim" :style="{ background: k.bg, color: k.color }">
          <Icon :icon="k.icon" width="20" />
        </div>
        <div class="kpi-body">
          <span class="kpi-val">{{ k.value }}</span>
          <span class="kpi-lbl">{{ k.label }}</span>
        </div>
        <div class="kpi-right">
          <span class="kpi-tag" :style="{ color: k.color, background: k.bg }">{{ k.tag }}</span>
          <span v-if="k.change != null" class="kpi-trend" :class="k.change >= 0 ? 'up' : 'down'">
            <Icon :icon="k.change >= 0 ? 'mdi:trending-up' : 'mdi:trending-down'" width="14" />
            {{ k.change >= 0 ? '+' : '' }}{{ k.change }}%
          </span>
        </div>
      </div>
    </section>

    <HomeAllSection
      v-if="activeBuilding === 'all'"
      :overview-data="overviewData"
      :anomaly-data="anomalyData"
      :sankey-data="sankeyData"
    />
    <HomeTeachingSection v-else-if="activeBuilding === 'Education'" :data-date="dataDateForSections" />
    <HomeOfficeSection
      v-else-if="activeBuilding === 'Office'"
      :data-date="dataDateForSections"
      :overview-data="overviewData"
    />
    <HomePublicSection v-else-if="activeBuilding === 'Public services'" :data-date="dataDateForSections" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { apiFetch } from '@/api/http'
import { useBuildingStore } from '@/stores/buildingStore'
import { useAuthStore } from '@/stores/authStore'
import { useNotificationStore } from '@/stores/notificationStore'
import HomeAllSection from '@/components/home/HomeAllSection.vue'
import HomeTeachingSection from '@/components/home/HomeTeachingSection.vue'
import HomeOfficeSection from '@/components/home/HomeOfficeSection.vue'
import HomePublicSection from '@/components/home/HomePublicSection.vue'
import { MC } from '@/utils/homeCharts'

const buildingStore = useBuildingStore()
const authStore     = useAuthStore()
const notifStore    = useNotificationStore()

const displayName = computed(() => authStore.user?.username ?? '访客')

const dataDate = ref('')
const weatherTemp = ref<number | null>(null)
const weatherHumi = ref<number | null>(null)
const overviewData = ref<any>(null)
const anomalyData = ref<any[]>([])
const sankeyData = ref<{
  nodes: { name: string }[]
  links: { source: string; target: string; value: number }[]
} | null>(null)

const buildingOptions = [
  { key: 'all', label: '全部' },
  { key: 'Education', label: '教学楼' },
  { key: 'Office', label: '办公楼' },
  { key: 'Public services', label: '公共楼' },
]
const activeBuilding = ref('all')
const capsuleRef = ref<HTMLElement | null>(null)
const btnRefs = new Map<string, HTMLElement>()

function setBtnRef(el: unknown, key: string) {
  if (el) btnRefs.set(key, el as HTMLElement)
}

const sliderStyle = computed(() => {
  const el = btnRefs.get(activeBuilding.value)
  if (!el || !capsuleRef.value) return { opacity: '0' }
  const parentRect = capsuleRef.value.getBoundingClientRect()
  const btnRect = el.getBoundingClientRect()
  return {
    width: `${btnRect.width}px`,
    transform: `translateX(${btnRect.left - parentRect.left}px)`,
    opacity: '1',
  }
})

const forceSliderUpdate = ref(0)
watch(activeBuilding, () => {
  nextTick(() => {
    forceSliderUpdate.value++
  })
})

/** 子组件 API 用 YYYY-MM-DD；无数据时给今天避免空请求 */
const dataDateForSections = computed(() => {
  const d = dataDate.value
  if (d && d.length >= 10) return d.slice(0, 10)
  return new Date().toISOString().slice(0, 10)
})

const CARBON_FACTOR = 0.5703
const kpis = computed(() => {
  void forceSliderUpdate.value
  const ov = overviewData.value
  if (!ov) return []
  const sel = activeBuilding.value
  const buildings: any[] = ov.buildings ?? []
  const chg = ov.kpis_change ?? {}

  let elec = 0,
    water = 0,
    hac = 0
  let elecChg: number | null = null,
    waterChg: number | null = null
  let hacChg: number | null = null,
    carbonChg: number | null = null

  if (sel === 'all') {
    elec = Number(ov.kpis?.total_electricity_kwh ?? 0)
    water = Number(ov.kpis?.total_water_m3 ?? 0)
    hac = Number(ov.kpis?.total_hac_energy_kwh ?? 0)
    elecChg = chg.total_electricity_pct ?? null
    waterChg = chg.total_water_pct ?? null
    hacChg = chg.total_hac_pct ?? null
    carbonChg = chg.total_carbon_pct ?? null
  } else {
    const b = buildings.find((x: any) => x.building_type === sel)
    elec = b ? Number(b.total_electricity_kwh ?? 0) : 0
    water = b ? Number(b.total_water_m3 ?? 0) : 0
    hac = b ? Number(b.total_hac_energy_kwh ?? 0) : 0
    elecChg = b?.electricity_change_pct ?? null
    waterChg = b?.water_change_pct ?? null
    hacChg = b?.hac_change_pct ?? null
    carbonChg = b?.carbon_change_pct ?? null
  }
  const carbon = elec * CARBON_FACTOR

  return [
    {
      icon: 'mdi:lightning-bolt',
      label: '日总用电 (kWh)',
      value: elec.toFixed(1),
      change: elecChg,
      tag: '今日',
      bg: 'rgba(122,170,142,0.14)',
      color: MC.sage,
      anim: 'anim-bolt',
    },
    {
      icon: 'mdi:water',
      label: '日总用水 (m³)',
      value: water.toFixed(1),
      change: waterChg,
      tag: '今日',
      bg: 'rgba(123,159,199,0.14)',
      color: MC.blue,
      anim: 'anim-drop',
    },
    {
      icon: 'mdi:snowflake',
      label: '空调能耗 (kWh)',
      value: hac.toFixed(1),
      change: hacChg,
      tag: '今日',
      bg: 'rgba(155,143,196,0.14)',
      color: MC.lav,
      anim: 'anim-spin',
    },
    {
      icon: 'mdi:leaf',
      label: '碳排放量 (kg)',
      value: carbon.toFixed(1),
      change: carbonChg,
      tag: 'CO₂',
      bg: 'rgba(196,149,106,0.14)',
      color: MC.terra,
      anim: 'anim-breathe',
    },
  ]
})

async function fetchOverview() {
  try {
    const data = await apiFetch<any>('/api/overview')
    overviewData.value = data
    dataDate.value = data?.data_date ?? ''
    weatherTemp.value = data?.weather?.temperature ?? null
    weatherHumi.value = data?.weather?.humidity ?? null
  } catch {
    /* silent */
  }
}

async function fetchAnomalies() {
  try {
    const data = await apiFetch<any>('/api/anomalies/recent?hours=168')
    anomalyData.value = data?.anomalies ?? []
  } catch {
    /* silent */
  }
}

async function fetchSankeyData() {
  try {
    const data = await apiFetch<any>('/api/anomalies/sankey')
    if (data?.nodes?.length && data?.links?.length) {
      sankeyData.value = data
    }
  } catch {
    /* silent */
  }
}

onMounted(async () => {
  await buildingStore.fetchBuildings()
  await Promise.all([fetchOverview(), fetchAnomalies(), fetchSankeyData()])
})
</script>

<style scoped>
.home-page {
  container-type: inline-size;
  padding: 28px 24px 32px;
  min-height: 100%;
  background: var(--bg-dark);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-sizing: border-box;
}

.pg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 10px;
}

.capsule-switcher {
  position: relative;
  display: inline-flex;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 24px;
  padding: 3px;
  gap: 0;
  flex-shrink: 0;
}
.capsule-slider {
  position: absolute;
  top: 3px;
  left: 0;
  height: calc(100% - 6px);
  border-radius: 20px;
  background: var(--border-accent, rgba(122, 170, 142, 0.35));
  transition:
    transform 0.3s cubic-bezier(0.4, 0, 0.2, 1),
    width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
  z-index: 0;
}
.capsule-btn {
  position: relative;
  z-index: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  padding: 5px 16px;
  border-radius: 20px;
  cursor: pointer;
  transition: color 0.25s;
  white-space: nowrap;
}
.capsule-btn.active {
  color: var(--text-primary);
  font-weight: 600;
}
.capsule-btn:hover:not(.active) {
  color: var(--text-primary);
}
.pg-greeting {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pg-title {
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  line-height: 1.2;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.pg-wave-lottie {
  width: 36px;
  height: 36px;
  display: inline-block;
  flex-shrink: 0;
}
@container (max-width: 539px) {
  .pg-wave-lottie {
    width: 28px;
    height: 28px;
  }
}
@container (max-width: 399px) {
  .pg-wave-lottie {
    width: 22px;
    height: 22px;
  }
}
.pg-sub {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 400;
}
/* ── 右侧天气+铃铛整体容器 ── */
.header-right-group {
  display: flex;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0;
  overflow: hidden;
  flex-shrink: 0;
}
.header-group-divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  flex-shrink: 0;
}

/* ── 消息铃铛 ── */
.home-bell-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 38px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.18s ease, color 0.18s ease;
}
.home-bell-dot {
  position: absolute;
  top: 7px;
  right: 8px;
  width: 7px;
  height: 7px;
  background: #e53e3e;
  border-radius: 50%;
  border: none;
}

.weather-widget {
  display: flex;
  align-items: center;
  gap: 10px;
  background: transparent;
  padding: 8px 14px;
  flex-shrink: 0;
}
.weather-date {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.weather-divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  flex-shrink: 0;
}
.weather-metrics {
  display: flex;
  align-items: center;
  gap: 12px;
}
.weather-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.weather-icon {
  flex-shrink: 0;
}
.temp-icon {
  color: #e8845a;
}
.humi-icon {
  color: #5a9fd4;
}
.weather-val {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.weather-val small {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-secondary);
  margin-left: 1px;
}

.kpi-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  flex-shrink: 0;
}
.kpi-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: border-color 0.2s;
}
.kpi-card:hover {
  border-color: var(--border-accent);
}
.kpi-ico {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition:
    transform 0.3s ease,
    box-shadow 0.3s ease;
}
.kpi-card:hover .kpi-ico {
  transform: scale(1.15);
  box-shadow: 0 0 12px rgba(0, 0, 0, 0.08);
}

.anim-bolt :deep(svg) {
  animation: bolt-flash 2s ease-in-out infinite;
}
@keyframes bolt-flash {
  0%,
  100% {
    opacity: 1;
    filter: drop-shadow(0 0 0px currentColor);
  }
  15% {
    opacity: 0.4;
    filter: drop-shadow(0 0 0px currentColor);
  }
  30% {
    opacity: 1;
    filter: drop-shadow(0 0 6px currentColor);
  }
  45% {
    opacity: 0.6;
  }
  60% {
    opacity: 1;
    filter: drop-shadow(0 0 3px currentColor);
  }
}

.anim-drop :deep(svg) {
  animation: drop-bounce 2.5s ease-in-out infinite;
  transform-origin: center bottom;
}
@keyframes drop-bounce {
  0%,
  100% {
    transform: translateY(0) scaleY(1);
  }
  30% {
    transform: translateY(-3px) scaleY(1.05);
  }
  50% {
    transform: translateY(1px) scaleY(0.95) scaleX(1.05);
  }
  70% {
    transform: translateY(-1px) scaleY(1.02);
  }
}

.anim-spin :deep(svg) {
  animation: snowflake-pulse 3s ease-in-out infinite;
}
@keyframes snowflake-pulse {
  0%,
  100% {
    transform: rotate(0deg) scale(1);
    opacity: 0.85;
  }
  50% {
    transform: rotate(180deg) scale(1.15);
    opacity: 1;
  }
}

.anim-breathe :deep(svg) {
  animation: co2-breathe 3s ease-in-out infinite;
}
@keyframes co2-breathe {
  0%,
  100% {
    transform: translateY(0) scale(1);
    opacity: 0.85;
  }
  50% {
    transform: translateY(-3px) scale(1.1);
    opacity: 1;
  }
}

.kpi-body {
  flex: 1;
  min-width: 0;
}
.kpi-val {
  display: block;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi-lbl {
  display: block;
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  flex-shrink: 0;
}
.kpi-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 20px;
  white-space: nowrap;
}
.kpi-trend {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 20px;
  white-space: nowrap;
  margin-top: 2px;
}
.kpi-trend-label {
  font-weight: 400;
  opacity: 0.7;
  margin-left: 2px;
  font-size: 10px;
}
.kpi-trend.up {
  color: #e65100;
  background: rgba(230, 81, 0, 0.08);
}
.kpi-trend.down {
  color: #16a34a;
  background: rgba(22, 163, 74, 0.08);
}

@container (max-width: 899px) {
  .home-page {
    padding: 20px 18px 28px;
    gap: 14px;
  }
}

@container (max-width: 699px) {
  .pg-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .capsule-switcher {
    align-self: stretch;
    justify-content: center;
  }
  .capsule-btn {
    flex: 1;
    text-align: center;
    padding: 5px 10px;
  }
  .home-page {
    padding: 16px 14px 24px;
    gap: 12px;
  }
  .kpi-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
}

@container (max-width: 539px) {
  .capsule-btn {
    font-size: 11px;
    padding: 4px 8px;
  }
  .home-page {
    padding: 12px 10px 20px;
    gap: 10px;
  }
  .kpi-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .kpi-card {
    padding: 10px 10px;
    gap: 8px;
  }
  .kpi-ico {
    width: 30px;
    height: 30px;
    border-radius: 8px;
  }
  .kpi-val {
    font-size: 15px;
  }
  .kpi-tag {
    display: none;
  }
}

@container (max-width: 399px) {
  .home-page {
    padding: 10px 8px 16px;
    gap: 8px;
  }
  .pg-title {
    font-size: 16px;
  }
  .pg-sub {
    display: none;
  }
  .weather-widget {
    display: none;
  }
}

html[data-theme='light'] .kpi-card {
  background: #ffffff;
  border-color: #e2e8e4;
}
html[data-theme="light"] .header-right-group {
  background: #ffffff;
  border-color: #e2e8e4;
}
html[data-theme="light"] .header-group-divider {
  background: #e2e8e4;
}
html[data-theme="light"] .weather-date {
  color: #666;
}
html[data-theme='light'] .weather-val {
  color: #111;
}
html[data-theme='light'] .weather-divider {
  background: #e2e8e4;
}
html[data-theme='light'] .capsule-switcher {
  background: #f4f7f5;
  border-color: #e2e8e4;
}
html[data-theme='light'] .capsule-slider {
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
html[data-theme='light'] .capsule-btn {
  color: #888;
}
html[data-theme='light'] .capsule-btn.active {
  color: #111;
}
html[data-theme='light'] .pg-title {
  color: #111;
}
html[data-theme='light'] .pg-sub {
  color: #666;
}
html[data-theme='light'] .kpi-val {
  color: #111;
}
html[data-theme='light'] .kpi-lbl {
  color: #666;
}
</style>
