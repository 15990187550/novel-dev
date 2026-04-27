import { describe, expect, it } from 'vitest'
import {
  buildChapterSummary,
  buildScoreSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
  buildStatusCards,
} from './dashboardSummary.js'

describe('dashboard summary helpers', () => {
  it('buildChapterSummary only keeps the current volume chapters and highlights the current chapter', () => {
    const summary = buildChapterSummary({
      chapters: [
        { chapter_id: 'ch-1', chapter_number: 1, title: '第一章', status: 'drafted' },
        { chapter_id: 'ch-2', chapter_number: 2, title: '第二章', status: 'edited' },
        { chapter_id: 'ch-3', chapter_number: 3, title: '第三章', status: 'pending' },
      ],
      volumePlan: {
        chapters: [
          { chapter_id: 'ch-1', title: '第一章（计划）' },
          { chapter_id: 'ch-2', title: '第二章（计划）' },
          { chapter_id: 'ch-4', title: '第四章（计划）', summary: '计划内但尚未落库' },
        ],
      },
      currentChapterId: 'ch-2',
    })

    expect(summary.chapters.map((chapter) => chapter.chapter_id)).toEqual(['ch-1', 'ch-2', 'ch-4'])
    expect(summary.chapters.find((chapter) => chapter.chapter_id === 'ch-2')?.isCurrent).toBe(true)
    expect(summary.chapters.find((chapter) => chapter.chapter_id === 'ch-4')).toMatchObject({
      chapter_id: 'ch-4',
      title: '第四章（计划）',
      summary: '计划内但尚未落库',
    })
    expect(summary.stats).toEqual({
      total: 3,
      drafted: 1,
      edited: 1,
      inProgress: 2,
      pending: 1,
      archived: 0,
    })
  })

  it('buildChapterSummary falls back to all chapters when there is no volume plan', () => {
    const summary = buildChapterSummary({
      chapters: [
        { chapter_id: 'ch-1', chapter_number: 1, title: '第一章', status: 'pending' },
        { chapter_id: 'ch-2', chapter_number: 2, title: '第二章', status: 'archived' },
      ],
      currentChapterId: 'ch-1',
    })

    expect(summary.chapters.map((chapter) => chapter.chapter_id)).toEqual(['ch-1', 'ch-2'])
    expect(summary.chapters[0].isCurrent).toBe(true)
    expect(summary.stats.total).toBe(2)
  })

  it('buildScoreSummary keeps only scored chapters and averages radar dimensions', () => {
    const summary = buildScoreSummary([
      {
        chapter_id: 'ch-1',
        chapter_number: 1,
        title: '第一章',
        summary: '开篇试炼',
        score_overall: 80,
        score_breakdown: {
          plot_tension: { score: 90, comment: '钩子明确' },
          characterization: 70,
        },
        review_feedback: { summary_feedback: '节奏可用' },
      },
      {
        chapter_id: 'ch-2',
        chapter_number: 2,
        title: '第二章',
        score_overall: null,
        score_breakdown: {},
      },
      {
        chapter_id: 'ch-3',
        chapter_number: 3,
        title: '第三章',
        score_overall: 90,
        score_breakdown: {
          plot_tension: 70,
          characterization: { score: 90 },
        },
      },
    ])

    expect(summary.chapters.map((chapter) => chapter.chapter_id)).toEqual(['ch-1', 'ch-3'])
    expect(summary.chapters[0]).toMatchObject({
      displayScore: 80,
      scoreDetail: '节奏可用',
    })
    expect(summary.scores).toEqual({
      plot_tension: 80,
      characterization: 80,
    })
  })

  it('buildDataSummary aggregates entity, timeline, foreshadowing and pending document counts', () => {
    const summary = buildDataSummary({
      entities: [{ id: 'e1' }, { id: 'e2' }],
      timelines: [{ id: 't1' }, { id: 't2' }, { id: 't3' }],
      foreshadowings: [{ id: 'f1' }, { id: 'f2' }, { id: 'f3' }, { id: 'f4' }],
      pendingDocs: [{ id: 'd1' }, { id: 'd2' }, { id: 'd3' }],
    })

    expect(summary).toEqual({
      entities: 2,
      timelines: 3,
      foreshadowings: 4,
      pendingDocs: 3,
      total: 12,
    })
  })

  it('buildRecentUpdates sorts by each source timestamp and truncates to four items', () => {
    const updates = buildRecentUpdates({
      entities: [
        { entity_id: 'e-new', name: '新实体', updated_at: '2026-04-21T10:00:00Z' },
      ],
      pendingDocs: [
        { id: 'd-2', extraction_type: 'setting', created_at: '2026-04-21T09:30:00Z' },
      ],
      timelines: [
        { id: 't-1', tick: 12, narrative: '事件 1' },
        { id: 't-2', tick: 3, narrative: '事件 2' },
      ],
      foreshadowings: [
        { id: 'f-1', content: '伏笔 1', 埋下_time_tick: 9 },
        { id: 'f-2', content: '伏笔 2', 埋下_time_tick: 1 },
      ],
    })

    expect(updates).toHaveLength(4)
    expect(updates.map((item) => item.route)).toEqual([
      '/entities',
      '/documents',
      '/timeline',
      '/foreshadowings',
    ])
    expect(updates[0]).toMatchObject({
      label: '实体',
      detail: '新实体',
    })
    expect(updates[1]).toMatchObject({
      label: '资料',
      detail: 'setting',
    })
    expect(updates[2]).toMatchObject({
      label: '时间线',
      detail: '事件 1',
    })
    expect(updates[3]).toMatchObject({
      label: '伏笔',
      detail: '伏笔 1',
    })
  })

  it('buildRecommendedActions uses volume_plan as the main action during volume planning', () => {
    const actions = buildRecommendedActions({
      currentPhase: 'volume_planning',
      currentChapter: { chapter_id: 'ch-2' },
      volumePlan: { chapters: [{ chapter_id: 'ch-1' }, { chapter_id: 'ch-2' }] },
    })

    expect(actions[0]).toMatchObject({
      key: 'volume_plan',
      phase: 'volume_planning',
    })
    expect(actions[0].reason).toContain('当前已完成脑暴')
  })

  it('buildRecommendedActions covers the full phase set', () => {
    const phaseCases = [
      ['brainstorming', 'brainstorm'],
      ['volume_planning', 'volume_plan'],
      ['context_preparation', 'context'],
      ['drafting', 'draft'],
      ['reviewing', 'advance'],
      ['editing', 'advance'],
      ['fast_reviewing', 'advance'],
      ['librarian', 'librarian'],
      ['completed', 'export'],
    ]

    for (const [phase, key] of phaseCases) {
      const actions = buildRecommendedActions({
        currentPhase: phase,
        currentChapter: { chapter_id: 'ch-1' },
        volumePlan: { chapters: [{ chapter_id: 'ch-1' }] },
      })

      expect(actions[0]).toMatchObject({ phase, key })
      expect(actions[0].reason).toBeTruthy()
    }
  })

  it('buildRiskItems reports missing current chapter only in phases that need it', () => {
    const riskyPhase = buildRiskItems({
      panels: [
        { id: 'data', label: '数据状态', state: 'error', route: '/dashboard' },
        { id: 'flow', label: '流程状态', state: 'ok', route: '/dashboard' },
      ],
      currentChapter: null,
      currentPhase: 'drafting',
      logs: [
        { timestamp: '2026-04-21T10:00:00Z', level: 'info', agent: 'NovelDirector', message: '正常日志' },
        { timestamp: '2026-04-21T10:01:00Z', level: 'warning', agent: 'ContextAgent', message: '上下文警告' },
        { timestamp: '2026-04-21T10:02:00Z', level: 'error', agent: 'WriterAgent', message: '写作错误' },
      ],
    })

    expect(riskyPhase.some((item) => item.type === 'panel_error' && item.label === '数据状态')).toBe(true)
    expect(riskyPhase.some((item) => item.type === 'current_chapter_missing')).toBe(true)
    expect(riskyPhase.some((item) => item.type === 'log_error' && item.detail.includes('写作错误'))).toBe(true)
    expect(riskyPhase.some((item) => item.type === 'log_warning' && item.detail.includes('上下文警告'))).toBe(true)

    const safePhase = buildRiskItems({
      currentChapter: null,
      currentPhase: 'brainstorming',
      logs: [],
    })

    expect(safePhase.some((item) => item.type === 'current_chapter_missing')).toBe(false)
    expect(buildRiskItems({ currentChapter: null, currentPhase: 'completed', logs: [] }).some((item) => item.type === 'current_chapter_missing')).toBe(false)
  })

  it('buildStatusCards folds panel errors and recent logs into the dashboard overview', () => {
    const cards = buildStatusCards({
      summary: {
        total: 7,
        entities: 2,
        timelines: 3,
        foreshadowings: 1,
        pendingDocs: 1,
      },
      panels: [
        { id: 'entities', state: 'ready' },
        { id: 'timelines', state: 'error' },
      ],
      currentPhaseLabel: '草稿写作',
      currentVolumeChapter: 'V3 / C8',
      currentChapter: { title: '第八章' },
      recentLogs: [
        { level: 'info', message: '运行正常' },
        { level: 'error', message: '渲染失败' },
      ],
      connected: true,
      dashboardLastUpdated: '2026-04-21 10:03:00',
    })

    expect(cards).toHaveLength(4)
    expect(cards[1]).toMatchObject({
      id: 'data',
      title: '7',
      meta: '存在面板异常',
      panelState: 'error',
    })
    expect(cards[2]).toMatchObject({
      id: 'logs',
      title: '2 条最近日志',
      meta: '实时连接中',
      panelState: 'error',
    })
    expect(cards[3]).toMatchObject({
      id: 'sync',
      title: '已同步',
      detail: '最后刷新于 2026-04-21 10:03:00',
    })
  })
})
