<template>
  <div v-if="!store.novelId" class="rounded-2xl border border-dashed border-gray-300 bg-white/70 px-6 py-16 text-center text-gray-500 shadow-sm dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-300">
    <p class="text-lg font-semibold text-gray-700 dark:text-gray-100">请从侧边栏选择或输入一个小说 ID</p>
    <p class="mt-2 text-sm">选中小说后，这里会展示总览、状态卡、实时日志和推荐动作。</p>
  </div>

  <main v-else class="space-y-6">
    <DashboardHero
      :title="store.novelTitle"
      :phase-label="store.currentPhaseLabel"
      :volume-chapter="store.currentVolumeChapter"
      :total-words="store.archiveStats.total_word_count || 0"
      :archived-count="store.archiveStats.archived_chapter_count || 0"
    />

    <DashboardStatusCards :panels="statusCards" />

    <DashboardVolumeSummary
      :chapters="chapterSummary.chapters"
      :scores="currentChapterScores"
      title="卷进度与评分"
      :subtitle="volumeSubtitle"
    />

    <div class="grid gap-6 xl:grid-cols-2">
      <DashboardNextActions :actions="recommendedActions" @action="handleAction" />

      <DashboardInsights
        :recent-updates="recentUpdates"
        :risks="riskItems"
        :recent-logs="recentLogs"
        :connected="connected"
        :links="quickLinks"
      />
    </div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { useRealtimeLog } from '@/composables/useRealtimeLog.js'
import DashboardHero from '@/components/dashboard/DashboardHero.vue'
import DashboardStatusCards from '@/components/dashboard/DashboardStatusCards.vue'
import DashboardVolumeSummary from '@/components/dashboard/DashboardVolumeSummary.vue'
import DashboardNextActions from '@/components/dashboard/DashboardNextActions.vue'
import DashboardInsights from '@/components/dashboard/DashboardInsights.vue'
import {
  buildChapterSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
} from './dashboard/dashboardSummary.js'

const store = useNovelStore()
const novelIdRef = computed(() => store.novelId)
const { logs, connected } = useRealtimeLog(novelIdRef)

const refreshTimer = ref(null)
let refreshing = false
let refreshQueued = false

const panelDefinitions = {
  entities: { label: '实体状态', route: '/entities' },
  timelines: { label: '时间线状态', route: '/timeline' },
  foreshadowings: { label: '伏笔状态', route: '/foreshadowings' },
  pendingDocs: { label: '资料状态', route: '/documents' },
}

const panelEntries = computed(() => Object.entries(panelDefinitions).map(([key, definition]) => {
  const panel = store.dashboardPanels?.[key] || {}
  const panelState = panel.state || 'idle'

  return {
    id: key,
    label: definition.label,
    title: panelState === 'error' ? '请求异常' : panelState === 'loading' ? '加载中' : panelState === 'ready' ? '已就绪' : '待刷新',
    detail: panel.error || (panelState === 'error' ? '面板请求失败，请稍后重试' : '面板状态正常'),
    meta: store.dashboardLastUpdated ? `更新时间 ${formatTime(store.dashboardLastUpdated)}` : '尚未刷新',
    route: definition.route,
    state: panelState,
    panelState,
  }
}))

const chapterSummary = computed(() => buildChapterSummary({
  chapters: store.chapters,
  volumePlan: store.volumePlan,
  currentChapterId: store.novelState.current_chapter_id,
  currentChapter: store.currentChapter,
}))

const dataSummary = computed(() => buildDataSummary({
  entities: store.entities,
  timelines: store.timelines,
  foreshadowings: store.foreshadowings,
  pendingDocs: store.pendingDocs,
}))

const recentUpdates = computed(() => buildRecentUpdates({
  entities: store.entities,
  timelines: store.timelines,
  foreshadowings: store.foreshadowings,
  pendingDocs: store.pendingDocs,
}))

const recommendedActions = computed(() => buildRecommendedActions({
  currentPhase: store.novelState.current_phase,
  currentChapter: store.currentChapter,
  volumePlan: store.volumePlan,
}))

const recentLogs = computed(() => logs.value.slice(-3))

const riskItems = computed(() => buildRiskItems({
  panels: panelEntries.value,
  currentChapter: store.currentChapter,
  currentPhase: store.novelState.current_phase,
  logs: logs.value,
}))

const currentChapterScores = computed(() => store.currentChapter?.score_breakdown || {})

const quickLinks = computed(() => ([
  { label: '章节', route: '/chapters', detail: '查看当前章节与进度' },
  { label: '实体', route: '/entities', detail: '管理人物与实体关系' },
  { label: '时间线', route: '/timeline', detail: '检查时间线事件' },
  { label: '伏笔', route: '/foreshadowings', detail: '追踪伏笔埋点' },
  { label: '资料', route: '/documents', detail: '查看待处理资料' },
  { label: '日志', route: '/logs', detail: '查看实时日志流' },
]))

const volumeSubtitle = computed(() => {
  if (store.currentChapter?.title) {
    return `当前章节：${store.currentChapter.title}`
  }
  if (store.currentPhaseLabel) {
    return `当前阶段：${store.currentPhaseLabel}`
  }
  return '当前章节与卷内评分概览'
})

const statusCards = computed(() => buildStatusCards({
  summary: dataSummary.value,
  panels: panelEntries.value,
  currentPhaseLabel: store.currentPhaseLabel,
  currentVolumeChapter: store.currentVolumeChapter,
  currentChapter: store.currentChapter,
  recentLogs: recentLogs.value,
  connected: connected.value,
  dashboardLastUpdated: store.dashboardLastUpdated,
}))

async function refreshDashboardOnce() {
  if (!store.novelId) return
  if (refreshing) {
    refreshQueued = true
    return
  }

  refreshing = true
  try {
    await store.refreshDashboard()
  } finally {
    refreshing = false
    if (refreshQueued) {
      refreshQueued = false
      void refreshDashboardOnce()
    }
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer.value = window.setInterval(() => {
    void refreshDashboardOnce()
  }, 20000)
}

function stopAutoRefresh() {
  if (refreshTimer.value) {
    window.clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

function handleAction(actionKey) {
  if (!actionKey) return
  void store.executeAction(actionKey)
}

function formatTime(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function buildStatusCards({
  summary = {},
  panels = [],
  currentPhaseLabel = '',
  currentVolumeChapter = '',
  currentChapter = null,
  recentLogs = [],
  connected = false,
  dashboardLastUpdated = '',
} = {}) {
  const hasPanelError = panels.some((panel) => panel?.state === 'error' || panel?.panelState === 'error')
  const hasLogError = recentLogs.some((log) => log?.level === 'error')
  const logCount = recentLogs.length

  return [
    {
      id: 'flow',
      label: '流程状态',
      title: currentPhaseLabel || '待更新',
      detail: currentChapter?.title || '当前章节待选择',
      meta: currentVolumeChapter || '暂无卷/章信息',
      route: '/chapters',
      panelState: currentChapter ? 'ok' : 'warning',
    },
    {
      id: 'data',
      label: '数据状态',
      title: `${summary.total || 0}`,
      detail: `实体 ${summary.entities || 0} · 时间线 ${summary.timelines || 0} · 伏笔 ${summary.foreshadowings || 0} · 资料 ${summary.pendingDocs || 0}`,
      meta: hasPanelError ? '存在面板异常' : '数据面板正常',
      route: '/entities',
      panelState: hasPanelError ? 'error' : 'ok',
    },
    {
      id: 'logs',
      label: '日志状态',
      title: logCount ? `${logCount} 条最近日志` : '暂无日志',
      detail: recentLogs[recentLogs.length - 1]?.message || '等待新的实时日志',
      meta: connected ? '实时连接中' : '连接已断开',
      route: '/logs',
      panelState: hasLogError ? 'error' : 'ok',
    },
    {
      id: 'sync',
      label: '同步状态',
      title: dashboardLastUpdated ? '已同步' : '未同步',
      detail: dashboardLastUpdated ? `最后刷新于 ${formatTime(dashboardLastUpdated)}` : '等待首次刷新',
      meta: panels.length ? `${panels.length} 个面板` : '暂无面板',
      route: '/dashboard',
      panelState: hasPanelError ? 'error' : 'ok',
    },
  ]
}

watch(() => store.novelId, () => {
  void refreshDashboardOnce()
})

onMounted(() => {
  void refreshDashboardOnce()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>
