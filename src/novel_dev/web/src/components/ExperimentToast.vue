<template>
  <div class="experiment-toast-container" data-testid="experiment-toast-container">
    <div v-for="t in activeToasts" :key="t.id" :data-testid="`toast-${t.action}`" class="toast">
      {{ t.message }}
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import { getRecentABDecisions } from '@/api';

const activeToasts = ref([]);
const seenIds = new Set();
let pollTimer = null;

const ACTION_MESSAGES = {
  accept: '已自动采纳为 active',
  early_stopped: '已早停,baseline 保持 active',
  timeout: '实验超时未达显著,已结束',
  rolled_back: '表现下降,已回滚',
  rollback_no_target: '表现下降,无可回滚版本',
};

function pushToast(d) {
  if (seenIds.has(d.id)) return;
  seenIds.add(d.id);
  activeToasts.value.push({
    id: d.id,
    action: d.action,
    message: `${d.experiment_id}: ${ACTION_MESSAGES[d.action] || d.action}`,
  });
  setTimeout(() => {
    activeToasts.value = activeToasts.value.filter(t => t.id !== d.id);
  }, 5000);
}

async function poll() {
  try {
    const data = await getRecentABDecisions(5);
    const critical = (data.decisions || []).filter(d =>
      ['accept', 'early_stopped', 'timeout', 'rolled_back', 'rollback_no_target'].includes(d.action)
    );
    critical.forEach(pushToast);
  } catch {}
}

onMounted(() => {
  poll();
  pollTimer = setInterval(poll, 30000);
});

onUnmounted(() => clearInterval(pollTimer));
</script>

<style scoped>
.experiment-toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; }
.toast { background: #333; color: white; padding: 12px 16px; margin-bottom: 8px; border-radius: 4px; }
</style>
