<template>
  <div class="experiment-widget" data-testid="experiment-widget">
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
import { getRecentABDecisions } from '@/api';

const decisions = ref([]);
const loading = ref(true);

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
</script>

<style scoped>
.experiment-widget { padding: 12px; border: 1px solid #e0e0e0; border-radius: 6px; }
.event-row { display: flex; justify-content: space-between; padding: 4px 0; }
.action { font-weight: bold; }
</style>
