<template>
  <section
    class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm"
    data-testid="brainstorm-suggestion-cards"
  >
    <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Suggestion Cards</div>
    <h2 class="mt-2 text-xl font-semibold text-gray-900">设定建议卡</h2>
    <p class="mt-1 text-sm leading-6 text-gray-500">
      对话优化大纲时，系统会持续整理需要补充或确认的设定建议卡。请优先处理未解决项，再进行最终确认。
    </p>

    <div
      v-if="normalizedLastRoundSummary"
      class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
      data-testid="last-round-summary"
    >
      <div class="font-semibold">本轮设定更新</div>
      <p class="mt-1 text-xs leading-5 text-emerald-800">
        新增 {{ normalizedLastRoundSummary.created }} · 更新 {{ normalizedLastRoundSummary.updated }} ·
        覆盖 {{ normalizedLastRoundSummary.superseded }} · 未解决 {{ normalizedLastRoundSummary.unresolved }}
      </p>
    </div>

    <div
      v-if="unresolvedCount > 0"
      class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      data-testid="unresolved-warning"
    >
      当前仍有 {{ unresolvedCount }} 张建议卡处于未解决状态，最终确认前建议先处理或补充信息。
    </div>

    <div
      v-if="resolvedSubmitWarnings.length"
      class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      data-testid="submit-warnings"
    >
      <div class="font-semibold">提交提示</div>
      <ul class="mt-2 list-disc space-y-1 pl-5 text-xs leading-5">
        <li v-for="warning in resolvedSubmitWarnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <div
      v-if="!activeCards.length"
      class="mt-4 rounded-2xl border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500"
      data-testid="suggestion-empty"
    >
      当前还没有待处理的设定建议卡。
    </div>

    <div v-else class="mt-4 grid gap-3 lg:grid-cols-2">
      <article
        v-for="card in activeCards"
        :key="card.card_id || card.merge_key"
        class="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-4"
        data-testid="suggestion-card"
      >
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-sm font-semibold text-gray-900">{{ card.title }}</div>
            <p class="mt-1 text-xs leading-5 text-gray-500">
              类型：{{ card.card_type || 'unknown' }} · 来源：{{ formatSourceRefs(card.source_outline_refs) }}
            </p>
          </div>
          <span
            class="rounded-full bg-white px-3 py-1 text-xs font-medium"
            :class="card.status === 'unresolved' ? 'text-amber-700' : 'text-emerald-700'"
          >
            {{ card.status === 'unresolved' ? '未解决' : '待处理' }}
          </span>
        </div>
        <p class="mt-3 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-gray-700">
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
  if (fromProp.length) return fromProp.filter((item) => typeof item === 'string' && item.trim())
  const fromWorkspace = props.workspace?.submit_warnings
  return Array.isArray(fromWorkspace) ? fromWorkspace.filter((item) => typeof item === 'string' && item.trim()) : []
})

function formatSourceRefs(value) {
  const refs = Array.isArray(value) ? value.filter(Boolean) : []
  if (!refs.length) return '未知'
  return refs.join('、')
}
</script>

