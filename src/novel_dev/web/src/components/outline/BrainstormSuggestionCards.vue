<template>
  <section
    class="surface-card surface-card--soft p-5"
    data-testid="brainstorm-suggestion-cards"
  >
    <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400 dark:text-gray-500">Suggestion Cards</div>
    <h2 class="mt-2 text-xl font-semibold text-gray-900 dark:text-gray-100">设定建议卡</h2>
    <p class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
      对话优化大纲时，系统会持续整理需要补充或确认的设定建议卡。请优先处理未解决项，再进行最终确认。
    </p>

    <div
      v-if="normalizedLastRoundSummary"
      class="brainstorm-suggestion-summary mt-4 rounded-2xl border px-4 py-3 text-sm"
      data-testid="last-round-summary"
    >
      <div class="font-semibold">本轮设定更新</div>
      <p class="brainstorm-suggestion-summary__meta mt-1 text-xs leading-5">
        新增 {{ normalizedLastRoundSummary.created }} · 更新 {{ normalizedLastRoundSummary.updated }} ·
        覆盖 {{ normalizedLastRoundSummary.superseded }} · 未解决 {{ normalizedLastRoundSummary.unresolved }}
      </p>
    </div>

    <div
      v-if="unresolvedCount > 0"
      class="brainstorm-suggestion-warning mt-4 rounded-2xl border px-4 py-3 text-sm"
      data-testid="unresolved-warning"
    >
      当前仍有 {{ unresolvedCount }} 张建议卡处于未解决状态，最终确认前建议先处理或补充信息。
    </div>

    <div
      v-if="resolvedSubmitWarnings.length"
      class="brainstorm-suggestion-warning mt-4 rounded-2xl border px-4 py-3 text-sm"
      data-testid="submit-warnings"
    >
      <div class="font-semibold">提交提示</div>
      <ul class="mt-2 list-disc space-y-1 pl-5 text-xs leading-5">
        <li v-for="warning in resolvedSubmitWarnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <div
      v-if="!activeCards.length"
      class="brainstorm-suggestion-empty mt-4 rounded-2xl border border-dashed px-4 py-6 text-sm"
      data-testid="suggestion-empty"
    >
      当前还没有待处理的设定建议卡。
    </div>

    <div v-else class="mt-4 grid gap-3 lg:grid-cols-2">
      <article
        v-for="card in activeCards"
        :key="card.card_id || card.merge_key"
        class="brainstorm-suggestion-card rounded-2xl border px-4 py-4"
        data-testid="suggestion-card"
      >
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ card.title }}</div>
            <p class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
              类型：{{ card.card_type || 'unknown' }} · 来源：{{ formatSourceRefs(card.source_outline_refs) }}
            </p>
          </div>
          <span
            class="brainstorm-suggestion-card__status rounded-full px-3 py-1 text-xs font-medium"
            :class="card.status === 'unresolved' ? 'brainstorm-suggestion-card__status--warning' : 'brainstorm-suggestion-card__status--accent'"
          >
            {{ card.status === 'unresolved' ? '未解决' : '待处理' }}
          </span>
        </div>
        <p class="mt-3 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-200">
          {{ card.summary }}
        </p>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  workspace: { type: Object, default: null },
  lastRoundSummary: { type: Object, default: null },
  submitWarnings: { type: Array, default: () => [] },
})

const activeCards = computed(() => {
  const cards = props.workspace?.setting_suggestion_cards
  const list = Array.isArray(cards) ? cards : []
  return list
    .filter((card) => card && (card.status === 'active' || card.status === 'unresolved'))
    .slice()
    .sort((left, right) => {
      const leftOrder = Number(left?.display_order ?? 0)
      const rightOrder = Number(right?.display_order ?? 0)
      if (leftOrder !== rightOrder) return leftOrder - rightOrder
      return String(left?.merge_key || '').localeCompare(String(right?.merge_key || ''))
    })
})

const unresolvedCount = computed(() => activeCards.value.filter((card) => card?.status === 'unresolved').length)

const normalizedLastRoundSummary = computed(() => {
  if (!props.lastRoundSummary) return null
  return {
    created: Number(props.lastRoundSummary.created ?? 0),
    updated: Number(props.lastRoundSummary.updated ?? 0),
    superseded: Number(props.lastRoundSummary.superseded ?? 0),
    unresolved: Number(props.lastRoundSummary.unresolved ?? 0),
  }
})

const resolvedSubmitWarnings = computed(() => {
  const fromProp = Array.isArray(props.submitWarnings) ? props.submitWarnings : []
  return fromProp.filter((item) => typeof item === 'string' && item.trim())
})

function formatSourceRefs(value) {
  const refs = Array.isArray(value) ? value.filter(Boolean) : []
  if (!refs.length) return '未知'
  return refs.join('、')
}
</script>

<style scoped>
.brainstorm-suggestion-summary {
  border-color: color-mix(in srgb, var(--app-accent, #34d399) 35%, var(--app-border));
  background: color-mix(in srgb, var(--app-accent, #34d399) 10%, var(--app-surface-soft));
  color: var(--app-text);
}

.brainstorm-suggestion-summary__meta {
  color: var(--app-text-muted);
}

.brainstorm-suggestion-warning {
  border-color: color-mix(in srgb, #f59e0b 35%, var(--app-border));
  background: color-mix(in srgb, #f59e0b 10%, var(--app-surface-soft));
  color: color-mix(in srgb, #f59e0b 72%, var(--app-text));
}

.brainstorm-suggestion-empty {
  border-color: var(--app-border);
  background: var(--app-surface);
  color: var(--app-text-muted);
}

.brainstorm-suggestion-card {
  border-color: var(--app-border);
  background: var(--app-surface);
}

.brainstorm-suggestion-card__status {
  background: var(--app-surface-soft);
}

.brainstorm-suggestion-card__status--warning {
  color: color-mix(in srgb, #f59e0b 72%, var(--app-text));
}

.brainstorm-suggestion-card__status--accent {
  color: color-mix(in srgb, var(--app-accent, #34d399) 68%, var(--app-text));
}
</style>
