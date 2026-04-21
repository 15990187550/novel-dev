import { describe, expect, it } from 'vitest'
import {
  buildChapterSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
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
          { chapter_id: 'ch-1' },
          { chapter_id: 'ch-2' },
        ],
      },
      currentChapterId: 'ch-2',
    })

    expect(summary.chapters.map((chapter) => chapter.chapter_id)).toEqual(['ch-1', 'ch-2'])
    expect(summary.chapters.find((chapter) => chapter.chapter_id === 'ch-2')?.isCurrent).toBe(true)
    expect(summary.stats).toEqual({
      total: 2,
      drafted: 1,
      edited: 1,
      inProgress: 2,
      pending: 0,
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
        { entity_id: 'e-old', name: '旧实体', updated_at: '2026-04-21T07:00:00Z' },
        { entity_id: 'e-new', name: '新实体', updated_at: '2026-04-21T10:00:00Z' },
      ],
      timelines: [
        { id: 't-1', tick: 4, narrative: '事件 4' },
        { id: 't-2', tick: 12, narrative: '事件 12' },
      ],
      foreshadowings: [
        { id: 'f-1', content: '伏笔 1', 埋下_time_tick: 2 },
        { id: 'f-2', content: '伏笔 2', 埋下_time_tick: 9 },
      ],
      pendingDocs: [
        { id: 'd-1', extraction_type: 'style', created_at: '2026-04-21T08:00:00Z' },
        { id: 'd-2', extraction_type: 'setting', created_at: '2026-04-21T09:30:00Z' },
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

  it('buildRiskItems merges panel errors, current chapter missing and the latest warning/error logs', () => {
    const risks = buildRiskItems({
      panels: [
        { id: 'data', label: '数据状态', state: 'error', route: '/dashboard' },
        { id: 'flow', label: '流程状态', state: 'ok', route: '/dashboard' },
      ],
      currentChapter: null,
      logs: [
        { timestamp: '2026-04-21T10:00:00Z', level: 'info', agent: 'NovelDirector', message: '正常日志' },
        { timestamp: '2026-04-21T10:01:00Z', level: 'warning', agent: 'ContextAgent', message: '上下文警告' },
        { timestamp: '2026-04-21T10:02:00Z', level: 'error', agent: 'WriterAgent', message: '写作错误' },
      ],
    })

    expect(risks.some((item) => item.type === 'panel_error' && item.label === '数据状态')).toBe(true)
    expect(risks.some((item) => item.type === 'current_chapter_missing')).toBe(true)
    expect(risks.some((item) => item.type === 'log_error' && item.detail.includes('写作错误'))).toBe(true)
    expect(risks.some((item) => item.type === 'log_warning' && item.detail.includes('上下文警告'))).toBe(true)
  })
})
import { describe, expect, it } from 'vitest'
import {
  buildChapterSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
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
          { chapter_id: 'ch-1' },
          { chapter_id: 'ch-2' },
        ],
      },
      currentChapterId: 'ch-2',
    })

    expect(summary.chapters.map((chapter) => chapter.chapter_id)).toEqual(['ch-1', 'ch-2'])
    expect(summary.chapters.find((chapter) => chapter.chapter_id === 'ch-2')?.isCurrent).toBe(true)
    expect(summary.stats).toEqual({
      total: 2,
      drafted: 1,
      edited: 1,
      inProgress: 2,
      pending: 0,
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
        { entity_id: 'e-old', name: '旧实体', updated_at: '2026-04-21T07:00:00Z' },
        { entity_id: 'e-new', name: '新实体', updated_at: '2026-04-21T10:00:00Z' },
      ],
      timelines: [
        { id: 't-1', tick: 4, narrative: '事件 4' },
        { id: 't-2', tick: 12, narrative: '事件 12' },
      ],
      foreshadowings: [
        { id: 'f-1', content: '伏笔 1', 埋下_time_tick: 2 },
        { id: 'f-2', content: '伏笔 2', 埋下_time_tick: 9 },
      ],
      pendingDocs: [
        { id: 'd-1', extraction_type: 'style', created_at: '2026-04-21T08:00:00Z' },
        { id: 'd-2', extraction_type: 'setting', created_at: '2026-04-21T09:30:00Z' },
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

  it('buildRiskItems merges panel errors, current chapter missing and the latest warning/error logs', () => {
    const risks = buildRiskItems({
      panels: [
        { id: 'data', label: '数据状态', state: 'error', route: '/dashboard' },
        { id: 'flow', label: '流程状态', state: 'ok', route: '/dashboard' },
      ],
      currentChapter: null,
      logs: [
        { timestamp: '2026-04-21T10:00:00Z', level: 'info', agent: 'NovelDirector', message: '正常日志' },
        { timestamp: '2026-04-21T10:01:00Z', level: 'warning', agent: 'ContextAgent', message: '上下文警告' },
        { timestamp: '2026-04-21T10:02:00Z', level: 'error', agent: 'WriterAgent', message: '写作错误' },
      ],
    })

    expect(risks.some((item) => item.type === 'panel_error' && item.label === '数据状态')).toBe(true)
    expect(risks.some((item) => item.type === 'current_chapter_missing')).toBe(true)
    expect(risks.some((item) => item.type === 'log_error' && item.detail.includes('写作错误'))).toBe(true)
    expect(risks.some((item) => item.type === 'log_warning' && item.detail.includes('上下文警告'))).toBe(true)
  })
})
