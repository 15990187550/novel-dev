<template>
  <section class="dashboard-next-actions">
    <header class="dashboard-section-header">
      <div>
        <p class="dashboard-section-header__eyebrow">Next Actions</p>
        <h2 class="dashboard-section-header__title">{{ title }}</h2>
      </div>
      <p class="dashboard-section-header__meta">{{ subtitle }}</p>
    </header>

    <div class="dashboard-next-actions__grid">
      <button
        v-for="action in normalizedActions"
        :key="action.slot"
        type="button"
        class="dashboard-action-card"
        :class="[`is-${action.variant}`]"
        @click="emitAction(action.source)"
      >
        <span class="dashboard-action-card__label">{{ action.label }}</span>
        <strong class="dashboard-action-card__title">{{ action.title }}</strong>
        <p class="dashboard-action-card__reason">{{ action.reason }}</p>
        <span v-if="action.route" class="dashboard-action-card__route">{{ action.route }}</span>
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const emit = defineEmits(['action'])

const props = defineProps({
  title: { type: String, default: '下一步操作' },
  subtitle: { type: String, default: '优先推进主动作，再补充辅助动作' },
  primary: { type: Object, default: null },
  secondary: { type: Object, default: null },
})

function normalizeAction(action, slot, variant) {
  if (!action) return null
  return {
    slot,
    variant,
    label: action.label || (variant === 'primary' ? '主操作' : '辅助操作'),
    title: action.title || action.name || action.key || '未命名操作',
    reason: action.reason || action.description || '',
    route: action.route || '',
    source: action,
  }
}

const normalizedActions = computed(() => [
  normalizeAction(props.primary, 'primary', 'primary'),
  normalizeAction(props.secondary, 'secondary', 'secondary'),
].filter(Boolean))

function emitAction(action) {
  emit('action', action)
}
</script>

