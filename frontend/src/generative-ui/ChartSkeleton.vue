<template>
  <div class="chart-skeleton">
    <!-- 微弱网格线暗示图表结构 -->
    <div class="skeleton-grid">
      <div class="grid-line" v-for="i in 4" :key="'h'+i"></div>
    </div>

    <!-- 模拟波形曲线（暗示折线图即将出现） -->
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
        fill="url(#skeleton-gradient)"
      />
      <defs>
        <linearGradient id="skeleton-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="currentColor" stop-opacity="0.08" />
          <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
        </linearGradient>
      </defs>
    </svg>

    <!-- 中心加载指示器 -->
    <div class="skeleton-center">
      <div class="skeleton-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
      </div>
      <span class="skeleton-label">图表加载中...</span>
    </div>

    <!-- 横向扫光动画 -->
    <div class="shimmer-overlay"></div>
  </div>
</template>

<style scoped>
.chart-skeleton {
  position: relative;
  width: 100%;
  height: 200px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.04);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 网格线 */
.skeleton-grid {
  position: absolute;
  inset: 20px 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.grid-line {
  height: 1px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 1px;
}

/* 波形曲线 */
.skeleton-wave {
  position: absolute;
  bottom: 20px;
  left: 16px;
  right: 16px;
  height: 60%;
  color: var(--accent, #6c8ef5);
  opacity: 0.12;
  animation: wavePulse 2.5s ease-in-out infinite;
}

@keyframes wavePulse {
  0%, 100% { opacity: 0.08; }
  50%      { opacity: 0.18; }
}

/* 中心图标 + 文字 */
.skeleton-center {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.skeleton-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted, #6b7280);
  animation: iconPulse 2s ease-in-out infinite;
}

@keyframes iconPulse {
  0%, 100% { opacity: 0.5; transform: scale(1); }
  50%      { opacity: 0.9; transform: scale(1.04); }
}

.skeleton-label {
  font-size: 11px;
  color: var(--text-muted, #6b7280);
  letter-spacing: 0.03em;
  opacity: 0.6;
  animation: labelPulse 2s ease-in-out infinite;
}

@keyframes labelPulse {
  0%, 100% { opacity: 0.4; }
  50%      { opacity: 0.7; }
}

/* 横向扫光 */
.shimmer-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.03) 40%,
    rgba(255, 255, 255, 0.06) 50%,
    rgba(255, 255, 255, 0.03) 60%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmerSlide 2s ease-in-out infinite;
  pointer-events: none;
}

@keyframes shimmerSlide {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

/* Light theme */
html[data-theme="light"] .chart-skeleton {
  background: rgba(0, 0, 0, 0.02);
  border-color: rgba(0, 0, 0, 0.04);
}

html[data-theme="light"] .grid-line {
  background: rgba(0, 0, 0, 0.04);
}

html[data-theme="light"] .skeleton-icon {
  background: rgba(0, 0, 0, 0.03);
  border-color: rgba(0, 0, 0, 0.06);
}

html[data-theme="light"] .shimmer-overlay {
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(0, 0, 0, 0.02) 40%,
    rgba(0, 0, 0, 0.04) 50%,
    rgba(0, 0, 0, 0.02) 60%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmerSlide 2s ease-in-out infinite;
}

/* prefers-reduced-motion: 关闭所有动画 */
@media (prefers-reduced-motion: reduce) {
  .skeleton-wave,
  .skeleton-icon,
  .skeleton-label,
  .shimmer-overlay {
    animation: none;
  }
  .skeleton-wave   { opacity: 0.12; }
  .skeleton-icon   { opacity: 0.6; }
  .skeleton-label  { opacity: 0.5; }
  .shimmer-overlay { display: none; }
}
</style>
