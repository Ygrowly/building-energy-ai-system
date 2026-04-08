<script setup lang="ts">
import { computed } from 'vue'
import { Icon } from '@iconify/vue'

interface StewardStatItem {
  label: string
  value: string | number
  prefix?: string
  suffix?: string
}

interface HomeAiStewardCardProps {
  title?: string
  statusText?: string
  statusTone?: 'success' | 'warning' | 'danger' | 'neutral'
  reportTitle?: string
  reportDesc?: string
  stats?: StewardStatItem[]
  forecastTitle?: string
  forecastText?: string
  optimizeTitle?: string
  optimizeText?: string
  loading?: boolean
  showViewAll?: boolean
  showRefresh?: boolean
  viewAllText?: string
  refreshText?: string
}

const DEFAULT_STATS: StewardStatItem[] = [
  { label: '节省电费', value: '0.00', prefix: '￥' },
  { label: '减少碳排放', value: '0.0', suffix: 'kg' },
  { label: '避免无效电耗', value: '0.0', suffix: 'kWh' },
]

const props = withDefaults(defineProps<HomeAiStewardCardProps>(), {
  title: 'AI 智能运行管家',
  statusText: '状态: 极佳',
  statusTone: 'success',
  reportTitle: '昨日 AI 运行成效简报 (00:00 - 24:00)',
  reportDesc: '根据后端实际运行数据与额定基线复盘，昨日系统形成如下运行收益：',
  forecastTitle: '近期负荷前瞻',
  forecastText: '预测预警模型当前未发现新增高风险偏离，系统将持续监测未来 6-12 小时负荷变化。',
  optimizeTitle: '深度寻优潜力',
  optimizeText: '系统正在结合教学楼供回水温与近 14 日运行曲线，持续评估可落地的调优空间。',
  loading: false,
  showViewAll: true,
  showRefresh: true,
  viewAllText: '查看全部',
  refreshText: '刷新',
})

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'view-all'): void
}>()

const displayStats = computed(() => (props.stats?.length ? props.stats : DEFAULT_STATS))
const refreshIcon = computed(() => (props.loading ? 'mdi:loading' : 'mdi:refresh'))
const statusClass = computed(() => `status-tag--${props.statusTone}`)
</script>

<template>
  <section
    class="home-ai-steward"
    aria-label="AI 智能运行管家"
    data-pick-id="home-ai-steward"
    data-pick-type="card"
    :data-pick-title="title"
    :data-pick-subtitle="reportTitle"
  >
    <header class="home-ai-steward__header">
      <div class="home-ai-steward__title-wrap">
        <span class="home-ai-steward__title-icon">
          <Icon icon="mdi:head-cog-outline" width="18" />
        </span>
        <h3 class="home-ai-steward__title">{{ title }}</h3>
      </div>

      <div class="home-ai-steward__toolbar">
        <button
          v-if="showRefresh"
          class="toolbar-btn"
          type="button"
          :disabled="loading"
          @click="emit('refresh')"
        >
          <Icon :icon="refreshIcon" width="15" :class="{ 'is-spinning': loading }" />
          <span>{{ refreshText }}</span>
        </button>

        <button
          v-if="showViewAll"
          class="toolbar-btn toolbar-btn--quiet"
          type="button"
          @click="emit('view-all')"
        >
          <span>{{ viewAllText }}</span>
          <Icon icon="mdi:arrow-right" width="15" />
        </button>

        <span class="status-tag" :class="statusClass">
          <Icon icon="mdi:check-circle" width="15" />
          <span>{{ statusText }}</span>
        </span>
      </div>
    </header>

    <div class="home-ai-steward__body">
      <section class="brief-card">
        <div class="brief-card__head">
          <div class="brief-card__title-row">
            <Icon icon="mdi:chart-box-outline" width="18" />
            <span>{{ reportTitle }}</span>
          </div>
          <p class="brief-card__desc">{{ reportDesc }}</p>
        </div>

        <div class="brief-card__stats">
          <article v-for="item in displayStats" :key="item.label" class="brief-stat">
            <div class="brief-stat__label">{{ item.label }}</div>
            <div class="brief-stat__value-row">
              <span class="brief-stat__value">
                <span v-if="item.prefix" class="brief-stat__affix">{{ item.prefix }}</span>
                {{ item.value }}
                <span v-if="item.suffix" class="brief-stat__suffix">{{ item.suffix }}</span>
              </span>
              <span class="brief-stat__trend">
                <Icon icon="mdi:arrow-top-right" width="15" />
              </span>
            </div>
          </article>
        </div>
      </section>

      <div class="insight-grid">
        <article class="insight-card insight-card--forecast">
          <div class="insight-card__title-row">
            <Icon icon="mdi:weather-partly-cloudy" width="18" />
            <h4 class="insight-card__title">{{ forecastTitle }}</h4>
          </div>
          <p class="insight-card__text">{{ forecastText }}</p>
        </article>

        <article class="insight-card insight-card--optimize">
          <div class="insight-card__title-row">
            <Icon icon="mdi:lightbulb-on-outline" width="18" />
            <h4 class="insight-card__title">{{ optimizeTitle }}</h4>
          </div>
          <p class="insight-card__text">{{ optimizeText }}</p>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.home-ai-steward {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
  transition: border-color 0.2s ease;
}

.home-ai-steward:hover {
  border-color: var(--border-accent);
}

.home-ai-steward__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}

.home-ai-steward__title-wrap {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.home-ai-steward__title-icon {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  background: var(--accent-glow);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
  flex-shrink: 0;
}

.home-ai-steward__title {
  font-size: 18px;
  line-height: 1.2;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.home-ai-steward__toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-btn {
  border: 1px solid var(--border);
  background: rgba(148, 163, 184, 0.08);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.toolbar-btn:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-accent);
  background: rgba(148, 163, 184, 0.14);
}

.toolbar-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.toolbar-btn--quiet {
  background: transparent;
}

.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.status-tag--success {
  color: var(--success);
  background: rgba(74, 222, 128, 0.12);
  border: 1px solid rgba(74, 222, 128, 0.24);
}

.status-tag--warning {
  color: var(--warning);
  background: rgba(251, 191, 36, 0.14);
  border: 1px solid rgba(251, 191, 36, 0.22);
}

.status-tag--danger {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.14);
  border: 1px solid rgba(248, 113, 113, 0.22);
}

.status-tag--neutral {
  color: var(--text-secondary);
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.home-ai-steward__body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.brief-card {
  border-radius: 20px;
  padding: 18px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background:
    linear-gradient(180deg, rgba(148, 163, 184, 0.08), rgba(148, 163, 184, 0.04)),
    rgba(255, 255, 255, 0.02);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.brief-card__head {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.brief-card__title-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.brief-card__desc {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.brief-card__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.brief-stat {
  border-radius: 16px;
  padding: 14px 14px 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.10);
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.brief-stat__label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.brief-stat__value-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.brief-stat__value {
  font-size: 28px;
  line-height: 1;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.brief-stat__affix,
.brief-stat__suffix {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-secondary);
}

.brief-stat__trend {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--success);
  background: rgba(74, 222, 128, 0.12);
  flex-shrink: 0;
}

.insight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.insight-card {
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(255, 255, 255, 0.03);
  padding: 18px;
  min-height: 178px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.insight-card--forecast {
  background:
    linear-gradient(180deg, rgba(56, 189, 248, 0.06), transparent),
    rgba(255, 255, 255, 0.03);
}

.insight-card--optimize {
  background:
    linear-gradient(180deg, rgba(34, 197, 94, 0.07), transparent),
    rgba(255, 255, 255, 0.03);
}

.insight-card__title-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
}

.insight-card__title {
  font-size: 14px;
  line-height: 1.4;
  font-weight: 700;
}

.insight-card__text {
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-secondary);
}

.is-spinning {
  animation: steward-spin 0.9s linear infinite;
}

@keyframes steward-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1180px) {
  .brief-card__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .brief-stat:last-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 880px) {
  .insight-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .home-ai-steward {
    padding: 16px;
    border-radius: 8px;
  }

  .brief-card {
    padding: 16px;
  }

  .brief-card__stats {
    grid-template-columns: 1fr;
  }

  .brief-stat:last-child {
    grid-column: auto;
  }

  .brief-stat__value {
    font-size: 24px;
  }

  .insight-card {
    min-height: 0;
    padding: 16px;
  }
}

html[data-theme='light'] .home-ai-steward {
  background: #ffffff;
}

html[data-theme='light'] .toolbar-btn {
  background: #f8fafc;
}

html[data-theme='light'] .toolbar-btn--quiet {
  background: transparent;
}

html[data-theme='light'] .brief-card {
  background:
    linear-gradient(180deg, rgba(241, 245, 249, 0.92), rgba(248, 250, 252, 0.92)),
    #f8fafc;
}

html[data-theme='light'] .brief-stat,
html[data-theme='light'] .insight-card {
  background: rgba(255, 255, 255, 0.88);
}
</style>
