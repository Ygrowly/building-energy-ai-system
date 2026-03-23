<script setup lang="ts">
defineProps<{
  cards: Array<{ label: string; value: string; unit?: string; desc?: string }>
}>()
</script>

<template>
  <div class="home-mini-metrics">
    <div v-for="c in cards" :key="c.label" class="home-mini-metric">
      <div class="home-mini-metric-top">
        <span class="home-mini-metric-val">{{ c.value }}</span>
        <span v-if="c.unit" class="home-mini-metric-unit">{{ c.unit }}</span>
      </div>
      <div class="home-mini-metric-lbl">{{ c.label }}</div>
      <div v-if="c.desc" class="home-mini-metric-desc">{{ c.desc }}</div>
    </div>
  </div>
</template>

<style scoped>
.home-mini-metrics {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.home-mini-metric {
  flex: 1;
  min-width: 120px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.home-mini-metric-top {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.home-mini-metric-val {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.home-mini-metric-unit {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
}

.home-mini-metric-lbl {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.home-mini-metric-desc {
  font-size: 10px;
  color: var(--text-muted);
  line-height: 1.4;
  margin-top: 2px;
}
</style>
