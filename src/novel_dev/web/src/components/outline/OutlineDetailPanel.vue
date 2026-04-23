<template>
  <section class="surface-card p-5">
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

    <div v-if="detail?.status === 'missing' && createAction" class="outline-detail-create-card mt-4 px-4 py-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ createAction.title || '立即创建' }}</div>
          <p class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
            {{ createAction.description || '根据当前阶段直接生成对应大纲内容。' }}
          </p>
          <p v-if="createAction.disabledReason" class="outline-detail-create-card__warning mt-2 text-xs leading-5">
            {{ createAction.disabledReason }}
          </p>
        </div>
        <button
          type="button"
          class="outline-detail-create-card__action rounded-full px-5 py-2.5 text-sm font-medium transition duration-200 disabled:cursor-not-allowed"
          :disabled="createAction.disabled || createAction.loading"
          @click="$emit('create')"
        >
          {{ createAction.loading ? '创建中...' : (createAction.label || '一键创建') }}
        </button>
      </div>
    </div>

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
        <span class="outline-detail-status rounded-full px-3 py-1 text-xs font-medium">
          {{ detail.statusLabel || '待处理' }}
        </span>
      </div>

      <div v-if="detail.meta?.length" class="grid gap-3 md:grid-cols-3">
        <div
          v-for="item in detail.meta"
          :key="item.label"
          class="outline-detail-meta-card rounded-2xl border px-4 py-3"
        >
          <div class="text-xs uppercase tracking-wide text-gray-400 dark:text-gray-500">{{ item.label }}</div>
          <div class="mt-1 text-sm font-medium text-gray-800 dark:text-gray-200">{{ item.value }}</div>
        </div>
      </div>

      <div v-if="detail.tags?.length" class="flex flex-wrap gap-2">
        <span
          v-for="tag in detail.tags"
          :key="tag"
          class="outline-detail-tag rounded-full px-3 py-1 text-xs font-medium"
        >
          {{ tag }}
        </span>
      </div>

      <div v-if="detail.sections?.length" class="grid gap-4 xl:grid-cols-2">
        <article
          v-for="section in detail.sections"
          :key="section.title"
          class="outline-detail-section-card rounded-2xl border px-4 py-4"
        >
          <h4 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ section.title }}</h4>
          <p v-if="section.text" class="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-600 dark:text-gray-300">
            {{ section.text }}
          </p>
          <ul v-if="section.items?.length" class="mt-3 space-y-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
            <li v-for="item in section.items" :key="item">• {{ item }}</li>
          </ul>
        </article>
      </div>

      <div v-if="detail.chapters?.length" class="outline-detail-section-card rounded-2xl border px-4 py-4">
        <h4 class="text-sm font-semibold text-gray-900 dark:text-gray-100">章节摘要</h4>
        <div class="mt-3 space-y-3">
          <div
            v-for="chapter in detail.chapters"
            :key="chapter.chapter_id || chapter.chapter_number || chapter.title"
            class="outline-detail-meta-card rounded-2xl border px-4 py-3"
          >
            <div class="text-sm font-medium text-gray-900 dark:text-gray-100">
              {{ chapter.title || `第${chapter.chapter_number}章` }}
            </div>
            <p v-if="chapter.summary" class="mt-1 whitespace-pre-wrap text-sm leading-6 text-gray-600 dark:text-gray-300">
              {{ chapter.summary }}
            </p>
          </div>
        </div>
      </div>

      <details v-if="detail.rawSnapshot" class="outline-detail-section-card rounded-2xl border px-4 py-3">
        <summary class="cursor-pointer text-sm font-medium text-gray-700 dark:text-gray-200">查看原始结构化结果</summary>
        <pre class="outline-detail-raw mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-2xl p-3 text-xs leading-6">{{ JSON.stringify(detail.rawSnapshot, null, 2) }}</pre>
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
  createAction: {
    type: Object,
    default: null,
  },
})

defineEmits(['create'])
</script>

<style scoped>
.outline-detail-create-card,
.outline-detail-meta-card,
.outline-detail-section-card,
.outline-detail-raw {
  border-color: var(--app-border);
  background: var(--app-surface);
}

.outline-detail-create-card {
  border: 1px solid var(--app-border);
  border-radius: 1rem;
}

.outline-detail-create-card__warning {
  color: color-mix(in srgb, #f59e0b 72%, var(--app-text));
}

.outline-detail-create-card__action {
  border: 1px solid color-mix(in srgb, var(--app-accent, #14b8a6) 38%, transparent);
  background: color-mix(in srgb, var(--app-accent, #14b8a6) 78%, white 10%);
  color: #fff;
}

.outline-detail-create-card__action:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.04);
}

.outline-detail-create-card__action:disabled {
  opacity: 0.5;
}

.outline-detail-status,
.outline-detail-tag {
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
}

.outline-detail-raw {
  color: var(--app-text-muted);
}
</style>
