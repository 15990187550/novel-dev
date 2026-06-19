<template>
  <div class="experiment-view" data-testid="experiment-view">
    <h2>A/B 实验时间线</h2>

    <nav class="tab-bar">
      <button
        v-for="t in tabs"
        :key="t.id"
        :class="['tab', { 'tab--active': activeTab === t.id }]"
        :data-test="'tab'"
        :data-test-tab="t.id"
        @click="activeTab = t.id"
      >
        {{ t.label }}
      </button>
    </nav>

    <!-- Overview tab: existing table -->
    <section v-if="activeTab === 'overview'">
      <div v-if="loading">加载中…</div>
      <table v-else>
        <thead>
          <tr><th>ID</th><th>Agent</th><th>Baseline</th><th>Challenger</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in experiments" :key="e.id" data-testid="experiment-row">
            <td>{{ e.id }}</td>
            <td>{{ e.agent_name }}</td>
            <td>{{ e.baseline_version }}</td>
            <td>{{ e.challenger_version }}</td>
            <td><span :data-testid="`status-${e.status}`">{{ e.status }}</span></td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- Samples tab: placeholder -->
    <section v-else-if="activeTab === 'samples'">
      <p class="text-gray-500">样本浏览(后续实现)</p>
    </section>

    <!-- History tab: placeholder -->
    <section v-else-if="activeTab === 'history'">
      <p class="text-gray-500">决策历史(后续实现)</p>
    </section>

    <!-- Judge tab: NEW -->
    <section v-else-if="activeTab === 'judge'" class="judge-tab">
      <h3>Judge 状态</h3>
      <div class="metric-cards">
        <div class="metric-card">
          <h4>平均一致率</h4>
          <p>{{ judgeMetrics.avgAgreementRate?.toFixed(2) || '—' }}</p>
        </div>
        <div class="metric-card">
          <h4>本月调用</h4>
          <p>{{ judgeMetrics.monthlyCalls || 0 }}</p>
        </div>
        <div class="metric-card">
          <h4>本月成本</h4>
          <p>${{ judgeMetrics.monthlyCost?.toFixed(4) || '0.0000' }}</p>
        </div>
      </div>
      <div class="active-judge-prompt">
        <h4>当前 active judge prompt</h4>
        <p>版本: {{ activeJudgePrompt?.version || '—' }}</p>
        <p>一致率: {{ activeJudgePrompt?.last_score?.toFixed(2) || '—' }}</p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { listABExperiments, fetchJudgeCallStats, fetchJudgePromptVersions } from '@/api';

const experiments = ref([]);
const loading = ref(true);

const tabs = [
  { id: 'overview', label: '概览' },
  { id: 'samples', label: '样本' },
  { id: 'history', label: '决策历史' },
  { id: 'judge', label: 'judge' },
];
const activeTab = ref('overview');

const judgeMetrics = ref({ avgAgreementRate: null, monthlyCalls: 0, monthlyCost: 0 });
const activeJudgePrompt = ref(null);

onMounted(async () => {
  try {
    const data = await listABExperiments();
    experiments.value = data.tests || [];
  } catch {
    experiments.value = [];
  } finally {
    loading.value = false;
  }
  try {
    const stats = await fetchJudgeCallStats({ window_days: 14 });
    judgeMetrics.value.monthlyCalls = stats.total_calls;
    judgeMetrics.value.monthlyCost = stats.total_cost_usd;
  } catch (e) {
    console.warn('judge stats fetch failed', e);
  }
  try {
    const versions = await fetchJudgePromptVersions();
    activeJudgePrompt.value = versions.find((v) => v.is_active) || null;
  } catch (e) {
    console.warn('judge prompt versions fetch failed', e);
  }
});
</script>

<style scoped>
.tab-bar {
  @apply flex gap-2 mb-3 border-b border-gray-200 dark:border-gray-700;
}
.tab {
  @apply px-3 py-2 text-sm text-gray-600 dark:text-gray-300;
}
.tab--active {
  @apply text-teal-700 border-b-2 border-teal-700;
}
.metric-cards {
  @apply grid grid-cols-3 gap-3 mb-4;
}
.metric-card {
  @apply rounded-md border border-gray-200 dark:border-gray-700 p-3;
}
.metric-card h4 {
  @apply text-xs text-gray-500 mb-1;
}
.metric-card p {
  @apply text-lg font-semibold;
}
.active-judge-prompt {
  @apply rounded-md border border-gray-200 dark:border-gray-700 p-3;
}
</style>