<script setup lang="ts">
defineProps<{
  cards: Array<{ label: string; value: string }>
}>()
</script>

<template>
  <div class="home-mini-metrics">
    <div v-for="c in cards" :key="c.label" class="home-mini-metric">
      <div class="home-mini-metric-val">{{ c.value }}</div>
      <div class="home-mini-metric-lbl">{{ c.label }}</div>
    </div>
  </div>
</template>
