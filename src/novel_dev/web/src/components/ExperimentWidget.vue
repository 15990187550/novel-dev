<template>
  <div class="experiment-widget" data-testid="experiment-widget">
    <aside class="judge-status-bar" data-testid="judge-status-chip">
      <span class="text-xs text-gray-500">Judge 状态:</span>
      <span :class="['judge-status-indicator', judgeEnabled ? 'enabled' : 'disabled']">
        {{ judgeEnabled ? '✓ 启用' : '✗ 禁用' }}
      </span>
      <span v-if="judgeActiveVersion" class="text-xs judge-active-version">活跃 prompt: {{ judgeActiveVersion }}</span>
      <span v-if="judgeDegradedReason" class="judge-degraded-chip" data-testid="judge-degraded-chip">⚠ {{ judgeDegradedReason }}</span>
    </aside>

    <h3>A/B 实验状态</h3>
    <div v-if="loading">加载中…</div>
    <div v-else-if="decisions.length === 0" data-testid="empty-state">暂无 A/B 实验</div>
    <div v-else>
      <div data-testid="recent-accepted-count">
        最近 24h 自动采纳: <strong>{{ acceptedCount }}</strong>
      </div>
      <div data-testid="recent-events">
        <div v-for="d in decisions.slice(0, 5)" :key="d.id" class="event-row">
          <span class="action">{{ d.action }}</span>
          <span class="time">{{ formatTime(d.decision_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { getRecentABDecisions, fetchJudgePromptVersions, fetchJudgeCallStats } from '@/api';

const decisions = ref([]);
const loading = ref(true);

const judgeEnabled = ref(true);
const judgeActiveVersion = ref(null);
const judgeDegradedReason = ref(null);

const acceptedCount = computed(() =>
  decisions.value.filter(d => d.action === 'accept').length
);

function formatTime(iso) {
  return new Date(iso).toLocaleString();
}

onMounted(async () => {
  try {
    const data = await getRecentABDecisions(60 * 24);
    decisions.value = data.decisions || [];
  } catch {
    decisions.value = [];
  } finally {
    loading.value = false;
  }
});

onMounted(async () => {
  try {
    const versions = await fetchJudgePromptVersions();
    const active = versions.find((v) => v.is_active);
    if (active) judgeActiveVersion.value = active.version;
    else judgeEnabled.value = false;
  } catch (e) {
    judgeDegradedReason.value = '连接失败';
  }
  try {
    const stats = await fetchJudgeCallStats({ window_days: 30 });
    if (stats.total_cost_usd > 0.40) {  // 80% of 0.50 cap
      judgeDegradedReason.value = '接近 cost cap';
    }
  } catch (e) {
    // ignore
  }
});
</script>

<style scoped>
.experiment-widget { padding: 12px; border: 1px solid #e0e0e0; border-radius: 6px; }
.event-row { display: flex; justify-content: space-between; padding: 4px 0; }
.action { font-weight: bold; }
.judge-status-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 6px 8px;
  background: #f8fafc;
  border-radius: 4px;
  margin-bottom: 8px;
  font-size: 12px;
}
.judge-status-indicator.enabled {
  color: #16a34a;
  font-weight: bold;
}
.judge-status-indicator.disabled {
  color: #dc2626;
}
.judge-degraded-chip {
  background: #fef3c7;
  color: #92400e;
  padding: 2px 6px;
  border-radius: 3px;
}
</style>
