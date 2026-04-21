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
        @click="emitAction(action.key)"
      >
        <span class="dashboard-action-card__label">{{ action.label }}</span>
        <strong class="dashboard-action-card__title">{{ action.title }}</strong>
        <p class="dashboard-action-card__reason">{{ action.reason }}</p>
        <p v-if="action.detail" class="dashboard-action-card__detail">{{ action.detail }}</p>
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
  actions: { type: Array, default: () => [] },
  primary: { type: Object, default: null },
  secondary: { type: Object, default: null },
})

function normalizeAction(action, slot, variant) {
  if (!action) return null
  return {
    slot,
    variant,
    key: action.key || '',
    label: action.label || (variant === 'primary' ? '主操作' : '次操作'),
    title: action.label || action.title || action.name || action.key || '未命名操作',
    reason: action.reason || action.description || '',
    detail: action.detail || '',
    route: action.route || '',
  }
}

const normalizedActions = computed(() => {
  const sourceActions = props.actions.length
    ? props.actions
    : [props.primary, props.secondary].filter(Boolean)

  return sourceActions
    .map((action, index) => normalizeAction(action, index === 0 ? 'primary' : 'secondary', index === 0 ? 'primary' : 'secondary'))
    .filter(Boolean)
    .slice(0, 2)
})

function emitAction(actionKey) {
  emit('action', actionKey)
}
</script>
