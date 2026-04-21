<template>
  <aside class="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
    <div class="mb-4">
      <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Outline</div>
      <h2 class="mt-2 text-xl font-semibold text-gray-900">大纲规划</h2>
      <p class="mt-1 text-sm leading-6 text-gray-500">总纲与各卷卷纲统一在这里查看和继续改稿。</p>
    </div>

    <div v-if="!items.length" class="rounded-2xl border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">
      暂无可用大纲项
    </div>

    <div v-else class="space-y-2">
      <button
        v-for="item in items"
        :key="item.key || `${item.outline_type}:${item.outline_ref}`"
        type="button"
        class="w-full rounded-2xl border px-4 py-3 text-left transition"
        :class="item.isCurrent
          ? 'border-slate-900 bg-slate-900 text-white shadow-sm'
          : 'border-gray-200 bg-white text-gray-900 hover:border-slate-300 hover:bg-slate-50'"
        @click="$emit('select', item)"
      >
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-sm font-semibold">{{ item.title || '未命名大纲' }}</div>
            <p class="mt-1 line-clamp-2 text-xs leading-5" :class="item.isCurrent ? 'text-slate-200' : 'text-gray-500'">
              {{ item.summary || item.summary_hint || fallbackSummary(item) }}
            </p>
          </div>
          <span
            class="shrink-0 rounded-full px-2 py-1 text-[11px] font-medium"
            :class="item.isCurrent ? 'bg-white/15 text-white' : 'bg-gray-100 text-gray-600'"
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
