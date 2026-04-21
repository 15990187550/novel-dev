<template>
  <section class="dashboard-status-cards">
    <RouterLink
      v-for="panel in normalizedPanels"
      :key="panel.id"
      :to="panel.route"
      class="dashboard-status-card"
      :class="{ 'is-error': panel.panelState === 'error' }"
    >
      <span class="dashboard-status-card__label">{{ panel.label }}</span>
      <strong class="dashboard-status-card__title">{{ panel.title }}</strong>
      <p class="dashboard-status-card__detail">{{ panel.detail }}</p>
      <span class="dashboard-status-card__meta">{{ panel.meta }}</span>
    </RouterLink>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  panels: { type: Array, default: () => [] },
})

const normalizedPanels = computed(() => props.panels.map((panel, index) => ({
  id: panel?.id || `panel-${index}`,
  label: panel?.label || panel?.name || '状态卡',
  title: panel?.title || panel?.summary || panel?.value || panel?.count || '暂无数据',
  detail: panel?.detail || panel?.description || panel?.hint || '',
  meta: panel?.meta || panel?.route || '',
  route: panel?.route || '/dashboard',
  panelState: panel?.panelState || panel?.state || 'ok',
})))
</script>

