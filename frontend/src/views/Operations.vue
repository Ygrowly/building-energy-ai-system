<template>
  <div class="operations">
    <header class="page-header">
      <h1>🔧 智慧运维</h1>
      <span class="subtitle">故障诊断 · 工单管理 · 可解释性分析</span>
    </header>

    <div class="hint-card">
      <div class="hint-icon">💬</div>
      <div>
        <p class="hint-title">在右侧输入故障场景，AI 将自动诊断并生成工单</p>
        <p class="hint-examples">
          例如：「办公楼今天凌晨3点的能耗是不是有问题？帮我处理一下」
        </p>
      </div>
    </div>

    <section class="section">
      <h2 class="section-title">🚨 当前异常记录（示例）</h2>
      <div class="anomaly-list">
        <div class="anomaly-item" v-for="a in anomalies" :key="a.id">
          <div class="anomaly-left">
            <span class="anomaly-priority" :class="a.priority.toLowerCase()">{{ a.priority }}</span>
            <div>
              <p class="anomaly-title">{{ a.title }}</p>
              <p class="anomaly-meta">{{ a.time }} · 设备 {{ a.device }}</p>
            </div>
          </div>
          <span class="anomaly-status" :class="a.status">{{ a.statusLabel }}</span>
        </div>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">🛡️ 可解释性说明</h2>
      <div class="explainability-card">
        <p>当 AI 给出诊断结论时，右侧控制台会显示：</p>
        <ul>
          <li>📊 <strong>原始数据快照</strong>：触发异常的真实传感器数值</li>
          <li>📖 <strong>知识库依据</strong>：从运维手册中检索到的相关条文</li>
          <li>📈 <strong>置信度评分</strong>：AI 推理的可信程度</li>
          <li>🛠️ <strong>工单草稿</strong>：需要人工审批才能正式派单（HITL）</li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
const anomalies = [
  {
    id: 1, priority: 'High', title: '办公楼凌晨3点高耗电异常',
    time: '今天 03:00', device: 'M-OFF-001',
    status: 'pending', statusLabel: '待处理',
  },
  {
    id: 2, priority: 'Medium', title: '图书馆空调 COP 低于基准',
    time: '昨天 14:00', device: 'M-EDU-001',
    status: 'investigating', statusLabel: '排查中',
  },
]
</script>

<style scoped>
.operations { padding: 24px; }
.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }

.hint-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  background: var(--accent-glow);
  border: 1px solid rgba(108,142,245,0.3);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 24px;
}
.hint-icon { font-size: 24px; }
.hint-title { font-weight: 600; font-size: 14px; color: var(--accent); margin-bottom: 4px; }
.hint-examples { font-size: 12px; color: var(--text-secondary); }

.section { margin-bottom: 24px; }
.section-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; color: var(--text-secondary); }

.anomaly-list { display: flex; flex-direction: column; gap: 8px; }

.anomaly-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}

.anomaly-left { display: flex; align-items: center; gap: 12px; }

.anomaly-priority {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
}
.anomaly-priority.high { background: rgba(248,113,113,0.15); color: var(--danger); }
.anomaly-priority.medium { background: rgba(251,191,36,0.15); color: var(--warning); }

.anomaly-title { font-size: 13px; font-weight: 600; margin-bottom: 2px; }
.anomaly-meta { font-size: 11px; color: var(--text-muted); }

.anomaly-status {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
}
.anomaly-status.pending { background: rgba(251,191,36,0.15); color: var(--warning); }
.anomaly-status.investigating { background: rgba(108,142,245,0.15); color: var(--accent); }

.explainability-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 20px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 2;
}
.explainability-card ul { list-style: none; margin-top: 8px; }
.explainability-card strong { color: var(--text-primary); }
</style>
