<template>
  <div class="space-y-6">
    <section class="page-header">
      <div>
        <div class="page-header__eyebrow">Outline Workbench</div>
        <h1 class="page-header__title">大纲规划</h1>
        <p class="page-header__description">
          左侧管理总纲与卷纲，右侧集中查看详情、对话优化和脑爆工作区草稿。
        </p>
      </div>
      <div class="page-header__meta-grid">
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">大纲项</span>
          <span class="page-header__meta-value">{{ workbenchItems.length }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">设定草稿</span>
          <span class="page-header__meta-value">{{ settingDrafts.length }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">建议卡</span>
          <span class="page-header__meta-value">{{ suggestionCardCount }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">当前模式</span>
          <span class="page-header__meta-value">{{ isBrainstormWorkspaceMode ? '脑爆工作区' : '标准规划' }}</span>
        </div>
      </div>
    </section>

    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Workbench</div>
        <h1 class="mt-2 text-3xl font-semibold text-gray-900 dark:text-gray-100">大纲规划</h1>
        <p class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
          左侧切换总纲与各卷卷纲，右侧查看当前版本并继续通过对话优化。
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span
          v-if="isWorkbenchBusy"
          class="volume-plan-busy-chip"
        >
          {{ busyLabel }}
        </span>
        <button
          v-if="store.shouldShowStopFlow"
          type="button"
          class="volume-plan-stop-button"
          :disabled="store.stoppingFlow"
          @click="store.stopCurrentFlow()"
        >
          {{ store.stoppingFlow ? '停止中...' : store.stopFlowLabel }}
        </button>
      </div>
    </div>

    <div
      v-if="isBrainstormWorkspaceMode"
      class="volume-plan-workspace-banner"
    >
      <div>
        <div class="volume-plan-workspace-banner__title">脑爆工作区</div>
        <p class="volume-plan-workspace-banner__description">
          当前修改只会写入工作区草稿。确认无误后，再统一提交为正式总纲、卷纲与待审核设定。
        </p>
        <p v-if="finalConfirmationDisabledReason" class="volume-plan-workspace-banner__warning">
          {{ finalConfirmationDisabledReason }}
        </p>
      </div>
      <button
        data-testid="brainstorm-submit"
        type="button"
        class="volume-plan-workspace-banner__action"
        :disabled="Boolean(finalConfirmationDisabledReason) || store.brainstormWorkspace.submitting"
        @click="handleFinalConfirm"
      >
        {{ store.brainstormWorkspace.submitting ? '最终确认中...' : '最终确认' }}
      </button>
    </div>

    <div v-if="!store.novelId" class="surface-card volume-plan-empty-state rounded-[1.6rem] border-dashed px-6 py-12 text-center">
      请先选择小说
    </div>

    <template v-else>
      <div
        v-if="store.outlineWorkbench.error"
        class="volume-plan-warning-banner"
      >
        {{ store.outlineWorkbench.error }}
      </div>

      <section
        v-if="isBrainstormWorkspaceMode"
        class="surface-card surface-card--soft p-5"
      >
        <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400 dark:text-gray-500">Setting Drafts</div>
        <h2 class="mt-2 text-xl font-semibold text-gray-900 dark:text-gray-100">设定草稿</h2>
        <p class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
          这些草稿会在最终确认后统一进入待审核导入链路。
        </p>

        <div v-if="!settingDrafts.length" class="volume-plan-draft-empty mt-4 rounded-2xl border border-dashed px-4 py-6 text-sm">
          当前还没有待提交的设定草稿。
        </div>

        <div v-else class="mt-4 grid gap-3 lg:grid-cols-2">
          <article
            v-for="draft in settingDrafts"
            :key="draft.draft_id"
            class="volume-plan-draft-card rounded-2xl border px-4 py-4"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ draft.title }}</div>
                <p class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
                  来源：{{ draft.source_outline_ref }} · 类型：{{ draft.source_kind }} · 导入：{{ draft.target_import_mode }}
                </p>
              </div>
              <span class="volume-plan-draft-card__tag rounded-full px-3 py-1 text-xs font-medium">
                {{ draft.target_doc_type || 'auto' }}
              </span>
            </div>
            <p class="mt-3 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-200">
              {{ draft.content }}
            </p>
          </article>
        </div>
      </section>

      <BrainstormSuggestionCards
        v-if="isBrainstormWorkspaceMode"
        :workspace="store.brainstormWorkspace.data"
        :last-round-summary="store.brainstormWorkspace.lastRoundSummary"
        :submit-warnings="store.brainstormWorkspace.data?.submit_warnings || []"
        :action-error="store.brainstormWorkspace.error"
        @fill-conversation="handleFillSuggestionConversation"
        @update-card="handleUpdateSuggestionCard"
      />

      <div class="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
        <OutlineSidebar :items="sidebarItems" @select="handleSelect" />

        <div class="space-y-4">
          <OutlineDetailPanel
            :detail="detailPanel"
            :create-action="null"
            :reviewing="store.outlineWorkbench.reviewing"
            @create="handleCreate"
            @review="handleReviewOutline"
            @apply-suggestion="handleApplySuggestion"
          />
          <OutlineConversation
            ref="conversationRef"
            :messages="store.outlineWorkbench.messages"
            :submitting="store.outlineWorkbench.submitting"
            :disabled="conversationDisabled"
            :current-title="selectedItem?.title || detailPanel?.title || ''"
            :submit-label="conversationSubmitLabel"
            :allow-empty-submit="allowEmptyConversationSubmit"
            :has-context="Boolean(store.outlineWorkbench.conversationSummary || store.outlineWorkbench.lastResultSnapshot)"
            @submit-feedback="handleSubmit"
            @clear-context="handleClearContext"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import * as api from '@/api.js'
import BrainstormSuggestionCards from '@/components/outline/BrainstormSuggestionCards.vue'
import OutlineConversation from '@/components/outline/OutlineConversation.vue'
import OutlineDetailPanel from '@/components/outline/OutlineDetailPanel.vue'
import OutlineSidebar from '@/components/outline/OutlineSidebar.vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const conversationRef = ref(null)

const isBrainstormWorkspaceMode = computed(() => (
  store.canBrainstorm && store.brainstormWorkspace.data?.status === 'active'
))

const settingDrafts = computed(() => (
  store.brainstormWorkspace.data?.setting_docs_draft || []
))

const suggestionCardCount = computed(() => (
  Array.isArray(store.brainstormWorkspace.data?.setting_suggestion_cards)
    ? store.brainstormWorkspace.data.setting_suggestion_cards.length
    : 0
))

const activeSelection = computed(() => (
  store.outlineWorkbench.selection ||
  store.outlineWorkbench.currentItem ||
  syntheticSynopsisSelection.value ||
  null
))

const isWorkbenchBusy = computed(() => (
  store.outlineWorkbench.state === 'loading' ||
  store.outlineWorkbench.submitting ||
  Boolean(store.outlineWorkbench.creatingKey) ||
  Boolean(store.loadingActions.volume_plan)
))

const busyLabel = computed(() => {
  if (store.loadingActions.volume_plan) return '生成中'
  if (store.outlineWorkbench.submitting) return '提交中'
  if (store.outlineWorkbench.creatingKey) return '创建中'
  return '加载中'
})

const workbenchItems = computed(() => {
  const items = [...store.outlineWorkbench.items]
  const hasSynopsis = items.some(
    (item) => item.outline_type === 'synopsis' && item.outline_ref === 'synopsis'
  )
  if (!hasSynopsis) {
    items.unshift({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
      key: 'synopsis:synopsis',
      itemId: 'synopsis:synopsis',
      title: '总纲',
      status: 'missing',
      statusLabel: '待创建',
      summary: '当前还没有总纲，可以直接在下方对话生成总纲。',
    })
  }
  return items
})

const syntheticSynopsisSelection = computed(() => (
  !store.outlineWorkbench.selection &&
  !store.outlineWorkbench.currentItem &&
  !store.synopsisData &&
  workbenchItems.value.some(
    (item) => item.outline_type === 'synopsis' && item.outline_ref === 'synopsis'
  )
    ? { outline_type: 'synopsis', outline_ref: 'synopsis' }
    : null
))

const sidebarItems = computed(() => {
  const selection = activeSelection.value
  return workbenchItems.value.map((item) => ({
    ...item,
    isCurrent: Boolean(
      selection &&
      item.outline_type === selection.outline_type &&
      item.outline_ref === selection.outline_ref
    ),
  }))
})

const selectedItem = computed(() => {
  const selection = activeSelection.value
  if (!selection) return null
  return sidebarItems.value.find(
    (item) => item.outline_type === selection.outline_type && item.outline_ref === selection.outline_ref
  ) || null
})

const awaitingGenerationConfirmation = computed(() => {
  if (detailPanel.value?.status !== 'missing') return false
  const messages = store.outlineWorkbench.messages || []
  const lastMessage = messages[messages.length - 1]
  return lastMessage?.role === 'assistant' &&
    lastMessage?.message_type === 'question' &&
    ['generation_confirmation', 'generation_clarification'].includes(lastMessage?.meta?.interaction_stage)
})

const conversationSubmitLabel = computed(() => (
  detailPanel.value?.status !== 'missing'
    ? '发送修改意见'
    : awaitingGenerationConfirmation.value
      ? '发送确认信息'
      : '生成大纲'
))

const conversationDisabled = computed(() => (
  !store.novelId ||
  !activeSelection.value ||
  Boolean(store.loadingActions.volume_plan) ||
  Boolean(store.outlineWorkbench.creatingKey) ||
  (detailPanel.value?.status === 'missing' && createAction.value?.disabled)
))

const allowEmptyConversationSubmit = computed(() => (
  detailPanel.value?.status === 'missing' &&
  !awaitingGenerationConfirmation.value &&
  !createAction.value?.disabled
))

const createAction = computed(() => {
  const detail = detailPanel.value
  if (!detail || detail.status !== 'missing') return null

  const actionKey = `${detail.outlineType}:${detail.outlineRef}`
  if (detail.outlineType === 'synopsis') {
    const disabledReason = resolveMissingOutlineDisabledReason(detail)
    return {
      key: actionKey,
      label: '一键创建总纲',
      title: '总纲还没有生成',
      description: '系统会基于当前设定文档直接生成完整总纲。',
      loading: store.outlineWorkbench.creatingKey === actionKey,
      disabled: Boolean(disabledReason),
      disabledReason,
    }
  }

  const volumeNumber = parseVolumeNumber(detail.outlineRef)
  const disabledReason = resolveMissingOutlineDisabledReason(detail)

  return {
    key: actionKey,
    label: `一键创建第 ${volumeNumber} 卷`,
    title: `${selectedItem.value?.title || '当前卷'} 还没有卷纲`,
    description: '系统会基于总纲与已完成卷纲，生成当前卷的卷级大纲。',
    loading: store.outlineWorkbench.creatingKey === actionKey,
    disabled: Boolean(disabledReason),
    disabledReason,
    volumeNumber,
  }
})

const detailPanel = computed(() => {
  const selection = activeSelection.value
  const item = selectedItem.value
  if (!selection || !item) return null

  if (item.status === 'missing') {
    const isSynopsis = selection.outline_type === 'synopsis'
    const disabledReason = resolveMissingOutlineDisabledReason(selection)
    return {
      outlineType: selection.outline_type,
      outlineRef: selection.outline_ref,
      status: 'missing',
      statusLabel: item.statusLabel,
      title: item.title,
      emptyTitle: isSynopsis ? '总纲尚未生成' : `${item.title || '当前卷'} 尚未生成卷纲`,
      emptyDescription: disabledReason || (isSynopsis
        ? '可以直接在下方对话生成总纲，再继续做卷级规划和对话式优化。'
        : '可以直接在下方对话生成本卷卷纲，或补充你希望强化的要求。'),
    }
  }

  const snapshot = store.outlineWorkbench.lastResultSnapshot || resolveFallbackSnapshot(selection)

  if (selection.outline_type === 'synopsis') {
    return buildSynopsisDetail(item, snapshot)
  }

  return buildVolumeDetail(item, snapshot)
})

const finalConfirmationDisabledReason = computed(() => {
  if (!isBrainstormWorkspaceMode.value) return ''
  const synopsisDraft = store.brainstormWorkspace.data?.outline_drafts?.['synopsis:synopsis']
  if (!synopsisDraft) return '请先完成总纲草稿。'
  return ''
})

watch(
  () => store.novelId,
  async (novelId) => {
    if (!novelId) return
    await store.refreshOutlineWorkbench()
  },
  { immediate: true }
)

function resolveFallbackSnapshot(selection) {
  if (selection.outline_type === 'synopsis') {
    return store.synopsisData || null
  }

  const selectedVolumeNumber = parseVolumeNumber(selection.outline_ref)
  const currentVolumeNumber = parseVolumeNumber(store.volumePlan?.volume_number || store.volumePlan?.outline_ref)
  if (selectedVolumeNumber && currentVolumeNumber && selectedVolumeNumber === currentVolumeNumber) {
    return store.volumePlan || null
  }
  return null
}

function parseVolumeNumber(value) {
  const match = String(value || '').match(/(\d+)/)
  return match ? Number(match[1]) : null
}

function resolveMissingOutlineDisabledReason(selection) {
  if (!selection) return '请先选择小说。'
  if (!store.novelId) return '请先选择小说。'
  const outlineType = selection.outline_type || selection.outlineType
  const outlineRef = selection.outline_ref || selection.outlineRef
  if (outlineType === 'synopsis') return ''

  const volumeNumber = parseVolumeNumber(outlineRef)
  const previousVolumeMissing = volumeNumber > 1 && sidebarItems.value.some(
    (item) =>
      item.outline_type === 'volume' &&
      item.outline_ref === `vol_${volumeNumber - 1}` &&
      item.status === 'missing'
  )

  if (previousVolumeMissing) return `请先创建第 ${volumeNumber - 1} 卷，再创建当前卷。`
  if (!store.canVolumePlan && !store.canBrainstorm) return '当前阶段不允许创建卷纲。'
  return ''
}

function buildSynopsisDetail(item, snapshot) {
  const themes = Array.isArray(snapshot?.themes) ? snapshot.themes.filter(Boolean) : []
  const characterArcs = Array.isArray(snapshot?.character_arcs) ? snapshot.character_arcs : []
  const milestones = Array.isArray(snapshot?.milestones) ? snapshot.milestones : []
  const volumeOutlines = Array.isArray(snapshot?.volume_outlines) ? snapshot.volume_outlines : []

  return {
    outlineType: 'synopsis',
    outlineRef: item.outline_ref,
    status: item.status,
    statusLabel: item.statusLabel,
    canReview: item.status !== 'missing',
    title: snapshot?.title || item.title,
    summary: snapshot?.logline || snapshot?.core_conflict || item.summary || '',
    meta: [
      { label: '核心冲突', value: snapshot?.core_conflict || '待补充' },
      { label: '预估卷数', value: snapshot?.estimated_volumes || '待定' },
      { label: '预估总章数', value: snapshot?.estimated_total_chapters || '待定' },
    ],
    review: buildReviewDetail(snapshot?.review_status),
    tags: themes,
    sections: [
      volumeOutlines.length
        ? {
          title: '卷级总览',
          items: volumeOutlines.map((volume) => {
            const number = volume.volume_number || volume.number || ''
            const title = volume.title || `第 ${number} 卷`
            const goal = volume.main_goal || volume.goal || volume.summary || '待补充'
            return `第 ${number} 卷《${title}》：${compactText(goal, 42)}`
          }),
          detailItems: volumeOutlines.map((volume) => {
            const number = volume.volume_number || volume.number || ''
            const title = volume.title || `第 ${number} 卷`
            const goal = volume.main_goal || volume.goal || volume.summary || '待补充'
            const conflict = volume.main_conflict || volume.conflict || ''
            const climax = volume.climax || volume.climax_event || ''
            const hook = volume.hook_to_next || volume.hook || ''
            return [
              `第 ${number} 卷《${title}》`,
              `目标：${goal}`,
              conflict ? `冲突：${conflict}` : '',
              climax ? `高潮：${climax}` : '',
              hook ? `钩子：${hook}` : '',
            ].filter(Boolean).join('；')
          }),
        }
        : null,
      characterArcs.length
        ? {
          title: '人物弧光',
          items: characterArcs.map((arc) => `${arc.name || '未命名人物'}：${arc.arc_summary || '待补充'}`),
        }
        : null,
      milestones.length
        ? {
          title: '关键剧情里程碑',
          items: milestones.map((milestone) => `${milestone.act || '阶段'}：${compactText(milestone.summary || '待补充', 34)}`),
          detailItems: milestones.map((milestone) => {
            const act = milestone.act || '阶段'
            const summary = milestone.summary || '待补充'
            const consequence = milestone.consequence || milestone.result || ''
            const trigger = milestone.trigger || milestone.turning_point || ''
            return [
              `${act}：${summary}`,
              trigger ? `转折：${trigger}` : '',
              consequence ? `影响：${consequence}` : '',
            ].filter(Boolean).join('；')
          }),
        }
        : null,
    ].filter(Boolean),
    rawSnapshot: snapshot,
  }
}

function compactText(value, maxLength = 40) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}...`
}

function buildVolumeDetail(item, snapshot) {
  const chapters = Array.isArray(snapshot?.chapters) ? snapshot.chapters : []
  const reviewStatus = snapshot?.review_status || null
  const reviewScore = reviewStatus?.score || null

  return {
    outlineType: 'volume',
    outlineRef: item.outline_ref,
    status: item.status,
    statusLabel: item.statusLabel,
    canReview: item.status !== 'missing',
    title: snapshot?.title || item.title,
    summary: snapshot?.summary || item.summary || '',
    review: buildReviewDetail(reviewStatus),
    meta: [
      { label: '卷目标', value: snapshot?.main_plot_goal || snapshot?.volume_goal || '待补充' },
      { label: '章节数', value: snapshot?.total_chapters || chapters.length || '待定' },
      { label: '预估字数', value: snapshot?.estimated_total_words || '待定' },
      reviewScore?.overall !== undefined ? { label: '评分', value: reviewScore.overall } : null,
    ],
    notices: reviewStatus?.status === 'revise_failed'
      ? [
        {
          title: '自动修订失败',
          text: reviewStatus.reason || '自动修订未完成，请在对话区提交修改意见继续处理。',
        },
      ]
      : [],
    sections: [
      reviewScore
        ? {
          title: '评分明细',
          items: [
            `整体评分：${reviewScore.overall ?? '未知'}`,
            `大纲贴合：${reviewScore.outline_fidelity ?? '未知'}`,
            `人物情节契合：${reviewScore.character_plot_alignment ?? '未知'}`,
            `爽点分布：${reviewScore.hook_distribution ?? '未知'}`,
            `伏笔管理：${reviewScore.foreshadowing_management ?? '未知'}`,
            `章末钩子：${reviewScore.chapter_hooks ?? '未知'}`,
            `翻页欲：${reviewScore.page_turning ?? '未知'}`,
            reviewScore.summary_feedback ? `评审意见：${reviewScore.summary_feedback}` : '',
          ].filter(Boolean),
        }
        : null,
      snapshot?.core_conflict
        ? {
          title: '核心冲突',
          text: snapshot.core_conflict,
        }
        : null,
      snapshot?.ending_hook
        ? {
          title: '卷末推进',
          text: snapshot.ending_hook,
        }
        : null,
    ].filter(Boolean),
    chapters,
    rawSnapshot: snapshot,
  }
}

function buildReviewDetail(reviewStatus) {
  if (!reviewStatus) return null
  const score = reviewStatus.score || null
  const dimensions = score
    ? [
      { label: '大纲贴合', value: score.outline_fidelity },
      { label: '人物情节契合', value: score.character_plot_alignment },
      { label: '爽点分布', value: score.hook_distribution },
      { label: '伏笔管理', value: score.foreshadowing_management },
      { label: '章末钩子', value: score.chapter_hooks },
      { label: '翻页欲', value: score.page_turning },
    ].filter((item) => item.value !== undefined && item.value !== null)
    : []

  return {
    status: reviewStatus.status || '',
    overall: score?.overall,
    feedback: score?.summary_feedback || reviewStatus.reason || '',
    suggestion: reviewStatus.optimization_suggestion || buildOptimizationSuggestion(score),
    dimensions,
  }
}

function buildOptimizationSuggestion(score) {
  if (!score) return ''
  const parts = []
  if (score.summary_feedback) parts.push(score.summary_feedback)
  if (score.outline_fidelity !== undefined && score.outline_fidelity < 75) {
    parts.push('请提高大纲与总设定、总目标、卷级规划的一致性，避免出现旧设定或未确认势力。')
  }
  if (score.character_plot_alignment !== undefined && score.character_plot_alignment < 75) {
    parts.push('请强化人物动机与剧情推进的因果关系，让关键行动来自角色目标而不是外部硬推。')
  }
  if (score.hook_distribution !== undefined && score.hook_distribution < 75) {
    parts.push('请重新分布爽点和阶段性成果，保证每个小阶段都有明确期待和兑现。')
  }
  if (score.foreshadowing_management !== undefined && score.foreshadowing_management < 75) {
    parts.push('请补充伏笔的埋设、回收位置和信息递进，避免只列事件不形成悬念链。')
  }
  if (score.chapter_hooks !== undefined && score.chapter_hooks < 75) {
    parts.push('请加强章末或卷末钩子，让每个关键节点都能推动读者继续阅读。')
  }
  return parts.join('\n')
}

async function handleSelect(item) {
  await store.refreshOutlineWorkbench({
    outline_type: item.outline_type,
    outline_ref: item.outline_ref,
  })
}

async function handleSubmit(content) {
  const trimmedContent = content.trim()
  const nextContent = !trimmedContent && allowEmptyConversationSubmit.value
    ? buildMissingOutlinePrompt(detailPanel.value)
    : trimmedContent
  if (!nextContent) return

  await store.submitOutlineFeedback({ content: nextContent })
}

async function handleClearContext() {
  await store.clearOutlineContext()
}

async function handleReviewOutline() {
  await store.reviewCurrentOutline()
}

function handleApplySuggestion(suggestion) {
  conversationRef.value?.setDraft?.(suggestion)
}

function buildSuggestionCardPrompt(card) {
  const title = card?.title || '未命名建议卡'
  const type = card?.card_type || 'unknown'
  const refs = Array.isArray(card?.source_outline_refs) && card.source_outline_refs.length
    ? card.source_outline_refs.join('、')
    : '未知'
  const status = card?.status || 'unknown'
  const summary = card?.summary || ''
  const payloadSummary = summarizeSuggestionPayload(card?.payload)
  return [
    '请根据这张设定建议卡继续优化当前大纲：',
    `标题：${title}`,
    `类型：${type}`,
    `来源：${refs}`,
    `状态：${status}`,
    `建议：${summary}`,
    `需要补充/确认的设定字段：${payloadSummary}`,
  ].join('\n')
}

function summarizeSuggestionPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return '无结构化字段'
  const entries = Object.entries(payload)
    .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== '')
    .slice(0, 12)
    .map(([key, value]) => `${key}=${formatSuggestionPayloadValue(value)}`)
  return entries.length ? entries.join('；') : '无结构化字段'
}

function formatSuggestionPayloadValue(value) {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(formatSuggestionPayloadValue).join('、')
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}

function handleFillSuggestionConversation(card) {
  conversationRef.value?.setDraft?.(buildSuggestionCardPrompt(card))
}

async function handleUpdateSuggestionCard({ card, action } = {}) {
  const cardId = card?.card_id || card?.merge_key
  if (!cardId || !action) return
  await store.updateBrainstormSuggestionCard(cardId, action)
}

async function handleCreate() {
  const action = createAction.value
  if (!action || action.disabled || action.loading || !store.novelId) return

  store.outlineWorkbench.creatingKey = action.key
  try {
    if (store.canBrainstorm) {
      if (detailPanel.value?.outlineType === 'synopsis') {
        await store.submitOutlineFeedback({
          content: '请基于当前设定生成完整总纲草稿，补齐一句话梗概、核心冲突、卷数规模、人物弧光和关键里程碑。',
        })
        return
      }

      await store.submitOutlineFeedback({
        content: `请基于当前总纲与已完成卷纲，先生成第 ${action.volumeNumber} 卷的完整卷纲草稿，补齐卷目标、核心冲突、章节结构和卷末推进。`,
      })
      return
    }

    if (detailPanel.value?.outlineType === 'synopsis') {
      await api.brainstorm(store.novelId)
      await store.refreshState()
      await store.refreshOutlineWorkbench({ outline_type: 'synopsis', outline_ref: 'synopsis' })
      return
    }

    await api.planVolume(store.novelId, action.volumeNumber)
    await store.refreshState()
    await store.refreshOutlineWorkbench({
      outline_type: 'volume',
      outline_ref: `vol_${action.volumeNumber}`,
    })
  } finally {
    if (store.outlineWorkbench.creatingKey === action.key) {
      store.outlineWorkbench.creatingKey = ''
    }
  }
}

async function handleFinalConfirm() {
  if (finalConfirmationDisabledReason.value) return
  await store.submitBrainstormWorkspace()
}

function buildMissingOutlinePrompt(detail) {
  if (!detail || detail.status !== 'missing') return ''
  if (detail.outlineType === 'synopsis') {
    return '请基于当前设定生成完整总纲草稿，补齐一句话梗概、核心冲突、卷数规模、人物弧光和关键里程碑。'
  }

  const volumeNumber = parseVolumeNumber(detail.outlineRef)
  if (!volumeNumber) return '请基于当前总纲生成当前卷的完整卷纲草稿，补齐卷目标、核心冲突、章节结构和卷末推进。'
  return `请基于当前总纲与已完成卷纲，先生成第 ${volumeNumber} 卷的完整卷纲草稿，补齐卷目标、核心冲突、章节结构和卷末推进。`
}
</script>

<style scoped>
.volume-plan-busy-chip {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 500;
}

.volume-plan-stop-button {
  border: 1px solid color-mix(in srgb, #ef4444 46%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, #ef4444 10%, transparent);
  color: color-mix(in srgb, #ef4444 82%, var(--app-text));
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 600;
  transition: transform 0.18s ease, filter 0.18s ease, opacity 0.18s ease;
}

.volume-plan-stop-button:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.05);
}

.volume-plan-stop-button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.volume-plan-workspace-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-radius: 1.6rem;
  border: 1px solid color-mix(in srgb, var(--app-accent, #34d399) 35%, var(--app-border));
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--app-accent, #34d399) 8%, var(--app-surface)) 0%, var(--app-surface-soft) 55%, var(--app-surface) 100%);
  padding: 1rem 1.25rem;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.volume-plan-workspace-banner__title {
  font-size: 0.95rem;
  font-weight: 600;
  color: color-mix(in srgb, var(--app-accent, #34d399) 55%, var(--app-text));
}

.volume-plan-workspace-banner__description {
  margin-top: 0.25rem;
  font-size: 0.95rem;
  line-height: 1.6;
  color: var(--app-text);
}

.volume-plan-workspace-banner__warning {
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: color-mix(in srgb, #f59e0b 72%, var(--app-text));
}

.volume-plan-workspace-banner__action {
  border: 1px solid color-mix(in srgb, var(--app-accent, #34d399) 48%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--app-accent, #34d399) 78%, white 10%);
  color: #ffffff;
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  transition: transform 0.18s ease, filter 0.18s ease, opacity 0.18s ease;
}

.volume-plan-workspace-banner__action:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.04);
}

.volume-plan-workspace-banner__action:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.volume-plan-empty-state {
  color: var(--app-text-muted);
}

.volume-plan-warning-banner {
  border: 1px solid color-mix(in srgb, #f59e0b 35%, var(--app-border));
  border-radius: 1rem;
  background: color-mix(in srgb, #f59e0b 10%, var(--app-surface-soft));
  color: color-mix(in srgb, #f59e0b 72%, var(--app-text));
  padding: 0.75rem 1rem;
  font-size: 0.875rem;
}

.volume-plan-draft-empty {
  border-color: var(--app-border);
  background: var(--app-surface);
  color: var(--app-text-muted);
}

.volume-plan-draft-card {
  border-color: var(--app-border);
  background: var(--app-surface);
}

.volume-plan-draft-card__tag {
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
}
</style>
