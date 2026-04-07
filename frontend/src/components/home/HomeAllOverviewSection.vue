<script setup lang="ts">
import HomeAiStewardCard from './HomeAiStewardCard.vue'
import HomeBuildingEnergyShareCard from './HomeBuildingEnergyShareCard.vue'
import HomeOverviewVsExpectedCard from './HomeOverviewVsExpectedCard.vue'
import HomeRootCauseSankeyCard from './HomeRootCauseSankeyCard.vue'

defineProps<{
  overviewData: any
  anomalyData: any[]
  aiStewardLoading?: boolean
  overviewSeriesBundle?: Record<string, any> | null
  useBundle?: boolean
  bundlePending?: boolean
  sankeyData: {
    nodes: { name: string }[]
    links: { source: string | number; target: string | number; value: number }[]
  } | null
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'view-all'): void
  (e: 'view-curve'): void
  (e: 'apply-strategy'): void
}>()

function handleStewardRefresh() {
  emit('refresh')
}

function handleStewardViewAll() {
  emit('view-all')
}

function handleStewardViewCurve() {
  emit('view-curve')
}

function handleStewardApplyStrategy() {
  emit('apply-strategy')
}
</script>

<template>
  <div class="home-all-section home-all-overview-section">
    <div class="overview-top-row">
      <HomeOverviewVsExpectedCard
        :overview-data="overviewData"
        :overview-series-bundle="overviewSeriesBundle"
        :use-bundle="useBundle"
        :bundle-pending="bundlePending"
      />
      <HomeBuildingEnergyShareCard :overview-data="overviewData" />
    </div>

    <div class="overview-bottom-row">
      <HomeRootCauseSankeyCard :sankey-data="sankeyData" />
      <HomeAiStewardCard
        class="home-actions-panel"
        :loading="aiStewardLoading"
        @refresh="handleStewardRefresh"
        @view-all="handleStewardViewAll"
        @view-curve="handleStewardViewCurve"
        @apply-strategy="handleStewardApplyStrategy"
      />
    </div>
  </div>
</template>

<style>
.home-page .home-all-overview-section > .overview-bottom-row {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 7fr);
  gap: 14px;
  align-items: stretch;
}

.home-page .home-all-overview-section > .overview-bottom-row > .panel-sankey,
.home-page .home-all-overview-section > .overview-bottom-row > .home-actions-panel {
  grid-column: auto;
  grid-row: auto;
  min-width: 0;
}


@container (max-width: 899px) {
  .home-page .home-all-overview-section > .overview-bottom-row {
    grid-template-columns: minmax(0, 3fr) minmax(0, 7fr);
  }
}

@container (max-width: 699px) {
  .home-page .home-all-overview-section > .overview-bottom-row {
    grid-template-columns: 1fr;
    gap: 10px;
  }
}

@container (max-width: 399px) {
  .home-page .home-all-overview-section > .overview-bottom-row {
    gap: 8px;
  }
}
</style>
