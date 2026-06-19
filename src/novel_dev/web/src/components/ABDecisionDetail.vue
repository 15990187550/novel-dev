<template>
  <div class="ab-decision-detail">
    <header class="mb-3 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-800 dark:text-gray-100">决策详情</h3>
      <span class="text-xs text-gray-500">ID: {{ decision.id }}</span>
    </header>

    <dl class="grid grid-cols-2 gap-2 text-xs mb-4">
      <dt class="text-gray-500">触发时间</dt>
      <dd>{{ formatTime(decision.decision_at) }}</dd>
      <dt class="text-gray-500">实验 ID</dt>
      <dd>{{ decision.experiment_id }}</dd>
      <dt class="text-gray-500">Action</dt>
      <dd>{{ decision.action }}</dd>
    </dl>

    <section class="mb-4">
      <h4 class="text-xs font-semibold text-gray-700 dark:text-gray-200 mb-1">硬指标</h4>
      <ul class="text-xs">
        <li v-for="(score, version) in decision.scores" :key="version">
          <code class="text-teal-700">{{ version }}</code>: {{ score.toFixed(2) }}
        </li>
      </ul>
    </section>

    <section v-if="decision.judge_triggered" class="judge-section">
      <h4 class="text-xs font-semibold text-teal-700 mb-1">Judge 评分(tie-breaker)</h4>
      <p class="text-xs text-gray-500 mb-2">模型: {{ decision.judge_model }}</p>
      <table class="w-full text-xs">
        <thead>
          <tr class="text-left text-gray-500">
            <th class="pr-2">维度</th>
            <th class="pr-2">baseline</th>
            <th class="pr-2">challenger</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(score, dim) in decision.judge_scores_baseline" :key="dim">
            <td class="pr-2">{{ dim }}</td>
            <td class="pr-2">{{ score.toFixed(2) }}</td>
            <td class="pr-2">{{ (decision.judge_scores_challenger[dim] || 0).toFixed(2) }}</td>
          </tr>
          <tr class="font-semibold">
            <td class="pr-2">tie_breaker</td>
            <td class="pr-2">{{ decision.judge_tie_breaker_baseline?.toFixed(2) }}</td>
            <td class="pr-2">{{ decision.judge_tie_breaker_challenger?.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
      <div class="mt-2 text-xs">
        <p><strong>baseline 理由:</strong> {{ decision.judge_rationale_baseline }}</p>
        <p><strong>challenger 理由:</strong> {{ decision.judge_rationale_challenger }}</p>
      </div>
    </section>

    <section v-else-if="decision.judge_error" class="degraded-notice">
      <p class="text-xs text-amber-700">Judge 未介入 — {{ decision.judge_error }}</p>
    </section>

    <section v-else class="text-xs text-gray-500">
      Judge 未介入(硬指标差距 &gt; 1%)
    </section>

    <footer class="mt-3 text-xs text-gray-500">
      最终决策: <strong class="text-teal-700">{{ decision.meta?.winner || decision.winner || '—' }}</strong>
    </footer>
  </div>
</template>

<script setup>
import { formatBeijingDateTime } from '@/utils/time.js'

defineProps({ decision: { type: Object, required: true } })

function formatTime(value) {
  return formatBeijingDateTime(value)
}
</script>

<style scoped>
.ab-decision-detail {
  @apply rounded-[1rem] border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-900 p-4 max-w-md;
}
.judge-section {
  @apply rounded-md bg-teal-50 dark:bg-teal-900/20 p-3;
}
.degraded-notice {
  @apply rounded-md bg-amber-50 dark:bg-amber-900/20 p-3;
}
</style>
