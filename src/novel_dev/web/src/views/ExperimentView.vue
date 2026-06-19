<template>
  <div class="experiment-view" data-testid="experiment-view">
    <h2>A/B 实验时间线</h2>
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { listABExperiments } from '@/api';

const experiments = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await listABExperiments();
    experiments.value = data.tests || [];
  } catch {
    experiments.value = [];
  } finally {
    loading.value = false;
  }
});
</script>
