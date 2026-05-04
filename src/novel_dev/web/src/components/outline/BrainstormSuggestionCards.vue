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
        <p class="mt-3 text-xs leading-5 text-gray-500 dark:text-gray-400">
          {{ getActionHint(card).reason }}
        </p>
        <div class="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            class="brainstorm-suggestion-card__button brainstorm-suggestion-card__button--primary"
            data-testid="suggestion-primary-action"
            @click="handlePrimaryAction(card)"
          >
            {{ getActionHint(card).primary_label }}
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            data-testid="suggestion-process"
            @click="openDetail(card)"
          >
            处理
          </button>
        </div>
      </article>
    </div>

    <div v-if="historyCards.length" class="mt-4">
      <button
        type="button"
        class="brainstorm-suggestion-card__button"
        data-testid="toggle-suggestion-history"
        @click="showHistory = !showHistory"
      >
        历史建议 {{ historyCards.length }}
      </button>
      <div v-if="showHistory" class="mt-3 grid gap-3 lg:grid-cols-2">
        <article
          v-for="card in historyCards"
          :key="card.card_id || card.merge_key"
          class="brainstorm-suggestion-card rounded-2xl border px-4 py-4"
          data-testid="suggestion-history-card"
        >
          <div class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ card.title }}</div>
          <p class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
            {{ getActionHint(card).reason }}
          </p>
          <button
            type="button"
            class="brainstorm-suggestion-card__button mt-3"
            @click="openDetail(card)"
          >
            查看处理
          </button>
        </article>
      </div>
    </div>

    <div
      v-if="selectedCard"
      class="brainstorm-suggestion-drawer"
      data-testid="suggestion-detail-drawer"
    >
      <div class="brainstorm-suggestion-drawer__panel">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-xs font-medium uppercase tracking-[0.2em] text-gray-400">Suggestion Detail</div>
            <h3 class="mt-2 text-lg font-semibold text-gray-900 dark:text-gray-100">{{ selectedCard.title }}</h3>
            <p class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
              类型：{{ selectedCard.card_type || 'unknown' }} · 来源：{{ formatSourceRefs(selectedCard.source_outline_refs) }}
            </p>
          </div>
          <button type="button" class="brainstorm-suggestion-card__button" @click="closeDetail">关闭</button>
        </div>
        <p class="mt-4 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-200">{{ selectedCard.summary }}</p>
        <div class="brainstorm-suggestion-summary mt-4 rounded-2xl border px-4 py-3 text-sm">
          <div class="font-semibold">{{ getActionHint(selectedCard).primary_label }}</div>
          <p class="mt-1 text-xs leading-5">{{ getActionHint(selectedCard).reason }}</p>
        </div>
        <div
          v-if="actionError"
          class="brainstorm-suggestion-error mt-4 rounded-2xl border px-4 py-3 text-sm"
          data-testid="suggestion-action-error"
        >
          处理失败：{{ actionError }}。请检查后重试。
        </div>
        <div class="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            class="brainstorm-suggestion-card__button brainstorm-suggestion-card__button--primary"
            data-testid="submit-to-pending-action"
            :disabled="!hasAction(selectedCard, 'submit_to_pending')"
            @click="emitUpdate(selectedCard, 'submit_to_pending')"
          >
            转为待审批设定
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'fill_conversation')"
            @click="emit('fill-conversation', selectedCard)"
          >
            回填到输入区
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'resolve')"
            @click="emitUpdate(selectedCard, 'resolve')"
          >
            标记已解决
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'dismiss')"
            @click="emitUpdate(selectedCard, 'dismiss')"
          >
            忽略
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'reactivate')"
            @click="emitUpdate(selectedCard, 'reactivate')"
          >
            重新激活
          </button>
        </div>
        <pre class="brainstorm-suggestion-payload mt-4 overflow-auto rounded-xl p-3 text-xs">{{ formatPayload(selectedCard.payload) }}</pre>
        <details class="mt-4 text-xs text-gray-500 dark:text-gray-400">
          <summary>调试信息</summary>
          <div class="mt-2">card_id: {{ selectedCard.card_id }}</div>
          <div>merge_key: {{ selectedCard.merge_key }}</div>
        </details>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  workspace: { type: Object, default: null },
  lastRoundSummary: { type: Object, default: null },
  submitWarnings: { type: Array, default: () => [] },
  actionError: { type: String, default: '' },
})

const emit = defineEmits(['fill-conversation', 'update-card'])
const selectedCardKey = ref('')
const showHistory = ref(false)

const terminalStatuses = new Set(['resolved', 'dismissed', 'submitted', 'superseded'])

const activeCards = computed(() => {
  const cards = props.workspace?.setting_suggestion_cards
  const list = Array.isArray(cards) ? cards : []
  return list
    .filter((card) => card && (card.status === 'active' || card.status === 'unresolved'))
    .slice()
    .sort(sortCards)
})

const historyCards = computed(() => {
  const cards = props.workspace?.setting_suggestion_cards
  const list = Array.isArray(cards) ? cards : []
  return list
    .filter((card) => card && terminalStatuses.has(card.status))
    .slice()
    .sort(sortCards)
})

const allCards = computed(() => [
  ...activeCards.value,
  ...historyCards.value,
])

const selectedCard = computed(() => (
  allCards.value.find((card) => buildCardKey(card) === selectedCardKey.value) || null
))

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

function sortCards(left, right) {
  const leftOrder = Number(left?.display_order ?? 0)
  const rightOrder = Number(right?.display_order ?? 0)
  if (leftOrder !== rightOrder) return leftOrder - rightOrder
  return String(left?.merge_key || '').localeCompare(String(right?.merge_key || ''))
}

function buildCardKey(card) {
  return String(card?.card_id || card?.merge_key || '')
}

function getActionHint(card) {
  return card?.action_hint || {
    recommended_action: 'open_detail',
    primary_label: '查看处理',
    available_actions: ['open_detail'],
    reason: '这张卡当前只支持查看。',
  }
}

function hasAction(card, action) {
  return Array.isArray(getActionHint(card).available_actions) &&
    getActionHint(card).available_actions.includes(action)
}

function openDetail(card) {
  selectedCardKey.value = buildCardKey(card)
}

function closeDetail() {
  selectedCardKey.value = ''
}

function handlePrimaryAction(card) {
  const hint = getActionHint(card)
  if (hint.recommended_action === 'submit_to_pending' && hasAction(card, 'submit_to_pending')) {
    emit('update-card', { card, action: 'submit_to_pending' })
    return
  }
  if (hint.recommended_action === 'continue_outline_feedback' || hint.recommended_action === 'request_more_info') {
    emit('fill-conversation', card)
    return
  }
  openDetail(card)
}

function emitUpdate(card, action) {
  if (!hasAction(card, action)) return
  emit('update-card', { card, action })
}

function formatPayload(payload) {
  if (!payload || typeof payload !== 'object') return '{}'
  return JSON.stringify(payload, null, 2)
}

watch(selectedCard, (card) => {
  if (!card && selectedCardKey.value) {
    selectedCardKey.value = ''
  }
})
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

.brainstorm-suggestion-error {
  border-color: color-mix(in srgb, #ef4444 38%, var(--app-border));
  background: color-mix(in srgb, #ef4444 10%, var(--app-surface-soft));
  color: color-mix(in srgb, #ef4444 72%, var(--app-text));
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

.brainstorm-suggestion-card__button {
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  color: var(--app-text);
  padding: 0.45rem 0.7rem;
  font-size: 0.75rem;
  font-weight: 600;
}

.brainstorm-suggestion-card__button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.brainstorm-suggestion-card__button--primary {
  border-color: color-mix(in srgb, var(--app-accent, #34d399) 45%, var(--app-border));
  color: color-mix(in srgb, var(--app-accent, #34d399) 72%, var(--app-text));
}

.brainstorm-suggestion-drawer {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
  background: rgb(15 23 42 / 0.32);
}

.brainstorm-suggestion-drawer__panel {
  width: min(560px, 100vw);
  height: 100%;
  overflow-y: auto;
  border-left: 1px solid var(--app-border);
  background: var(--app-surface);
  padding: 1.25rem;
  box-shadow: -16px 0 40px rgb(15 23 42 / 0.18);
}

.brainstorm-suggestion-payload {
  border: 1px solid var(--app-border);
  background: var(--app-surface-soft);
  color: var(--app-text);
}
</style>
