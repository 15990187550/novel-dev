<template>
  <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
    <OutlineEmptyState
      v-if="!detail"
      title="选择左侧大纲开始查看"
      description="选中总纲或某一卷后，这里会显示当前版本与结构化信息。"
    />

    <OutlineEmptyState
      v-else-if="detail.status === 'missing'"
      :title="detail.emptyTitle || '当前卷尚未生成卷纲'"
      :description="detail.emptyDescription || '可以直接在下方输入修改意见，要求系统先生成本卷卷纲。'"
    />

    <div v-else class="space-y-5">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">
            {{ detail.outlineType === 'synopsis' ? 'Synopsis' : 'Volume Outline' }}
          </div>
          <h3 class="mt-2 text-2xl font-semibold text-gray-900">{{ detail.title || '未命名大纲' }}</h3>
          <p v-if="detail.summary" class="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-600">
            {{ detail.summary }}
          </p>
        </div>
        <span class="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
          {{ detail.statusLabel || '待处理' }}
        </span>
      </div>

      <div v-if="detail.meta?.length" class="grid gap-3 md:grid-cols-3">
        <div
          v-for="item in detail.meta"
          :key="item.label"
          class="rounded-2xl bg-gray-50 px-4 py-3"
        >
          <div class="text-xs uppercase tracking-wide text-gray-400">{{ item.label }}</div>
          <div class="mt-1 text-sm font-medium text-gray-800">{{ item.value }}</div>
        </div>
      </div>

      <div v-if="detail.tags?.length" class="flex flex-wrap gap-2">
        <span
          v-for="tag in detail.tags"
          :key="tag"
          class="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
        >
          {{ tag }}
        </span>
      </div>

      <div v-if="detail.sections?.length" class="grid gap-4 xl:grid-cols-2">
        <article
          v-for="section in detail.sections"
          :key="section.title"
          class="rounded-2xl border border-gray-200 px-4 py-4"
        >
          <h4 class="text-sm font-semibold text-gray-900">{{ section.title }}</h4>
          <p v-if="section.text" class="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-600">
            {{ section.text }}
          </p>
          <ul v-if="section.items?.length" class="mt-3 space-y-2 text-sm leading-6 text-gray-600">
            <li v-for="item in section.items" :key="item">• {{ item }}</li>
          </ul>
        </article>
      </div>

      <div v-if="detail.chapters?.length" class="rounded-2xl border border-gray-200 px-4 py-4">
        <h4 class="text-sm font-semibold text-gray-900">章节摘要</h4>
        <div class="mt-3 space-y-3">
          <div
            v-for="chapter in detail.chapters"
            :key="chapter.chapter_id || chapter.chapter_number || chapter.title"
            class="rounded-2xl bg-gray-50 px-4 py-3"
          >
            <div class="text-sm font-medium text-gray-900">
              {{ chapter.title || `第${chapter.chapter_number}章` }}
            </div>
            <p v-if="chapter.summary" class="mt-1 whitespace-pre-wrap text-sm leading-6 text-gray-600">
              {{ chapter.summary }}
            </p>
          </div>
        </div>
      </div>

      <details v-if="detail.rawSnapshot" class="rounded-2xl border border-gray-200 px-4 py-3">
        <summary class="cursor-pointer text-sm font-medium text-gray-700">查看原始结构化结果</summary>
        <pre class="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-2xl bg-gray-50 p-3 text-xs leading-6 text-gray-600">{{ JSON.stringify(detail.rawSnapshot, null, 2) }}</pre>
      </details>
    </div>
  </section>
</template>

<script setup>
import OutlineEmptyState from './OutlineEmptyState.vue'

defineProps({
  detail: {
    type: Object,
    default: null,
  },
})
</script>
