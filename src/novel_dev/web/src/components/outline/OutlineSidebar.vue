<template>
  <aside class="surface-card surface-card--soft p-4">
    <div class="mb-4">
      <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Outline</div>
      <h2 class="mt-2 text-xl font-semibold text-gray-900 dark:text-gray-100">大纲规划</h2>
      <p class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">总纲与各卷卷纲统一在这里查看和继续改稿。</p>
    </div>

    <div v-if="!items.length" class="outline-sidebar-empty px-4 py-6 text-sm">
      暂无可用大纲项
    </div>

    <div v-else class="space-y-2">
      <button
        v-for="item in items"
        :key="item.key || `${item.outline_type}:${item.outline_ref}`"
        type="button"
        class="outline-sidebar-item w-full rounded-2xl border px-4 py-3 text-left transition duration-200"
        :class="item.isCurrent
          ? 'outline-sidebar-item--current'
          : 'outline-sidebar-item--idle'"
        @click="$emit('select', item)"
      >
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-sm font-semibold">{{ item.title || '未命名大纲' }}</div>
            <p class="mt-1 line-clamp-2 text-xs leading-5" :class="item.isCurrent ? 'outline-sidebar-item__summary--current' : 'outline-sidebar-item__summary--idle'">
              {{ item.summary || item.summary_hint || fallbackSummary(item) }}
            </p>
          </div>
          <span
            class="outline-sidebar-item__status shrink-0 rounded-full px-2 py-1 text-[11px] font-medium"
            :class="item.isCurrent ? 'outline-sidebar-item__status--current' : 'outline-sidebar-item__status--idle'"
          >
            {{ item.statusLabel || '待处理' }}
          </span>
        </div>
      </button>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  items: {
    type: Array,
    default: () => [],
  },
})

defineEmits(['select'])

function fallbackSummary(item) {
  if (item?.outline_type === 'synopsis') return '查看总纲脉络、主题与人物弧光。'
  if (item?.status === 'missing') return '当前卷还没有卷纲，可以直接发起生成或修改。'
  return '查看当前卷纲详情和最近修改结果。'
}
</script>

<style scoped>
.outline-sidebar-empty {
  border: 1px dashed var(--app-border);
  border-radius: 1rem;
  background: var(--app-surface);
  color: var(--app-text-muted);
}

.outline-sidebar-item {
  transition-property: transform, border-color, background-color, color;
}

.outline-sidebar-item--idle {
  border-color: var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
}

.outline-sidebar-item--idle:hover {
  transform: translateY(-2px);
  border-color: var(--app-border-strong);
  background: var(--app-surface-soft);
}

.outline-sidebar-item--current {
  border-color: color-mix(in srgb, var(--app-accent, #14b8a6) 40%, var(--app-border));
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--app-accent, #14b8a6) 14%, var(--app-surface)) 0%, var(--app-surface-soft) 100%);
  color: var(--app-text);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.outline-sidebar-item__summary--idle {
  color: var(--app-text-muted);
}

.outline-sidebar-item__summary--current {
  color: color-mix(in srgb, var(--app-text) 75%, var(--app-text-muted));
}

.outline-sidebar-item__status--idle {
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
}

.outline-sidebar-item__status--current {
  background: color-mix(in srgb, var(--app-accent, #14b8a6) 22%, var(--app-surface));
  color: var(--app-text);
}
</style>
