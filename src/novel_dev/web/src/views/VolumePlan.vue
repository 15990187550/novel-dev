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
          <OutlineDetailPanel :detail="detailPanel" :create-action="createAction" @create="handleCreate" />
          <OutlineConversation
            :messages="store.outlineWorkbench.messages"
            :submitting="store.outlineWorkbench.submitting"
            :disabled="!store.novelId || !activeSelection || Boolean(store.outlineWorkbench.creatingKey)"
            :current-title="selectedItem?.title || detailPanel?.title || ''"
            @submit-feedback="handleSubmit"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import * as api from '@/api.js'
import OutlineConversation from '@/components/outline/OutlineConversation.vue'
import OutlineDetailPanel from '@/components/outline/OutlineDetailPanel.vue'
import OutlineSidebar from '@/components/outline/OutlineSidebar.vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()

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
      summary: '当前还没有总纲，可以先一键创建总纲。',
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

const createAction = computed(() => {
  const detail = detailPanel.value
  if (!detail || detail.status !== 'missing') return null

  const actionKey = `${detail.outlineType}:${detail.outlineRef}`
  if (detail.outlineType === 'synopsis') {
    const disabledReason = !store.novelId ? '请先选择小说。' : ''
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
  const previousVolumeMissing = volumeNumber > 1 && sidebarItems.value.some(
    (item) =>
      item.outline_type === 'volume' &&
      item.outline_ref === `vol_${volumeNumber - 1}` &&
      item.status === 'missing'
  )

  let disabledReason = ''
  if (!store.novelId) disabledReason = '请先选择小说。'
  else if (previousVolumeMissing) disabledReason = `请先创建第 ${volumeNumber - 1} 卷，再创建当前卷。`
  else if (!store.canVolumePlan) disabledReason = '当前阶段不允许创建卷纲。'

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
    return {
      outlineType: selection.outline_type,
      outlineRef: selection.outline_ref,
      status: 'missing',
      statusLabel: item.statusLabel,
      title: item.title,
      emptyTitle: isSynopsis ? '总纲尚未生成' : `${item.title || '当前卷'} 尚未生成卷纲`,
      emptyDescription: isSynopsis
        ? '先创建总纲，再继续做卷级规划和对话式优化。'
        : '你可以直接在下方输入意见，或者先一键创建本卷卷纲。',
    }
  }

  const snapshot = store.outlineWorkbench.lastResultSnapshot || resolveFallbackSnapshot(selection)

  if (selection.outline_type === 'synopsis') {
    return buildSynopsisDetail(item, snapshot)
  }

  return buildVolumeDetail(item, snapshot)
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
  await store.submitOutlineFeedback({ content })
}

async function handleCreate() {
  const action = createAction.value
  if (!action || action.disabled || action.loading || !store.novelId) return

  store.outlineWorkbench.creatingKey = action.key
  try {
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
</script>
