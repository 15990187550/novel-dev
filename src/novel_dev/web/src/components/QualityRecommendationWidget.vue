<template>
  <div
    class="quality-recommendation-widget"
    :class="[`quality-recommendation-widget--${stateModifier}`, { 'is-error': hasError }]"
    data-testid="quality-recommendation-widget"
  >
    <header class="quality-recommendation-widget__header">
      <div class="quality-recommendation-widget__title">
        <p class="quality-recommendation-widget__eyebrow">质量推荐</p>
        <h3 class="quality-recommendation-widget__chapter">章节 {{ chapterId }}</h3>
      </div>
      <span
        v-if="!loading && !hasError"
        class="quality-recommendation-widget__badge"
        :class="`quality-recommendation-widget__badge--${recommendationType}`"
        data-testid="recommendation-badge"
      >
        <span class="quality-recommendation-widget__badge-dot" aria-hidden="true" />
        {{ recommendationLabel() }}
      </span>
      <span v-else-if="loading" class="quality-recommendation-widget__spinner" aria-label="加载中" />
    </header>

    <p
      v-if="hasError"
      class="quality-recommendation-widget__error"
      data-testid="recommendation-error"
    >
      加载推荐结果失败:{{ errorMessage }}
    </p>

    <template v-else-if="!loading && recommendation">
      <p v-if="isStopAndInspect" class="quality-recommendation-widget__alert" data-testid="stop-and-inspect-alert">
        需人工介入
      </p>

      <div class="quality-recommendation-widget__confidence">
        <div class="quality-recommendation-widget__confidence-label">
          <span>置信度</span>
          <span data-testid="recommendation-confidence">{{ confidencePercent }}</span>
        </div>
        <div class="quality-recommendation-widget__confidence-track" :title="confidencePercent">
          <div
            class="quality-recommendation-widget__confidence-fill"
            :class="`quality-recommendation-widget__confidence-fill--${recommendationType}`"
            :style="{ width: `${confidencePercentValue}%` }"
          />
        </div>
      </div>

      <div v-if="suggestedActions.length" class="quality-recommendation-widget__actions">
        <p class="quality-recommendation-widget__section-label">建议操作</p>
        <ul class="quality-recommendation-widget__action-list" data-testid="suggested-actions">
          <li
            v-for="(action, index) in suggestedActions"
            :key="`${action.type || 'action'}-${index}`"
            class="quality-recommendation-widget__action-item"
          >
            <div class="quality-recommendation-widget__action-row">
              <span class="quality-recommendation-widget__action-type">{{ actionTypeLabel(action.type) }}</span>
              <span
                v-if="action.estimated_iterations != null"
                class="quality-recommendation-widget__action-iterations"
              >
                ≈ {{ action.estimated_iterations }} 轮
              </span>
            </div>
            <div v-if="action.scope && action.scope.length" class="quality-recommendation-widget__scope">
              <span
                v-for="scope in action.scope"
                :key="scope"
                class="quality-recommendation-widget__chip"
              >
                {{ scopeLabel(scope) }}
              </span>
            </div>
            <p v-if="action.reason" class="quality-recommendation-widget__action-reason">{{ action.reason }}</p>
          </li>
        </ul>
      </div>
      <p v-else class="quality-recommendation-widget__empty">无额外操作建议</p>

      <section v-if="rootCause" data-testid="root-cause-section" class="quality-recommendation-widget__root-cause">
        <p class="quality-recommendation-widget__section-label">上轮根因分析</p>
        <p data-testid="root-cause-summary" class="quality-recommendation-widget__root-cause-summary">
          {{ rootCause.summary }}
        </p>
        <ul v-if="rootCause.suggested_actions && rootCause.suggested_actions.length" class="quality-recommendation-widget__root-cause-actions" data-testid="root-cause-actions">
          <li
            v-for="(a, i) in rootCause.suggested_actions"
            :key="i"
            :data-severity="a.severity"
            data-testid="root-cause-action"
            class="quality-recommendation-widget__root-cause-action"
          >
            {{ a.action }}
            <span v-if="a.severity" class="quality-recommendation-widget__root-cause-severity">({{ a.severity }})</span>
          </li>
        </ul>
        <small v-if="rootCause.confidence != null" class="quality-recommendation-widget__root-cause-confidence">
          置信度: {{ Math.round(rootCause.confidence * 100) }}%
        </small>
      </section>

      <section class="quality-recommendation-widget__rationale">
        <button
          type="button"
          class="quality-recommendation-widget__rationale-toggle"
          data-testid="rationale-toggle"
          :aria-expanded="rationaleExpanded"
          @click="rationaleExpanded = !rationaleExpanded"
        >
          {{ rationaleExpanded ? '收起推理' : '查看推理' }}
        </button>
        <ul
          v-if="rationaleExpanded && rationale.length"
          class="quality-recommendation-widget__rationale-list"
          data-testid="rationale-list"
        >
          <li
            v-for="(line, index) in rationale"
            :key="`rationale-${index}`"
            class="quality-recommendation-widget__rationale-item"
          >
            {{ line }}
          </li>
        </ul>
        <p v-else-if="rationaleExpanded" class="quality-recommendation-widget__empty">无推理细节</p>
      </section>

      <div v-if="isStopAndInspect" class="quality-recommendation-widget__manual-actions" data-testid="manual-review-actions">
        <button type="button" data-testid="continue-retry-btn" @click="$emit('continue-retry')">
          继续重试
        </button>
        <button type="button" data-testid="accept-version-btn" @click="$emit('accept-version')">
          接受当前版本
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { recommendChapterQuality } from '@/api.js'

const emit = defineEmits(['continue-retry', 'accept-version'])

const props = defineProps({
  novelId: { type: String, required: true },
  chapterId: { type: String, required: true },
  currentAttempt: { type: Number, default: 1 },
  acceptWithWarn: { type: Boolean, default: false },
  recentIssueCounts: { type: Array, default: () => [] },
  rootCause: { type: Object, default: null },
})

const loading = ref(false)
const errorMessage = ref('')
const recommendation = ref(null)
const rationaleExpanded = ref(false)

const hasError = computed(() => Boolean(errorMessage.value))

const recommendationType = computed(() => recommendation.value?.recommendation || 'accept')
const stateModifier = computed(() => {
  if (loading.value) return 'loading'
  if (hasError.value) return 'error'
  return recommendationType.value
})

const confidencePercentValue = computed(() => {
  const value = Number(recommendation.value?.confidence ?? 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value * 100)))
})

const confidencePercent = computed(() => `${confidencePercentValue.value}%`)

const rationale = computed(() => {
  const list = recommendation.value?.rationale
  return Array.isArray(list) ? list : []
})

const suggestedActions = computed(() => {
  const list = recommendation.value?.suggested_actions
  return Array.isArray(list) ? list : []
})

const isStopAndInspect = computed(() => recommendationType.value === 'stop_and_inspect')

const RECOMMENDATION_LABELS = {
  accept: '可发布',
  minor_repair: '建议小幅修改',
  major_repair: '建议大幅修改',
  stop_and_inspect: '需人工介入',
}

const ACTION_TYPE_LABELS = {
  targeted_repair: '定向修复',
  full_rewrite: '整体重写',
  manual_review: '人工复核',
  accept_with_warning: '带风险发布',
  no_action: '无需操作',
}

const SCOPE_LABELS = {
  plot_tension: '情节张力',
  characterization: '人物塑造',
  readability: '可读性',
  consistency: '一致性',
  humanity: '人性刻画',
  hook_strength: '章末钩子',
  ai_flavor: 'AI 腔',
  word_count: '字数',
}

function recommendationLabel() {
  return RECOMMENDATION_LABELS[recommendationType.value] || '未知建议'
}

function actionTypeLabel(type) {
  return ACTION_TYPE_LABELS[type] || type || '操作'
}

function scopeLabel(scope) {
  return SCOPE_LABELS[scope] || scope
}

async function loadRecommendation() {
  if (!props.novelId || !props.chapterId) return
  loading.value = true
  errorMessage.value = ''
  rationaleExpanded.value = false
  try {
    const payload = {
      current_attempt: props.currentAttempt,
      accept_with_warn: props.acceptWithWarn,
      recent_issue_counts: props.recentIssueCounts,
    }
    const data = await recommendChapterQuality(props.novelId, props.chapterId, payload)
    recommendation.value = data || null
  } catch (err) {
    errorMessage.value = err?.response?.data?.detail || err?.message || '未知错误'
    recommendation.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.novelId, props.chapterId, props.currentAttempt, props.acceptWithWarn, props.recentIssueCounts],
  () => {
    loadRecommendation()
  },
  { deep: true, immediate: true },
)
</script>

<style scoped>
.quality-recommendation-widget {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  width: 100%;
  min-width: 320px;
  max-width: 480px;
  padding: 1rem 1.1rem;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.85), rgba(241, 245, 249, 0.7));
  color: #0f172a;
  box-sizing: border-box;
}

.quality-recommendation-widget.dark\:bg-slate-900\/60 {
  background: rgba(15, 23, 42, 0.6);
}

:global(.dark) .quality-recommendation-widget {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.78), rgba(15, 23, 42, 0.62));
  color: #e2e8f0;
  border-color: rgba(71, 85, 105, 0.7);
}

.quality-recommendation-widget.is-error {
  border-color: rgba(220, 38, 38, 0.7);
  background: rgba(254, 226, 226, 0.5);
}

:global(.dark) .quality-recommendation-widget.is-error {
  background: rgba(127, 29, 29, 0.3);
}

.quality-recommendation-widget__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.quality-recommendation-widget__title {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.quality-recommendation-widget__eyebrow {
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #64748b;
  margin: 0;
}

.quality-recommendation-widget__chapter {
  font-size: 0.95rem;
  font-weight: 600;
  margin: 0;
  color: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.quality-recommendation-widget__badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1;
  border: 1px solid transparent;
  white-space: nowrap;
}

.quality-recommendation-widget__badge-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 999px;
  background: currentColor;
}

.quality-recommendation-widget__badge--accept {
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;
  border-color: rgba(34, 197, 94, 0.45);
}

.quality-recommendation-widget__badge--minor_repair {
  background: rgba(245, 158, 11, 0.15);
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.5);
}

.quality-recommendation-widget__badge--major_repair {
  background: rgba(234, 88, 12, 0.18);
  color: #c2410c;
  border-color: rgba(234, 88, 12, 0.55);
}

.quality-recommendation-widget__badge--stop_and_inspect {
  background: rgba(220, 38, 38, 0.18);
  color: #b91c1c;
  border-color: rgba(220, 38, 38, 0.55);
}

:global(.dark) .quality-recommendation-widget__badge--accept {
  background: rgba(34, 197, 94, 0.22);
  color: #86efac;
  border-color: rgba(34, 197, 94, 0.55);
}

:global(.dark) .quality-recommendation-widget__badge--minor_repair {
  background: rgba(245, 158, 11, 0.25);
  color: #fcd34d;
  border-color: rgba(245, 158, 11, 0.6);
}

:global(.dark) .quality-recommendation-widget__badge--major_repair {
  background: rgba(234, 88, 12, 0.28);
  color: #fdba74;
  border-color: rgba(234, 88, 12, 0.65);
}

:global(.dark) .quality-recommendation-widget__badge--stop_and_inspect {
  background: rgba(220, 38, 38, 0.3);
  color: #fca5a5;
  border-color: rgba(220, 38, 38, 0.65);
}

.quality-recommendation-widget__spinner {
  width: 1rem;
  height: 1rem;
  border-radius: 999px;
  border: 2px solid rgba(148, 163, 184, 0.4);
  border-top-color: #3b82f6;
  animation: qrw-spin 0.9s linear infinite;
}

@keyframes qrw-spin {
  to { transform: rotate(360deg); }
}

.quality-recommendation-widget__error {
  margin: 0;
  font-size: 0.8125rem;
  color: #b91c1c;
}

:global(.dark) .quality-recommendation-widget__error {
  color: #fca5a5;
}

.quality-recommendation-widget__alert {
  margin: 0;
  padding: 0.5rem 0.7rem;
  font-size: 0.8125rem;
  font-weight: 600;
  border-radius: 8px;
  background: rgba(220, 38, 38, 0.12);
  color: #b91c1c;
  border: 1px solid rgba(220, 38, 38, 0.4);
}

:global(.dark) .quality-recommendation-widget__alert {
  background: rgba(220, 38, 38, 0.22);
  color: #fecaca;
  border-color: rgba(220, 38, 38, 0.55);
}

.quality-recommendation-widget__confidence {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.quality-recommendation-widget__confidence-label {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 0.75rem;
  color: #475569;
}

:global(.dark) .quality-recommendation-widget__confidence-label {
  color: #cbd5e1;
}

.quality-recommendation-widget__confidence-label > span:last-child {
  font-weight: 600;
  color: #0f172a;
}

:global(.dark) .quality-recommendation-widget__confidence-label > span:last-child {
  color: #f1f5f9;
}

.quality-recommendation-widget__confidence-track {
  height: 0.45rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.35);
  overflow: hidden;
}

.quality-recommendation-widget__confidence-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.25s ease;
}

.quality-recommendation-widget__confidence-fill--accept { background: #22c55e; }
.quality-recommendation-widget__confidence-fill--minor_repair { background: #f59e0b; }
.quality-recommendation-widget__confidence-fill--major_repair { background: #ea580c; }
.quality-recommendation-widget__confidence-fill--stop_and_inspect { background: #dc2626; }

.quality-recommendation-widget__section-label {
  margin: 0 0 0.4rem;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #64748b;
}

.quality-recommendation-widget__actions {
  display: flex;
  flex-direction: column;
}

.quality-recommendation-widget__action-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.quality-recommendation-widget__action-item {
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  padding: 0.55rem 0.7rem;
  background: rgba(255, 255, 255, 0.55);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

:global(.dark) .quality-recommendation-widget__action-item {
  background: rgba(30, 41, 59, 0.6);
  border-color: rgba(71, 85, 105, 0.7);
}

.quality-recommendation-widget__action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.quality-recommendation-widget__action-type {
  font-size: 0.8125rem;
  font-weight: 600;
}

.quality-recommendation-widget__action-iterations {
  font-size: 0.6875rem;
  color: #475569;
  border-radius: 999px;
  padding: 0.15rem 0.45rem;
  background: rgba(148, 163, 184, 0.25);
}

:global(.dark) .quality-recommendation-widget__action-iterations {
  color: #cbd5e1;
  background: rgba(71, 85, 105, 0.55);
}

.quality-recommendation-widget__scope {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.quality-recommendation-widget__chip {
  font-size: 0.6875rem;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
  border: 1px solid rgba(59, 130, 246, 0.35);
}

:global(.dark) .quality-recommendation-widget__chip {
  background: rgba(59, 130, 246, 0.22);
  color: #bfdbfe;
  border-color: rgba(59, 130, 246, 0.55);
}

.quality-recommendation-widget__action-reason {
  margin: 0;
  font-size: 0.75rem;
  color: #475569;
  line-height: 1.5;
}

:global(.dark) .quality-recommendation-widget__action-reason {
  color: #cbd5e1;
}

.quality-recommendation-widget__root-cause {
  border-top: 1px dashed rgba(148, 163, 184, 0.4);
  padding-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.quality-recommendation-widget__root-cause-summary {
  margin: 0;
  font-size: 0.8125rem;
  color: #334155;
  line-height: 1.5;
}

:global(.dark) .quality-recommendation-widget__root-cause-summary { color: #cbd5e1; }

.quality-recommendation-widget__root-cause-actions {
  list-style: disc;
  padding-left: 1.1rem;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: #334155;
}

:global(.dark) .quality-recommendation-widget__root-cause-actions { color: #cbd5e1; }

.quality-recommendation-widget__root-cause-severity {
  margin-left: 0.25rem;
  color: #b45309;
  font-weight: 600;
}

.quality-recommendation-widget__root-cause-confidence {
  font-size: 0.6875rem;
  color: #64748b;
}

.quality-recommendation-widget__rationale {
  border-top: 1px dashed rgba(148, 163, 184, 0.4);
  padding-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.quality-recommendation-widget__rationale-toggle {
  align-self: flex-start;
  background: transparent;
  border: none;
  padding: 0;
  font-size: 0.75rem;
  font-weight: 600;
  color: #2563eb;
  cursor: pointer;
}

.quality-recommendation-widget__rationale-toggle:hover {
  text-decoration: underline;
}

:global(.dark) .quality-recommendation-widget__rationale-toggle {
  color: #93c5fd;
}

.quality-recommendation-widget__rationale-list {
  list-style: disc;
  padding-left: 1.1rem;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: #334155;
}

:global(.dark) .quality-recommendation-widget__rationale-list {
  color: #cbd5e1;
}

.quality-recommendation-widget__empty {
  margin: 0;
  font-size: 0.75rem;
  color: #94a3b8;
}
</style>