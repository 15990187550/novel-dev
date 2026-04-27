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

      <div v-if="detail.review || detail.canReview" class="outline-detail-review rounded-2xl border px-4 py-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="text-sm font-semibold text-gray-900 dark:text-gray-100">
              大纲评价：{{ detail.review?.overall ?? '未评分' }}
            </div>
            <p v-if="detail.review?.feedback" class="mt-1 whitespace-pre-wrap text-sm leading-6">
              {{ detail.review.feedback }}
            </p>
            <p v-else class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
              当前大纲还没有评分，可以手动触发一次评价，系统会给出维度评分和优化建议。
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="outline-detail-link"
              :disabled="reviewing"
              @click="$emit('review')"
            >
              {{ reviewing ? '评价中...' : (detail.review ? '重新评价' : '评价大纲') }}
            </button>
            <button
              v-if="detail.review?.suggestion"
              type="button"
              class="outline-detail-link"
              @click="$emit('apply-suggestion', detail.review.suggestion)"
            >
              复制建议到输入框
            </button>
          </div>
        </div>
        <div v-if="detail.review?.dimensions?.length" class="mt-3 grid gap-2 md:grid-cols-3">
          <div
            v-for="dimension in detail.review.dimensions"
            :key="dimension.label"
            class="outline-detail-meta-card rounded-2xl border px-3 py-2"
          >
            <div class="text-xs uppercase tracking-wide text-gray-400">{{ dimension.label }}</div>
            <div class="mt-1 text-sm font-medium">{{ dimension.value ?? '未知' }}</div>
          </div>
        </div>
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

      <div v-if="detail.notices?.length" class="space-y-3">
        <div
          v-for="notice in detail.notices"
          :key="notice.title"
          class="outline-detail-notice rounded-2xl border px-4 py-3"
        >
          <div class="text-sm font-semibold">{{ notice.title }}</div>
          <p class="mt-1 whitespace-pre-wrap text-sm leading-6">{{ notice.text }}</p>
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
          <div class="flex items-center justify-between gap-3">
            <h4 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ section.title }}</h4>
            <button
              v-if="section.detailItems?.length"
              type="button"
              class="outline-detail-link"
              @click="openSectionDetail(section)"
            >
              查看详情
            </button>
          </div>
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

    <Teleport to="body">
      <div
        v-if="activeSection"
        class="outline-detail-modal"
        role="dialog"
        aria-modal="true"
        :aria-label="`${activeSection.title}详情`"
        @click.self="closeSectionDetail"
      >
        <section class="outline-detail-modal__panel">
          <div class="outline-detail-modal__header">
            <h3>{{ activeSection.title }}</h3>
            <button type="button" class="outline-detail-modal__close" aria-label="关闭详情" @click="closeSectionDetail">关闭</button>
          </div>
          <ul class="outline-detail-modal__list">
            <li v-for="item in activeSection.detailItems" :key="item">{{ item }}</li>
          </ul>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<script setup>
import { ref } from 'vue'
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
  reviewing: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['create', 'review', 'apply-suggestion'])

const activeSection = ref(null)

function openSectionDetail(section) {
  activeSection.value = section
}

function closeSectionDetail() {
  activeSection.value = null
}
</script>

<style scoped>
.outline-detail-create-card,
.outline-detail-meta-card,
.outline-detail-notice,
.outline-detail-review,
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

.outline-detail-link {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
  font-size: 0.75rem;
  font-weight: 600;
  transition: border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
}

.outline-detail-link:hover {
  border-color: color-mix(in srgb, var(--app-accent, #14b8a6) 45%, var(--app-border));
  color: var(--app-text);
  transform: translateY(-1px);
}

.outline-detail-link:disabled {
  cursor: not-allowed;
  opacity: 0.55;
  transform: none;
}

.outline-detail-notice {
  border-color: color-mix(in srgb, #f59e0b 46%, var(--app-border));
  background: color-mix(in srgb, #f59e0b 10%, var(--app-surface));
  color: color-mix(in srgb, #f59e0b 72%, var(--app-text));
}

.outline-detail-raw {
  color: var(--app-text-muted);
}

.outline-detail-modal {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: rgb(15 23 42 / 0.45);
}

.outline-detail-modal__panel {
  width: min(760px, 100%);
  max-height: min(78vh, 720px);
  overflow: auto;
  border: 1px solid var(--app-border);
  border-radius: 1rem;
  background: var(--app-surface);
  box-shadow: 0 22px 70px rgb(15 23 42 / 0.22);
}

.outline-detail-modal__header {
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border-bottom: 1px solid var(--app-border);
  background: var(--app-surface);
  padding: 1rem 1.25rem;
}

.outline-detail-modal__header h3 {
  margin: 0;
  color: var(--app-text);
  font-size: 1rem;
  font-weight: 700;
}

.outline-detail-modal__close {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
  font-size: 0.75rem;
  font-weight: 600;
}

.outline-detail-modal__list {
  margin: 0;
  padding: 1rem 1.25rem 1.25rem;
  list-style: none;
}

.outline-detail-modal__list li {
  padding: 0.8rem 0;
  color: var(--app-text);
  font-size: 0.875rem;
  line-height: 1.7;
  white-space: pre-wrap;
}

.outline-detail-modal__list li + li {
  border-top: 1px solid var(--app-border);
}
</style>
