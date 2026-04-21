import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api.js'
import { useNovelStore } from './novel.js'

vi.mock('@/api.js', () => ({
  getNovelState: vi.fn(),
  getArchiveStats: vi.fn(),
  getChapters: vi.fn(),
  getSynopsis: vi.fn(),
  getVolumePlan: vi.fn(),
  getEntities: vi.fn(),
  getEntityRelationships: vi.fn(),
  getTimelines: vi.fn(),
  getForeshadowings: vi.fn(),
  getPendingDocs: vi.fn(),
  getOutlineWorkbench: vi.fn(),
  getOutlineWorkbenchMessages: vi.fn(),
  submitOutlineFeedback: vi.fn(),
}))

describe('novel store dashboard loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(api.getSynopsis).mockResolvedValue(null)
    vi.mocked(api.getVolumePlan).mockResolvedValue(null)
  })

  it('marks every dashboard panel ready after loadDashboardSupplemental succeeds', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    vi.mocked(api.getEntities).mockResolvedValue({ items: [{ id: 'entity-1' }] })
    vi.mocked(api.getEntityRelationships).mockResolvedValue({ items: [{ id: 'rel-1' }] })
    vi.mocked(api.getTimelines).mockResolvedValue({ items: [{ id: 'timeline-1' }] })
    vi.mocked(api.getForeshadowings).mockResolvedValue({ items: [{ id: 'foreshadowing-1' }] })
    vi.mocked(api.getPendingDocs).mockResolvedValue({ items: [{ id: 'doc-1' }] })

    await store.loadDashboardSupplemental()

    expect(store.dashboardPanels.entities).toEqual({ state: 'ready', error: '' })
    expect(store.dashboardPanels.timelines).toEqual({ state: 'ready', error: '' })
    expect(store.dashboardPanels.foreshadowings).toEqual({ state: 'ready', error: '' })
    expect(store.dashboardPanels.pendingDocs).toEqual({ state: 'ready', error: '' })
    expect(store.dashboardLastUpdated).toBeTruthy()
  })

  it('marks a failed supplemental panel as error and clears its stale data', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.entities = [{ id: 'stale-entity' }]
    store.entityRelationships = [{ id: 'stale-rel' }]
    store.timelines = [{ id: 'stale-timeline' }]
    store.foreshadowings = [{ id: 'stale-foreshadowing' }]
    store.pendingDocs = [{ id: 'stale-doc' }]
    store.dashboardPanels.entities.state = 'ready'
    store.dashboardPanels.timelines.state = 'ready'
    store.dashboardPanels.foreshadowings.state = 'ready'
    store.dashboardPanels.pendingDocs.state = 'ready'
    store.dashboardLastUpdated = '2026-04-20T00:00:00.000Z'

    vi.mocked(api.getEntities).mockResolvedValue({ items: [{ id: 'entity-1' }] })
    vi.mocked(api.getEntityRelationships).mockResolvedValue({ items: [{ id: 'rel-1' }] })
    vi.mocked(api.getTimelines).mockResolvedValue({ items: [{ id: 'timeline-1' }] })
    vi.mocked(api.getForeshadowings).mockResolvedValue({ items: [{ id: 'foreshadowing-1' }] })
    vi.mocked(api.getPendingDocs).mockRejectedValue(new Error('pending docs failed'))

    await store.loadDashboardSupplemental()

    expect(store.dashboardPanels.entities).toEqual({ state: 'ready', error: '' })
    expect(store.dashboardPanels.timelines).toEqual({ state: 'ready', error: '' })
    expect(store.dashboardPanels.foreshadowings).toEqual({ state: 'ready', error: '' })
    expect(store.dashboardPanels.pendingDocs).toEqual({
      state: 'error',
      error: 'pending docs failed',
    })
    expect(store.entities).toEqual([{ id: 'entity-1' }])
    expect(store.entityRelationships).toEqual([{ id: 'rel-1' }])
    expect(store.timelines).toEqual([{ id: 'timeline-1' }])
    expect(store.foreshadowings).toEqual([{ id: 'foreshadowing-1' }])
    expect(store.pendingDocs).toEqual([])
    expect(store.dashboardLastUpdated).toBeTruthy()
  })

  it('resets supplemental dashboard state when switching novels', async () => {
    const store = useNovelStore()

    vi.mocked(api.getNovelState)
      .mockResolvedValueOnce({
        current_phase: 'drafting',
        current_chapter_id: 'ch-1',
        checkpoint_data: {
          current_volume_plan: {
            chapters: [{ chapter_id: 'ch-1', summary: '第一章计划摘要' }],
          },
        },
      })
      .mockResolvedValueOnce({
        current_phase: 'editing',
        current_chapter_id: 'ch-2',
        checkpoint_data: {
          current_volume_plan: {
            chapters: [{ chapter_id: 'ch-2', summary: '第二章计划摘要' }],
          },
        },
      })

    vi.mocked(api.getArchiveStats)
      .mockResolvedValueOnce({ total: 1 })
      .mockResolvedValueOnce({ total: 2 })
    vi.mocked(api.getChapters)
      .mockResolvedValueOnce({
        items: [{ chapter_id: 'ch-1', title: '第一章', status: 'drafted', word_count: 1200 }],
      })
      .mockResolvedValueOnce({
        items: [{ chapter_id: 'ch-2', title: '第二章', status: 'edited', word_count: 2400 }],
      })

    await store.loadNovel('novel-1')

    store.entities = [{ id: 'stale-entity' }]
    store.entityRelationships = [{ id: 'stale-rel' }]
    store.timelines = [{ id: 'stale-timeline' }]
    store.foreshadowings = [{ id: 'stale-foreshadowing' }]
    store.pendingDocs = [{ id: 'stale-doc' }]
    store.dashboardPanels.entities.state = 'ready'
    store.dashboardPanels.entities.error = ''
    store.dashboardPanels.timelines.state = 'ready'
    store.dashboardPanels.foreshadowings.state = 'error'
    store.dashboardPanels.foreshadowings.error = 'old error'
    store.dashboardPanels.pendingDocs.state = 'ready'
    store.dashboardLastUpdated = '2026-04-20T00:00:00.000Z'

    await store.loadNovel('novel-2')

    expect(store.novelId).toBe('novel-2')
    expect(store.entities).toEqual([])
    expect(store.entityRelationships).toEqual([])
    expect(store.timelines).toEqual([])
    expect(store.foreshadowings).toEqual([])
    expect(store.pendingDocs).toEqual([])
    expect(store.dashboardPanels.entities).toEqual({ state: 'idle', error: '' })
    expect(store.dashboardPanels.timelines).toEqual({ state: 'idle', error: '' })
    expect(store.dashboardPanels.foreshadowings).toEqual({ state: 'idle', error: '' })
    expect(store.dashboardPanels.pendingDocs).toEqual({ state: 'idle', error: '' })
    expect(store.dashboardLastUpdated).toBe('')
    expect(store.currentChapter).toEqual({
      chapter_id: 'ch-2',
      title: '第二章',
      status: 'edited',
      word_count: 2400,
      summary: '第二章计划摘要',
    })
  })

  it('refreshes state with fresh chapters and preserves the merged currentChapter result', async () => {
    const store = useNovelStore()

    vi.mocked(api.getNovelState)
      .mockResolvedValueOnce({
        current_phase: 'drafting',
        current_chapter_id: 'ch-1',
        checkpoint_data: {
          current_volume_plan: {
            chapters: [
              { chapter_id: 'ch-1', summary: '第一章计划摘要' },
            ],
          },
        },
      })
      .mockResolvedValueOnce({
        current_phase: 'editing',
        current_chapter_id: 'ch-2',
        checkpoint_data: {
          current_volume_plan: {
            chapters: [
              { chapter_id: 'ch-2', summary: '刷新后的计划摘要' },
            ],
          },
        },
      })

    vi.mocked(api.getArchiveStats)
      .mockResolvedValueOnce({ total: 2 })
      .mockResolvedValueOnce({ total: 3 })
    vi.mocked(api.getChapters)
      .mockResolvedValueOnce({
        items: [
          {
            chapter_id: 'ch-1',
            title: '第一章',
            status: 'drafted',
            word_count: 1800,
            score_breakdown: { plot: 72 },
            body: '章节一正文',
          },
          {
            chapter_id: 'ch-2',
            title: '第二章',
            status: 'pending',
            word_count: 900,
            score_breakdown: { plot: 60 },
            body: '章节二草稿',
          },
        ],
      })
      .mockResolvedValueOnce({
        items: [
          {
            chapter_id: 'ch-1',
            title: '第一章（旧值）',
            status: 'drafted',
            word_count: 1800,
            score_breakdown: { plot: 72 },
            body: '章节一旧正文',
          },
          {
            chapter_id: 'ch-2',
            title: '第二章（刷新后正文）',
            status: 'edited',
            word_count: 2600,
            score_breakdown: { plot: 91, characterization: 88 },
            body: '章节二正文',
          },
        ],
      })
    vi.mocked(api.getEntities).mockResolvedValue({ items: [] })
    vi.mocked(api.getEntityRelationships).mockResolvedValue({ items: [] })
    vi.mocked(api.getTimelines).mockResolvedValue({ items: [] })
    vi.mocked(api.getForeshadowings).mockResolvedValue({ items: [] })
    vi.mocked(api.getPendingDocs).mockResolvedValue({ items: [] })

    await store.loadNovel('novel-1')

    expect(store.currentChapter).toEqual({
      chapter_id: 'ch-1',
      title: '第一章',
      status: 'drafted',
      word_count: 1800,
      score_breakdown: { plot: 72 },
      body: '章节一正文',
      summary: '第一章计划摘要',
    })

    await store.refreshDashboard()

    expect(store.novelState.current_phase).toBe('editing')
    expect(store.archiveStats).toEqual({ total: 3 })
    expect(store.currentChapter).toEqual({
      chapter_id: 'ch-2',
      title: '第二章（刷新后正文）',
      status: 'edited',
      word_count: 2600,
      score_breakdown: { plot: 91, characterization: 88 },
      body: '章节二正文',
      summary: '刷新后的计划摘要',
    })
    expect(store.dashboardLastUpdated).toBeTruthy()
  })

  it('refreshOutlineWorkbench stores normalized items, selection and messages', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    vi.mocked(api.getOutlineWorkbench).mockResolvedValue({
      outline_items: [
        {
          outline_type: 'synopsis',
          outline_ref: 'synopsis',
          title: '总纲',
          status: 'ready',
        },
        {
          outline_type: 'volume',
          outline_ref: 'vol_2',
          title: '第二卷',
          status: 'ready',
        },
      ],
      context_window: {
        recent_messages: [{ id: 'msg-inline', content: 'inline' }],
      },
    })
    vi.mocked(api.getOutlineWorkbenchMessages).mockResolvedValue({
      recent_messages: [{ id: 'msg-1', content: 'message-1' }],
      conversation_summary: 'summary-1',
      last_result_snapshot: { title: '快照 1' },
    })

    await store.refreshOutlineWorkbench({
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })

    expect(api.getOutlineWorkbench).toHaveBeenCalledWith('novel-1', {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(api.getOutlineWorkbenchMessages).toHaveBeenCalledWith('novel-1', {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(store.outlineWorkbench.items.map((item) => item.itemId)).toEqual([
      'synopsis:synopsis',
      'volume:vol_2',
    ])
    expect(store.outlineWorkbench.selection).toEqual({
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(store.outlineWorkbench.currentItem).toEqual({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
    expect(store.outlineWorkbench.messages).toEqual([{ id: 'msg-1', content: 'message-1' }])
    expect(store.outlineWorkbench.conversationSummary).toBe('summary-1')
    expect(store.outlineWorkbench.lastResultSnapshot).toEqual({ title: '快照 1' })
  })

  it('refreshOutlineWorkbench keeps selection and current item separate', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }

    vi.mocked(api.getOutlineWorkbench).mockResolvedValue({
      outline_type: 'volume',
      outline_ref: 'vol_2',
      outline_items: [
        {
          outline_type: 'synopsis',
          outline_ref: 'synopsis',
          title: '总纲',
          status: 'ready',
        },
        {
          outline_type: 'volume',
          outline_ref: 'vol_2',
          title: '第二卷',
          status: 'ready',
        },
      ],
    })
    vi.mocked(api.getOutlineWorkbenchMessages).mockResolvedValue({
      recent_messages: [{ id: 'msg-current', content: 'message-current' }],
      conversation_summary: 'summary-current',
      last_result_snapshot: { title: '快照 current' },
    })

    await store.refreshOutlineWorkbench()

    expect(api.getOutlineWorkbench).toHaveBeenCalledWith('novel-1', {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
    expect(api.getOutlineWorkbenchMessages).toHaveBeenCalledWith('novel-1', {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
    expect(store.outlineWorkbench.selection).toEqual({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
    expect(store.outlineWorkbench.currentItem).toEqual({
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(store.outlineWorkbench.items.find((item) => item.itemId === 'volume:vol_2')?.isCurrent).toBe(true)
    expect(store.outlineWorkbench.items.find((item) => item.itemId === 'synopsis:synopsis')?.isCurrent).toBe(false)
  })

  it('refreshOutlineWorkbench defaults selection to service current item when synopsis is absent', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    vi.mocked(api.getOutlineWorkbench).mockResolvedValue({
      outline_type: 'volume',
      outline_ref: 'vol_3',
      outline_items: [
        {
          outline_type: 'volume',
          outline_ref: 'vol_2',
          title: '第二卷',
          status: 'ready',
        },
        {
          outline_type: 'volume',
          outline_ref: 'vol_3',
          title: '第三卷',
          status: 'active',
        },
      ],
    })
    vi.mocked(api.getOutlineWorkbenchMessages).mockResolvedValue({
      recent_messages: [{ id: 'msg-vol-3', content: 'message-vol-3' }],
      conversation_summary: 'summary-vol-3',
      last_result_snapshot: { title: '快照 vol-3' },
    })

    await store.refreshOutlineWorkbench()

    expect(api.getOutlineWorkbenchMessages).toHaveBeenCalledWith('novel-1', {
      outline_type: 'volume',
      outline_ref: 'vol_3',
    })
    expect(store.outlineWorkbench.selection).toEqual({
      outline_type: 'volume',
      outline_ref: 'vol_3',
    })
    expect(store.outlineWorkbench.currentItem).toEqual({
      outline_type: 'volume',
      outline_ref: 'vol_3',
    })
  })

  it('submitOutlineFeedback keeps selection but updates current item from service', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    }
    store.outlineWorkbench.currentItem = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    }

    vi.mocked(api.submitOutlineFeedback).mockResolvedValue({
      assistant_message: { id: 'assistant-1', content: '已处理' },
    })
    vi.mocked(api.getOutlineWorkbench).mockResolvedValue({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
      outline_items: [
        {
          outline_type: 'synopsis',
          outline_ref: 'synopsis',
          title: '总纲',
          status: 'ready',
        },
        {
          outline_type: 'volume',
          outline_ref: 'vol_2',
          title: '第二卷',
          status: 'ready',
        },
      ],
      context_window: {
        recent_messages: [],
      },
    })
    vi.mocked(api.getOutlineWorkbenchMessages).mockResolvedValue({
      recent_messages: [{ id: 'msg-2', content: 'message-2' }],
      conversation_summary: 'summary-2',
      last_result_snapshot: { title: '快照 2' },
    })

    await store.submitOutlineFeedback({ content: '补充第二卷的反派动机' })

    expect(api.submitOutlineFeedback).toHaveBeenCalledWith('novel-1', {
      outline_type: 'volume',
      outline_ref: 'vol_2',
      content: '补充第二卷的反派动机',
    })
    expect(api.getOutlineWorkbenchMessages).toHaveBeenCalledWith('novel-1', {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(store.outlineWorkbench.selection).toEqual({
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(store.outlineWorkbench.currentItem).toEqual({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
    expect(store.outlineWorkbench.items.find((item) => item.itemId === 'synopsis:synopsis')?.isCurrent).toBe(true)
    expect(store.outlineWorkbench.items.find((item) => item.itemId === 'volume:vol_2')?.isCurrent).toBe(false)
    expect(store.outlineWorkbench.messages).toEqual([{ id: 'msg-2', content: 'message-2' }])
  })
})
