<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Workbench</div>
        <h1 class="mt-2 text-3xl font-semibold text-gray-900">大纲规划</h1>
        <p class="mt-1 text-sm leading-6 text-gray-500">
          左侧切换总纲与各卷卷纲，右侧查看当前版本并继续通过对话优化。
        </p>
      </div>
      <span
        v-if="isWorkbenchBusy"
        class="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
      >
        {{ busyLabel }}
      </span>
    </div>

    <div
      v-if="isBrainstormWorkspaceMode"
      class="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-emerald-200 bg-emerald-50 px-5 py-4"
    >
      <div>
        <div class="text-sm font-semibold text-emerald-900">脑爆工作区</div>
        <p class="mt-1 text-sm leading-6 text-emerald-800">
          当前修改只会写入工作区草稿。确认无误后，再统一提交为正式总纲、卷纲与待审核设定。
        </p>
        <p v-if="finalConfirmationDisabledReason" class="mt-1 text-xs text-amber-700">
          {{ finalConfirmationDisabledReason }}
        </p>
      </div>
      <button
        data-testid="brainstorm-submit"
        type="button"
        class="rounded-full bg-emerald-900 px-5 py-2.5 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:bg-emerald-300"
        :disabled="Boolean(finalConfirmationDisabledReason) || store.brainstormWorkspace.submitting"
        @click="handleFinalConfirm"
      >
        {{ store.brainstormWorkspace.submitting ? '最终确认中...' : '最终确认' }}
      </button>
    </div>

    <div v-if="!store.novelId" class="rounded-3xl border border-dashed border-gray-300 bg-gray-50 px-6 py-12 text-center text-gray-500">
      请先选择小说
    </div>

    <template v-else>
      <div
        v-if="store.outlineWorkbench.error"
        class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700"
      >
        {{ store.outlineWorkbench.error }}
      </div>

      <div class="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <OutlineSidebar :items="sidebarItems" @select="handleSelect" />

        <div class="space-y-4">
          <OutlineDetailPanel :detail="detailPanel" :create-action="null" @create="handleCreate" />
          <OutlineConversation
            :messages="store.outlineWorkbench.messages"
            :submitting="store.outlineWorkbench.submitting"
            :disabled="conversationDisabled"
            :current-title="selectedItem?.title || detailPanel?.title || ''"
            :submit-label="conversationSubmitLabel"
            :allow-empty-submit="allowEmptyConversationSubmit"
            @submit-feedback="handleSubmit"
          />
        </div>
      </div>

      <section
        v-if="isBrainstormWorkspaceMode"
        class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm"
      >
        <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Setting Drafts</div>
        <h2 class="mt-2 text-xl font-semibold text-gray-900">设定草稿</h2>
        <p class="mt-1 text-sm leading-6 text-gray-500">
          这些草稿会在最终确认后统一进入待审核导入链路。
        </p>

        <div v-if="!settingDrafts.length" class="mt-4 rounded-2xl border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">
          当前还没有待提交的设定草稿。
        </div>

        <div v-else class="mt-4 grid gap-3 lg:grid-cols-2">
          <article
            v-for="draft in settingDrafts"
            :key="draft.draft_id"
            class="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-4"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="text-sm font-semibold text-gray-900">{{ draft.title }}</div>
                <p class="mt-1 text-xs leading-5 text-gray-500">
                  来源：{{ draft.source_outline_ref }} · 类型：{{ draft.source_kind }} · 导入：{{ draft.target_import_mode }}
                </p>
              </div>
              <span class="rounded-full bg-white px-3 py-1 text-xs font-medium text-gray-600">
                {{ draft.target_doc_type || 'auto' }}
              </span>
            </div>
            <p class="mt-3 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-gray-700">
              {{ draft.content }}
            </p>
          </article>
        </div>
      </section>

      <BrainstormSuggestionCards
        v-if="isBrainstormWorkspaceMode"
        :workspace="store.brainstormWorkspace.data"
        :last-round-summary="store.brainstormWorkspace.lastRoundSummary"
      />
    </template>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import * as api from '@/api.js'
import BrainstormSuggestionCards from '@/components/outline/BrainstormSuggestionCards.vue'
import OutlineConversation from '@/components/outline/OutlineConversation.vue'
import OutlineDetailPanel from '@/components/outline/OutlineDetailPanel.vue'
import OutlineSidebar from '@/components/outline/OutlineSidebar.vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()

const isBrainstormWorkspaceMode = computed(() => (
  store.canBrainstorm && store.brainstormWorkspace.data?.status === 'active'
))

const settingDrafts = computed(() => (
  store.brainstormWorkspace.data?.setting_docs_draft || []
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
  Boolean(store.outlineWorkbench.creatingKey)
))

const busyLabel = computed(() => {
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
    lastMessage?.meta?.interaction_stage === 'generation_confirmation'
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

  return {
    outlineType: 'synopsis',
    outlineRef: item.outline_ref,
    status: item.status,
    statusLabel: item.statusLabel,
    title: snapshot?.title || item.title,
    summary: snapshot?.logline || snapshot?.core_conflict || item.summary || '',
    meta: [
      { label: '核心冲突', value: snapshot?.core_conflict || '待补充' },
      { label: '预估卷数', value: snapshot?.estimated_volumes || '待定' },
      { label: '预估总章数', value: snapshot?.estimated_total_chapters || '待定' },
    ],
    tags: themes,
    sections: [
      characterArcs.length
        ? {
          title: '人物弧光',
          items: characterArcs.map((arc) => `${arc.name || '未命名人物'}：${arc.arc_summary || '待补充'}`),
        }
        : null,
      milestones.length
        ? {
          title: '关键剧情里程碑',
          items: milestones.map((milestone) => `${milestone.act || '阶段'}：${milestone.summary || '待补充'}`),
        }
        : null,
    ].filter(Boolean),
    rawSnapshot: snapshot,
  }
}

function buildVolumeDetail(item, snapshot) {
  const chapters = Array.isArray(snapshot?.chapters) ? snapshot.chapters : []

  return {
    outlineType: 'volume',
    outlineRef: item.outline_ref,
    status: item.status,
    statusLabel: item.statusLabel,
    title: snapshot?.title || item.title,
    summary: snapshot?.summary || item.summary || '',
    meta: [
      { label: '卷目标', value: snapshot?.main_plot_goal || snapshot?.volume_goal || '待补充' },
      { label: '章节数', value: snapshot?.total_chapters || chapters.length || '待定' },
      { label: '预估字数', value: snapshot?.estimated_total_words || '待定' },
    ],
    sections: [
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
