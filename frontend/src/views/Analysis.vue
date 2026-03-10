<template>
  <div class="analysis">
    <header class="page-header">
      <h1>📊 能源透视</h1>
      <span class="subtitle">生成式图表分析 · 数据血缘可视化</span>
    </header>

    <div class="hint-card">
      <div>
        <p class="hint-title">💬 在右侧输入分析指令，AI 将自动生成图表</p>
        <p class="hint-examples">例如：「对比图书馆和办公楼最近一周每天的用电量」</p>
      </div>
    </div>

    <!-- 数据血缘流向图 -->
    <section class="section">
      <h2 class="section-title">🔗 数据流向（血缘视图）</h2>
      <div class="lineage-flow">
        <div class="lineage-node source">
          <div class="node-icon">📂</div>
          <div class="node-label">CSV 原始数据</div>
          <div class="node-sub">传感器读数</div>
        </div>
        <div class="lineage-arrow">→</div>
        <div class="lineage-node table">
          <div class="node-icon">🗄️</div>
          <div class="node-label">energy_data</div>
          <div class="node-sub">时序表 · PostgreSQL</div>
        </div>
        <div class="lineage-arrow">→</div>
        <div class="lineage-node view">
          <div class="node-icon">⚡</div>
          <div class="node-label">daily_energy_summary</div>
          <div class="node-sub">物化视图 · 预聚合</div>
        </div>
        <div class="lineage-arrow">→</div>
        <div class="lineage-node ai">
          <div class="node-icon">🤖</div>
          <div class="node-label">AI 分析结论</div>
          <div class="node-sub">LangGraph Agent</div>
        </div>
      </div>
    </section>

    <!-- 空状态提示 -->
    <div class="empty-chart" v-if="!chartGenerated">
      <div class="empty-icon">📈</div>
      <p>在右侧控制台输入分析指令</p>
      <p class="empty-sub">AI 将在此区域生成交互式图表</p>
    </div>
  </div>
</template>

<script setup lang="ts">
const chartGenerated = false
</script>

<style scoped>
.analysis { padding: 24px; }
.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }

.hint-card {
  background: var(--accent-glow);
  border: 1px solid rgba(108,142,245,0.3);
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 24px;
}
.hint-title { font-weight: 600; font-size: 14px; color: var(--accent); margin-bottom: 4px; }
.hint-examples { font-size: 12px; color: var(--text-secondary); }

.section { margin-bottom: 24px; }
.section-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; color: var(--text-secondary); }

.lineage-flow {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
  overflow-x: auto;
}

.lineage-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 20px;
  border-radius: 8px;
  min-width: 130px;
  text-align: center;
}
.lineage-node.source  { background: rgba(74,222,128,0.08); border: 1px solid rgba(74,222,128,0.3); }
.lineage-node.table   { background: rgba(108,142,245,0.08); border: 1px solid rgba(108,142,245,0.3); }
.lineage-node.view    { background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.3); }
.lineage-node.ai      { background: rgba(167,139,250,0.08); border: 1px solid rgba(167,139,250,0.3); }

.node-icon { font-size: 22px; }
.node-label { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.node-sub { font-size: 11px; color: var(--text-muted); }

.lineage-arrow {
  font-size: 20px;
  color: var(--text-muted);
  padding: 0 12px;
  flex-shrink: 0;
}

.empty-chart {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 20px;
  background: var(--bg-panel);
  border: 2px dashed var(--border);
  border-radius: 12px;
  color: var(--text-secondary);
  font-size: 14px;
}
.empty-icon { font-size: 48px; margin-bottom: 8px; }
.empty-sub { font-size: 12px; color: var(--text-muted); }
</style>
