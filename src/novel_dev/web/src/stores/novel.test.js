import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api.js'
import { useNovelStore } from './novel.js'

function createDeferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

vi.mock('@/api.js', () => ({
  getNovelState: vi.fn(),
  getArchiveStats: vi.fn(),
  getChapters: vi.fn(),
  getSynopsis: vi.fn(),
  getVolumePlan: vi.fn(),
  deleteNovel: vi.fn(),
  getEntities: vi.fn(),
  getEntityRelationships: vi.fn(),
  getTimelines: vi.fn(),
  getForeshadowings: vi.fn(),
  getPendingDocs: vi.fn(),
  getOutlineWorkbench: vi.fn(),
  getOutlineWorkbenchMessages: vi.fn(),
  getBrainstormWorkspace: vi.fn(),
  startBrainstormWorkspace: vi.fn(),
  submitBrainstormWorkspace: vi.fn(),
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

  it('skips volume plan request when the checkpoint has no current volume plan', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    vi.mocked(api.getNovelState).mockResolvedValue({
      current_phase: 'brainstorming',
      current_chapter_id: null,
      checkpoint_data: {
        synopsis_data: {
          title: '道照诸天',
        },
      },
    })
    vi.mocked(api.getArchiveStats).mockResolvedValue({})
    vi.mocked(api.getChapters).mockResolvedValue({ items: [] })

    await store.refreshState()

    expect(api.getVolumePlan).not.toHaveBeenCalled()
    expect(store.volumePlan).toBeNull()
    expect(store.synopsisData).toEqual({ title: '道照诸天' })
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

  it('deletes the current novel and resets the store to the dashboard empty state', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState = {
      current_phase: 'drafting',
      current_chapter_id: 'ch-1',
      checkpoint_data: {
        synopsis_data: { title: '道照诸天' },
      },
    }
    store.archiveStats = { total_word_count: 1234 }
    store.chapters = [{ chapter_id: 'ch-1' }]
    store.volumePlan = { chapters: [{ chapter_id: 'ch-1' }] }
    store.synopsisContent = '内容'
    store.synopsisData = { title: '道照诸天' }
    store.entities = [{ entity_id: 'e-1' }]
    store.entityRelationships = [{ id: 'rel-1' }]
    store.timelines = [{ id: 't-1' }]
    store.spacelines = [{ id: 's-1' }]
    store.foreshadowings = [{ id: 'f-1' }]
    store.pendingDocs = [{ id: 'd-1' }]
    store.dashboardPanels.entities.state = 'ready'
    store.dashboardLastUpdated = '2026-04-22T00:00:00.000Z'

    vi.mocked(api.deleteNovel).mockResolvedValue()

    await store.deleteCurrentNovel()

    expect(api.deleteNovel).toHaveBeenCalledWith('novel-1')
    expect(store.novelId).toBe('')
    expect(store.novelState).toEqual({})
    expect(store.archiveStats).toEqual({})
    expect(store.chapters).toEqual([])
    expect(store.volumePlan).toBeNull()
    expect(store.synopsisContent).toBe('')
    expect(store.synopsisData).toBeNull()
    expect(store.entities).toEqual([])
    expect(store.entityRelationships).toEqual([])
    expect(store.timelines).toEqual([])
    expect(store.spacelines).toEqual([])
    expect(store.foreshadowings).toEqual([])
    expect(store.pendingDocs).toEqual([])
    expect(store.dashboardPanels.entities).toEqual({ state: 'idle', error: '' })
    expect(store.dashboardLastUpdated).toBe('')
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

  it('submitOutlineFeedback prevents duplicate submits while a request is pending', async () => {
    const store = useNovelStore()
    const deferred = createDeferred()
    store.novelId = 'novel-1'
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()

    vi.mocked(api.submitOutlineFeedback).mockReturnValueOnce(deferred.promise)

    const firstSubmit = store.submitOutlineFeedback({ content: '把总章数调整到 1300 章左右' })
    expect(store.outlineWorkbench.submitting).toBe(true)

    await store.submitOutlineFeedback({ content: '第二次重复提交' })
    expect(api.submitOutlineFeedback).toHaveBeenCalledTimes(1)

    deferred.resolve({})
    await firstSubmit

    expect(store.outlineWorkbench.submitting).toBe(false)
    expect(store.refreshOutlineWorkbench).toHaveBeenCalledWith({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
  })

  it('refreshOutlineWorkbench ignores stale responses that return after a newer request', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    const firstWorkbench = createDeferred()
    const secondWorkbench = createDeferred()
    const firstMessages = createDeferred()
    const secondMessages = createDeferred()

    vi.mocked(api.getOutlineWorkbench)
      .mockReturnValueOnce(firstWorkbench.promise)
      .mockReturnValueOnce(secondWorkbench.promise)
    vi.mocked(api.getOutlineWorkbenchMessages).mockImplementation((_novelId, selection) => {
      return selection?.outline_ref === 'vol_1' ? firstMessages.promise : secondMessages.promise
    })

    const firstRefresh = store.refreshOutlineWorkbench({
      outline_type: 'volume',
      outline_ref: 'vol_1',
    })
    const secondRefresh = store.refreshOutlineWorkbench({
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })

    secondWorkbench.resolve({
      outline_type: 'volume',
      outline_ref: 'vol_2',
      outline_items: [
        { outline_type: 'volume', outline_ref: 'vol_1', title: '第一卷', status: 'ready' },
        { outline_type: 'volume', outline_ref: 'vol_2', title: '第二卷', status: 'active' },
      ],
    })
    await Promise.resolve()
    secondMessages.resolve({
      recent_messages: [{ id: 'msg-2', content: 'message-2' }],
      conversation_summary: 'summary-2',
      last_result_snapshot: { title: '快照 2' },
    })
    await secondRefresh

    firstWorkbench.resolve({
      outline_type: 'volume',
      outline_ref: 'vol_1',
      outline_items: [
        { outline_type: 'volume', outline_ref: 'vol_1', title: '第一卷', status: 'active' },
      ],
    })
    await Promise.resolve()
    firstMessages.resolve({
      recent_messages: [{ id: 'msg-1', content: 'message-1' }],
      conversation_summary: 'summary-1',
      last_result_snapshot: { title: '快照 1' },
    })
    await firstRefresh

    expect(store.outlineWorkbench.selection).toEqual({
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(store.outlineWorkbench.currentItem).toEqual({
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    expect(store.outlineWorkbench.messages).toEqual([{ id: 'msg-2', content: 'message-2' }])
    expect(store.outlineWorkbench.lastResultSnapshot).toEqual({ title: '快照 2' })
  })

  it('submitOutlineFeedback does not pull selection back after the user switches items', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    }

    const submitDeferred = createDeferred()
    vi.mocked(api.submitOutlineFeedback).mockReturnValueOnce(submitDeferred.promise)
    vi.mocked(api.getOutlineWorkbench).mockResolvedValue({
      outline_type: 'volume',
      outline_ref: 'vol_3',
      outline_items: [
        { outline_type: 'volume', outline_ref: 'vol_2', title: '第二卷', status: 'ready' },
        { outline_type: 'volume', outline_ref: 'vol_3', title: '第三卷', status: 'active' },
      ],
    })
    vi.mocked(api.getOutlineWorkbenchMessages).mockResolvedValue({
      recent_messages: [{ id: 'msg-3', content: 'message-3' }],
      conversation_summary: 'summary-3',
      last_result_snapshot: { title: '快照 3' },
    })

    const submitPromise = store.submitOutlineFeedback({ content: '补充第二卷' })
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_3',
    }
    submitDeferred.resolve({ assistant_message: { id: 'assistant-3', content: 'done' } })
    await submitPromise

    expect(api.submitOutlineFeedback).toHaveBeenCalledWith('novel-1', {
      outline_type: 'volume',
      outline_ref: 'vol_2',
      content: '补充第二卷',
    })
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

  it('refreshOutlineWorkbench also loads brainstorm workspace data during brainstorming', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'

    vi.mocked(api.getOutlineWorkbench).mockResolvedValue({
      outline_items: [
        {
          outline_type: 'synopsis',
          outline_ref: 'synopsis',
          title: '总纲',
          status: 'ready',
        },
      ],
    })
    vi.mocked(api.getOutlineWorkbenchMessages).mockResolvedValue({
      recent_messages: [],
      conversation_summary: '',
      last_result_snapshot: { title: '工作区总纲' },
    })
    vi.mocked(api.getBrainstormWorkspace).mockResolvedValue({
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {
        'synopsis:synopsis': { title: '工作区总纲' },
      },
      setting_docs_draft: [
        {
          draft_id: 'draft-1',
          source_outline_ref: 'synopsis',
          source_kind: 'character',
          target_import_mode: 'explicit_type',
          target_doc_type: 'concept',
          title: '林风',
          content: '外门弟子。',
          order_index: 1,
        },
      ],
    })

    await store.refreshOutlineWorkbench({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })

    expect(api.getBrainstormWorkspace).toHaveBeenCalledWith('novel-1')
    expect(store.brainstormWorkspace.data?.workspace_id).toBe('ws-1')
    expect(store.brainstormWorkspace.data?.setting_docs_draft).toHaveLength(1)
  })

  it('submitBrainstormWorkspace refreshes formal state and clears workspace after confirmation', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {
        'synopsis:synopsis': { title: '工作区总纲' },
      },
      setting_docs_draft: [],
    }

    vi.mocked(api.submitBrainstormWorkspace).mockResolvedValue({
      synopsis_title: '工作区总纲',
      pending_setting_count: 1,
      volume_outline_count: 1,
    })

    store.refreshState = vi.fn().mockImplementation(async () => {
      store.novelState.current_phase = 'volume_planning'
    })
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()

    await store.submitBrainstormWorkspace()

    expect(api.submitBrainstormWorkspace).toHaveBeenCalledWith('novel-1')
    expect(store.refreshState).toHaveBeenCalledTimes(1)
    expect(store.refreshOutlineWorkbench).toHaveBeenCalledWith({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
    expect(store.brainstormWorkspace.data).toBeNull()
  })
})
