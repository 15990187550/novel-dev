const STATUS_BUCKETS = {
  drafted: 'drafted',
  edited: 'edited',
  pending: 'pending',
  archived: 'archived',
}

const PHASE_ACTIONS = {
  brainstorming: { key: 'brainstorm', label: '脑暴', route: '/dashboard' },
  volume_planning: { key: 'volume_plan', label: '分卷', route: '/volume-plan' },
  context_preparation: { key: 'context', label: '上下文', route: '/chapters' },
  drafting: { key: 'draft', label: '草稿', route: '/chapters' },
  reviewing: { key: 'advance', label: '推进', route: '/logs' },
  editing: { key: 'advance', label: '推进', route: '/logs' },
  fast_reviewing: { key: 'advance', label: '推进', route: '/logs' },
  librarian: { key: 'librarian', label: '归档', route: '/logs' },
  completed: { key: 'export', label: '导出', route: '/dashboard' },
}

const PHASES_REQUIRING_CURRENT_CHAPTER = new Set([
  'context_preparation',
  'drafting',
  'reviewing',
  'editing',
  'fast_reviewing',
  'librarian',
])

function toArray(value) {
  return Array.isArray(value) ? value : []
}

function parseTime(value) {
  return timestampMs(value)
}

function normalizeNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function hasRealTime(value) {
  return parseTime(value) > 0
}

function chapterRoute(chapter) {
  const id = chapter?.chapter_id || chapter?.id
  return id ? `/chapters/${id}` : '/chapters'
}

function statusLabel(status) {
  switch (status) {
    case 'drafted':
      return '已起草'
    case 'edited':
      return '已编辑'
    case 'archived':
      return '已归档'
    default:
      return '待处理'
  }
}

function scoreValue(value) {
  if (value && typeof value === 'object') return normalizeNumber(value.score)
  return normalizeNumber(value)
}

function hasScore(chapter) {
  if (chapter?.score_overall != null && chapter.score_overall !== '' && Number.isFinite(Number(chapter.score_overall))) return true
  return Object.values(chapter?.score_breakdown || {}).some((value) => scoreValue(value) > 0)
}

function scoreDetail(chapter) {
  const feedback = chapter?.review_feedback
  if (typeof feedback === 'string') return feedback
  if (feedback?.summary_feedback) return feedback.summary_feedback
  if (feedback?.feedback) return feedback.feedback
  if (chapter?.summary) return chapter.summary
  return ''
}

function buildScoreSummary(chapters = []) {
  const scoredChapters = toArray(chapters)
    .filter(hasScore)
    .map((chapter) => ({
      ...chapter,
      displayScore: chapter?.score_overall != null && chapter.score_overall !== '' && Number.isFinite(Number(chapter.score_overall))
        ? normalizeNumber(chapter.score_overall)
        : Math.round(
          Object.values(chapter?.score_breakdown || {})
            .map(scoreValue)
            .filter((value) => value > 0)
            .reduce((sum, value, _, values) => sum + value / values.length, 0)
        ),
      scoreDetail: scoreDetail(chapter),
    }))

  const totals = {}
  const counts = {}
  for (const chapter of scoredChapters) {
    for (const [key, value] of Object.entries(chapter.score_breakdown || {})) {
      const score = scoreValue(value)
      if (score <= 0) continue
      totals[key] = (totals[key] || 0) + score
      counts[key] = (counts[key] || 0) + 1
    }
  }

  const scores = {}
  for (const [key, total] of Object.entries(totals)) {
    scores[key] = Math.round(total / counts[key])
  }

  return { chapters: scoredChapters, scores }
}

function buildChapterSummary({ chapters = [], volumePlan = null, currentChapterId = null, currentChapter = null } = {}) {
  const sourceChapters = toArray(chapters)
  const plannedChapters = toArray(volumePlan?.chapters)
  const chapterById = new Map(sourceChapters.map((chapter) => [chapter?.chapter_id, chapter]))

  const scopedChapters = plannedChapters.length
    ? [
      ...plannedChapters.map((planChapter) => {
        const chapter = chapterById.get(planChapter?.chapter_id)
        return chapter ? { ...planChapter, ...chapter } : { ...planChapter }
      }),
    ]
    : sourceChapters

  const activeChapterId = currentChapterId || currentChapter?.chapter_id || currentChapter?.id || null
  const stats = scopedChapters.reduce((acc, chapter) => {
    const bucket = STATUS_BUCKETS[chapter?.status] || 'pending'
    acc[bucket] += 1
    if (bucket === 'drafted' || bucket === 'edited') acc.inProgress += 1
    return acc
  }, { total: scopedChapters.length, drafted: 0, edited: 0, pending: 0, archived: 0, inProgress: 0 })

  return {
    chapters: scopedChapters.map((chapter) => ({
      ...chapter,
      isCurrent: chapter?.chapter_id === activeChapterId,
      statusLabel: statusLabel(chapter?.status),
      route: chapterRoute(chapter),
    })),
    stats,
  }
}

function buildDataSummary({ entities = [], timelines = [], foreshadowings = [], pendingDocs = [] } = {}) {
  const summary = {
    entities: toArray(entities).length,
    timelines: toArray(timelines).length,
    foreshadowings: toArray(foreshadowings).length,
    pendingDocs: toArray(pendingDocs).length,
  }

  return {
    ...summary,
    total: summary.entities + summary.timelines + summary.foreshadowings + summary.pendingDocs,
  }
}

function buildRecentUpdates({ entities = [], timelines = [], foreshadowings = [], pendingDocs = [] } = {}) {
  const updates = [
    ...toArray(entities).map((entity) => ({
      sort: parseTime(entity?.updated_at || entity?.created_at),
      layer: hasRealTime(entity?.updated_at || entity?.created_at) ? 0 : 2,
      layerSort: parseTime(entity?.updated_at || entity?.created_at),
      label: '实体',
      detail: entity?.name || entity?.entity_id || entity?.id || '未命名实体',
      route: '/entities',
    })),
    ...toArray(pendingDocs).map((doc) => ({
      sort: parseTime(doc?.created_at),
      layer: hasRealTime(doc?.created_at) ? 0 : 2,
      layerSort: parseTime(doc?.created_at),
      label: '资料',
      detail: doc?.extraction_type || doc?.title || doc?.id || '待处理资料',
      route: '/documents',
    })),
    ...toArray(timelines).map((timeline) => ({
      sort: normalizeNumber(timeline?.tick),
      layer: 1,
      layerSort: normalizeNumber(timeline?.tick),
      label: '时间线',
      detail: timeline?.narrative || `Tick ${timeline?.tick ?? 0}`,
      route: '/timeline',
    })),
    ...toArray(foreshadowings).map((foreshadowing) => ({
      sort: normalizeNumber(foreshadowing?.埋下_time_tick),
      layer: 1,
      layerSort: normalizeNumber(foreshadowing?.埋下_time_tick),
      label: '伏笔',
      detail: foreshadowing?.content || foreshadowing?.id || '未命名伏笔',
      route: '/foreshadowings',
    })),
  ]

  return updates
    .sort((left, right) => {
      if (left.layer !== right.layer) return left.layer - right.layer
      if (right.layerSort !== left.layerSort) return right.layerSort - left.layerSort
      return 0
    })
    .slice(0, 4)
    .map(({ sort, label, detail, route }) => ({ sort, label, detail, route }))
}

function buildRecommendedActions({ currentPhase = '', currentChapter = null, volumePlan = null } = {}) {
  const base = PHASE_ACTIONS[currentPhase] || PHASE_ACTIONS.brainstorming
  let reason = ''

  switch (currentPhase) {
    case 'brainstorming':
      reason = '当前还在脑暴阶段，先把大纲跑通。'
      break
    case 'volume_planning':
      reason = '当前已完成脑暴，可以继续生成卷规划。'
      break
    case 'context_preparation':
      reason = currentChapter ? '当前卷规划已可用，适合准备当前章上下文。' : '当前章缺失，先补齐章节信息再准备上下文。'
      break
    case 'drafting':
      reason = '上下文已准备，继续生成草稿。'
      break
    case 'reviewing':
      reason = '当前处于审稿中，继续推进到编辑或快速审查。'
      break
    case 'editing':
      reason = '当前处于编辑润色阶段，继续推进。'
      break
    case 'fast_reviewing':
      reason = '当前处于快速审查阶段，继续推进。'
      break
    case 'librarian':
      reason = '当前处于归档阶段，适合完成世界状态收束。'
      break
    case 'completed':
      reason = '小说已完成，可以导出或回看最新状态。'
      break
    default:
      reason = '保持当前流程推进。'
  }

  const action = {
    key: base.key,
    phase: currentPhase || 'brainstorming',
    label: base.label,
    reason,
    route: base.route,
  }

  if (currentPhase === 'volume_planning' && volumePlan?.chapters?.length) {
    action.detail = `当前卷共有 ${volumePlan.chapters.length} 章`
  }

  return [action]
}

function buildRiskItems({ panels = [], currentChapter = null, currentPhase = '', logs = [] } = {}) {
  const risks = []

  for (const panel of toArray(panels)) {
    if (panel?.state === 'error') {
      risks.push({
        type: 'panel_error',
        label: panel.label || panel.id || '面板异常',
        detail: '面板状态异常',
        route: panel.route || '/dashboard',
      })
    }
  }

  if (!currentChapter && PHASES_REQUIRING_CURRENT_CHAPTER.has(currentPhase)) {
    risks.push({
      type: 'current_chapter_missing',
      label: '当前章节缺失',
      detail: '当前阶段没有可用章节，请先检查当前卷/章是否已设置。',
      route: '/chapters',
    })
  }

  const recentWarningsAndErrors = toArray(logs)
    .filter((log) => ['warning', 'error'].includes(log?.level))
    .sort((left, right) => parseTime(right?.timestamp) - parseTime(left?.timestamp))
    .slice(0, 2)

  for (const log of recentWarningsAndErrors) {
    risks.push({
      type: log.level === 'error' ? 'log_error' : 'log_warning',
      label: log.agent || '日志',
      detail: log.message || '日志异常',
      route: '/logs',
    })
  }

  return risks
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
  const hasPanelError = toArray(panels).some((panel) => panel?.state === 'error' || panel?.panelState === 'error')
  const hasLogError = toArray(recentLogs).some((log) => log?.level === 'error')
  const logCount = toArray(recentLogs).length
  const lastLogMessage = toArray(recentLogs)[toArray(recentLogs).length - 1]?.message || '等待新的实时日志'

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
      detail: lastLogMessage,
      meta: connected ? '实时连接中' : '连接已断开',
      route: '/logs',
      panelState: hasLogError ? 'error' : 'ok',
    },
    {
      id: 'sync',
      label: '同步状态',
      title: dashboardLastUpdated ? '已同步' : '未同步',
      detail: dashboardLastUpdated ? `最后刷新于 ${dashboardLastUpdated}` : '等待首次刷新',
      meta: toArray(panels).length ? `${panels.length} 个面板` : '暂无面板',
      route: '/dashboard',
      panelState: hasPanelError ? 'error' : 'ok',
    },
  ]
}

export {
  buildChapterSummary,
  buildScoreSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
  buildStatusCards,
}
import { timestampMs } from '@/utils/time.js'
