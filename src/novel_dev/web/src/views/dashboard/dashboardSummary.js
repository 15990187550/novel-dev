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

function toArray(value) {
  return Array.isArray(value) ? value : []
}

function parseTime(value) {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function normalizeNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
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

function buildChapterSummary({ chapters = [], volumePlan = null, currentChapterId = null, currentChapter = null } = {}) {
  const sourceChapters = toArray(chapters)
  const plannedIds = toArray(volumePlan?.chapters)
    .map((chapter) => chapter?.chapter_id)
    .filter(Boolean)

  const scopedChapters = plannedIds.length
    ? plannedIds
      .map((chapterId) => sourceChapters.find((chapter) => chapter?.chapter_id === chapterId))
      .filter(Boolean)
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
      label: '实体',
      detail: entity?.name || entity?.entity_id || entity?.id || '未命名实体',
      route: '/entities',
    })),
    ...toArray(pendingDocs).map((doc) => ({
      sort: parseTime(doc?.created_at),
      label: '资料',
      detail: doc?.extraction_type || doc?.title || doc?.id || '待处理资料',
      route: '/documents',
    })),
    ...toArray(timelines).map((timeline) => ({
      sort: normalizeNumber(timeline?.tick),
      label: '时间线',
      detail: timeline?.narrative || `Tick ${timeline?.tick ?? 0}`,
      route: '/timeline',
    })),
    ...toArray(foreshadowings).map((foreshadowing) => ({
      sort: normalizeNumber(foreshadowing?.埋下_time_tick),
      label: '伏笔',
      detail: foreshadowing?.content || foreshadowing?.id || '未命名伏笔',
      route: '/foreshadowings',
    })),
  ]

  return updates
    .sort((left, right) => right.sort - left.sort)
    .slice(0, 4)
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

function buildRiskItems({ panels = [], currentChapter = null, logs = [] } = {}) {
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

  if (!currentChapter) {
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

export {
  buildChapterSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
}
