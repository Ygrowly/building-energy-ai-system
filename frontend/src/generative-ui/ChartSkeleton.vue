<template>
  <div class="chart-skeleton">
    <!-- Y 轴刻度模拟 -->
    <div class="skeleton-y-axis">
      <div class="y-tick" v-for="i in 4" :key="'y'+i"></div>
    </div>

    <!-- 图表区域 -->
    <div class="skeleton-chart-area">
      <!-- 网格线 -->
      <div class="skeleton-grid">
        <div class="grid-line" v-for="i in 4" :key="'h'+i"></div>
      </div>

      <!-- 模拟柱状图骨架（底部对齐） -->
      <div class="skeleton-bars">
        <div class="bar-group" v-for="(h, i) in barHeights" :key="'b'+i">
          <div class="bar" :style="{ height: h + '%', animationDelay: (i * 0.12) + 's' }"></div>
        </div>
      </div>

      <!-- 模拟折线曲线叠加 -->
      <svg class="skeleton-wave" viewBox="0 0 400 120" preserveAspectRatio="none">
        <path
          d="M0,90 C40,85 60,70 100,60 C140,50 160,75 200,55 C240,35 260,45 300,30 C340,15 370,25 400,20"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
        />
        <path
          d="M0,90 C40,85 60,70 100,60 C140,50 160,75 200,55 C240,35 260,45 300,30 C340,15 370,25 400,20 L400,120 L0,120 Z"
          fill="url(#skel-grad)"
        />
        <defs>
          <linearGradient id="skel-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="currentColor" stop-opacity="0.06" />
            <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
          </linearGradient>
        </defs>
      </svg>

      <!-- 横向扫光 -->
      <div class="shimmer-overlay"></div>
    </div>

    <!-- X 轴刻度模拟 -->
    <div class="skeleton-x-axis">
      <div class="x-tick" v-for="i in 6" :key="'x'+i"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
const barHeights = [45, 62, 38, 78, 55, 70, 42, 65, 50, 72, 48, 58]
</script>

<style scoped>
.chart-skeleton {
  position: relative;
  width: 100%;
  height: 180px;
  border-radius: 10px;
  background: var(--bg-card, rgba(255, 255, 255, 0.02));
  border: 1px solid rgba(108, 142, 245, 0.08);
  overflow: hidden;
  display: grid;
  grid-template-columns: 28px 1fr;
  grid-template-rows: 1fr 20px;
  padding: 14px 12px 6px 4px;
  gap: 0;
}

/* Y 轴 */
.skeleton-y-axis {
  grid-row: 1;
  grid-column: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 2px 0;
}
.y-tick {
  width: 20px;
  height: 6px;
  border-radius: 3px;
  background: var(--skel-muted, rgba(108, 142, 245, 0.08));
}

/* 图表区域 */
.skeleton-chart-area {
  grid-row: 1;
  grid-column: 2;
  position: relative;
  overflow: hidden;
  border-radius: 4px;
}

/* 网格线 */
.skeleton-grid {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.grid-line {
  height: 1px;
  background: var(--skel-line, rgba(108, 142, 245, 0.05));
}

/* 柱状图骨架 */
.skeleton-bars {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 100%;
  display: flex;
  align-items: flex-end;
  gap: 4px;
  padding: 0 4px;
  z-index: 1;
}
.bar-group {
  flex: 1;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.bar {
  width: 70%;
  max-width: 24px;
  border-radius: 3px 3px 0 0;
  background: var(--skel-bar, rgba(108, 142, 245, 0.08));
  animation: barPulse 2.4s ease-in-out infinite;
}
@keyframes barPulse {
  0%, 100% { opacity: 0.5; }
  50%      { opacity: 1; }
}

/* 折线叠加 */
.skeleton-wave {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 65%;
  color: var(--accent, #6c8ef5);
  opacity: 0.1;
  animation: wavePulse 2.5s ease-in-out infinite;
  z-index: 2;
  pointer-events: none;
}
@keyframes wavePulse {
  0%, 100% { opacity: 0.06; }
  50%      { opacity: 0.15; }
}

/* X 轴 */
.skeleton-x-axis {
  grid-row: 2;
  grid-column: 2;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 4px 0;
}
.x-tick {
  width: 26px;
  height: 6px;
  border-radius: 3px;
  background: var(--skel-muted, rgba(108, 142, 245, 0.08));
}

/* 横向扫光 */
.shimmer-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(108, 142, 245, 0.03) 40%,
    rgba(108, 142, 245, 0.06) 50%,
    rgba(108, 142, 245, 0.03) 60%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmerSlide 2s ease-in-out infinite;
  pointer-events: none;
  z-index: 3;
}
@keyframes shimmerSlide {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

/* ── Light theme ── */
html[data-theme="light"] .chart-skeleton {
  background: rgba(248, 250, 252, 0.6);
  border-color: rgba(0, 0, 0, 0.06);
}
html[data-theme="light"] .y-tick,
html[data-theme="light"] .x-tick {
  background: rgba(0, 0, 0, 0.06);
}
html[data-theme="light"] .grid-line {
  background: rgba(0, 0, 0, 0.04);
}
html[data-theme="light"] .bar {
  background: rgba(108, 142, 245, 0.1);
}
html[data-theme="light"] .shimmer-overlay {
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(0, 0, 0, 0.015) 40%,
    rgba(0, 0, 0, 0.03) 50%,
    rgba(0, 0, 0, 0.015) 60%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmerSlide 2s ease-in-out infinite;
}

/* prefers-reduced-motion */
@media (prefers-reduced-motion: reduce) {
  .bar, .skeleton-wave, .shimmer-overlay {
    animation: none;
  }
  .bar            { opacity: 0.7; }
  .skeleton-wave  { opacity: 0.1; }
  .shimmer-overlay { display: none; }
}
</style>
