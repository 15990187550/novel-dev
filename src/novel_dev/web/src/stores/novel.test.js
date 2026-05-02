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
  updateNovel: vi.fn(),
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
  clearOutlineContext: vi.fn(),
  reviewOutline: vi.fn(),
  getBrainstormWorkspace: vi.fn(),
  startBrainstormWorkspace: vi.fn(),
  submitBrainstormWorkspace: vi.fn(),
  updateBrainstormSuggestionCard: vi.fn(),
  submitOutlineFeedback: vi.fn(),
  autoRunChapters: vi.fn(),
  rewriteChapter: vi.fn(),
  stopCurrentFlow: vi.fn(),
  getGenerationJob: vi.fn(),
  getChapterRewriteJobs: vi.fn(),
}))

describe('novel store dashboard loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(api.getSynopsis).mockResolvedValue(null)
    vi.mocked(api.getVolumePlan).mockResolvedValue(null)
    vi.mocked(api.getChapterRewriteJobs).mockResolvedValue({ items: [] })
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

  it('builds separate entity tree scopes for global and each knowledge domain', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    vi.mocked(api.getEntities).mockResolvedValue({
      items: [
        { entity_id: 'global-xf', name: '张小凡', type: 'character', knowledge_usage: 'global' },
        {
          entity_id: 'zhuxian-xf',
          name: '张小凡',
          type: 'character',
          knowledge_usage: 'domain',
          knowledge_domain_id: 'domain_zhuxian',
          knowledge_domain_name: '诛仙',
        },
        {
          entity_id: 'zhetian-xf',
          name: '张小凡',
          type: 'character',
          knowledge_usage: 'domain',
          knowledge_domain_id: 'domain_zhetian',
          knowledge_domain_name: '遮天',
        },
      ],
    })
    vi.mocked(api.getEntityRelationships).mockResolvedValue({ items: [] })

    await store.fetchEntities()

    expect(store.entityTree.map((node) => node.label)).toEqual(['全局实体', '规则域：遮天', '规则域：诛仙'])
    expect(store.entityTree.map((node) => node.entityCount)).toEqual([1, 1, 1])
    const zhuxianNode = store.entityTree.find((node) => node.label === '规则域：诛仙')
    const zhetianNode = store.entityTree.find((node) => node.label === '规则域：遮天')
    expect(zhuxianNode.children[0].children[0].children[0].entityId).toBe('zhuxian-xf')
    expect(zhetianNode.children[0].children[0].children[0].entityId).toBe('zhetian-xf')
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

  it('loads persisted rewrite jobs so failed chapters can continue after refresh', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    vi.mocked(api.getNovelState).mockResolvedValue({
      current_phase: 'context_preparation',
      current_chapter_id: 'ch-1',
      checkpoint_data: {
        current_volume_plan: {
          chapters: [{ chapter_id: 'ch-1', summary: '第一章计划摘要' }],
        },
      },
    })
    vi.mocked(api.getArchiveStats).mockResolvedValue({})
    vi.mocked(api.getChapters).mockResolvedValue({
      items: [{ chapter_id: 'ch-1', title: '第一章', status: 'edited', word_count: 4401 }],
    })
    vi.mocked(api.getChapterRewriteJobs).mockResolvedValue({
      items: [{
        chapter_id: 'ch-1',
        job: {
          job_id: 'job-failed-rewrite',
          status: 'failed',
          job_type: 'chapter_rewrite',
          request_payload: { chapter_id: 'ch-1' },
          result_payload: { resume_from_stage: 'librarian_archive' },
        },
      }],
    })

    await store.refreshState()

    expect(api.getChapterRewriteJobs).toHaveBeenCalledWith('novel-1')
    expect(store.chapterRewriteJobs['ch-1'].job_id).toBe('job-failed-rewrite')
    expect(store.chapterRewriteJobs['ch-1'].status).toBe('failed')
  })

  it('uses explicit novel title instead of synopsis title for display', () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState = {
      title: '项目名',
      checkpoint_data: {
        novel_title: '项目名',
        synopsis_data: { title: '总纲标题' },
      },
    }

    expect(store.novelTitle).toBe('项目名')
  })

  it('updates novel title without changing synopsis data', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState = {
      title: '旧项目名',
      checkpoint_data: {
        novel_title: '旧项目名',
        synopsis_data: { title: '总纲标题' },
      },
    }
    vi.mocked(api.updateNovel).mockResolvedValue({
      novel_id: 'novel-1',
      title: '新项目名',
      checkpoint_data: {
        novel_title: '新项目名',
        synopsis_data: { title: '总纲标题' },
      },
    })

    await store.updateNovelTitle('新项目名')

    expect(api.updateNovel).toHaveBeenCalledWith('novel-1', '新项目名')
    expect(store.novelTitle).toBe('新项目名')
    expect(store.novelState.checkpoint_data.synopsis_data.title).toBe('总纲标题')
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
      setting_suggestion_cards: [
        {
          card_id: 'card-1',
          card_type: 'character',
          merge_key: 'character:lin-feng',
          title: '林风',
          summary: '建议补充人物弧光。',
          status: 'active',
          source_outline_refs: ['synopsis'],
          payload: {},
          display_order: 1,
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
    expect(store.brainstormWorkspace.lastRoundSummary).toBeNull()
  })

  it('submitOutlineFeedback stores brainstormWorkspace.lastRoundSummary from service response during brainstorming', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    }
    store.outlineWorkbench.currentItem = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    }

    vi.mocked(api.submitOutlineFeedback).mockResolvedValue({
      session_id: 's-1',
      assistant_message: { id: 'assistant-1', role: 'assistant', message_type: 'result', content: '已处理' },
      setting_update_summary: { created: 1, updated: 2, superseded: 0, unresolved: 1 },
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
    })
    vi.mocked(api.getOutlineWorkbenchMessages).mockResolvedValue({
      recent_messages: [{ id: 'msg-2', content: 'message-2' }],
      conversation_summary: 'summary-2',
      last_result_snapshot: { title: '快照 2' },
      session_id: 's-1',
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })
    vi.mocked(api.getBrainstormWorkspace).mockResolvedValue({
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {
        'synopsis:synopsis': { title: '工作区总纲' },
      },
      setting_docs_draft: [],
      setting_suggestion_cards: [],
    })

    await store.submitOutlineFeedback({ content: '补充第二卷的反派动机' })

    expect(store.brainstormWorkspace.lastRoundSummary).toEqual({
      created: 1,
      updated: 2,
      superseded: 0,
      unresolved: 1,
    })
  })

  it('clears brainstormWorkspace.lastRoundSummary when a different workspace is loaded', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {},
      setting_docs_draft: [],
      setting_suggestion_cards: [],
    }
    store.brainstormWorkspace.lastRoundSummary = { created: 1, updated: 2, superseded: 0, unresolved: 1 }

    vi.mocked(api.getBrainstormWorkspace).mockResolvedValue({
      workspace_id: 'ws-2',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {},
      setting_docs_draft: [],
      setting_suggestion_cards: [],
    })

    await store.refreshBrainstormWorkspace()

    expect(store.brainstormWorkspace.data?.workspace_id).toBe('ws-2')
    expect(store.brainstormWorkspace.lastRoundSummary).toBeNull()
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

  it('updateBrainstormSuggestionCard updates workspace data from API response', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      setting_suggestion_cards: [{ card_id: 'card-1', status: 'active' }],
    }
    vi.mocked(api.updateBrainstormSuggestionCard).mockResolvedValue({
      workspace: {
        workspace_id: 'ws-1',
        novel_id: 'novel-1',
        status: 'active',
        setting_suggestion_cards: [{ card_id: 'card-1', status: 'resolved' }],
      },
      pending_extraction: null,
    })

    const result = await store.updateBrainstormSuggestionCard('card-1', 'resolve')

    expect(api.updateBrainstormSuggestionCard).toHaveBeenCalledWith(
      'novel-1',
      'card-1',
      { action: 'resolve' }
    )
    expect(result.pending_extraction).toBeNull()
    expect(store.brainstormWorkspace.data.setting_suggestion_cards[0].status).toBe('resolved')
    expect(store.brainstormWorkspace.updatingCardId).toBe('')
  })

  it('updateBrainstormSuggestionCard keeps workspace and records error on failure', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      setting_suggestion_cards: [{ card_id: 'card-1', status: 'active' }],
    }
    vi.mocked(api.updateBrainstormSuggestionCard).mockRejectedValue(new Error('状态不允许'))

    await expect(store.updateBrainstormSuggestionCard('card-1', 'resolve')).rejects.toThrow('状态不允许')

    expect(store.brainstormWorkspace.data.setting_suggestion_cards[0].status).toBe('active')
    expect(store.brainstormWorkspace.error).toBe('状态不允许')
    expect(store.brainstormWorkspace.updatingCardId).toBe('')
  })

  it('stopCurrentFlow requests backend stop and refreshes state', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.flowActivity = { active: true, label: '停止生成大纲', updatedAt: '2026-04-25T00:00:00Z' }
    store.refreshState = vi.fn().mockResolvedValue()
    vi.mocked(api.stopCurrentFlow).mockResolvedValue({ stop_requested: true })

    await store.stopCurrentFlow()

    expect(api.stopCurrentFlow).toHaveBeenCalledWith('novel-1')
    expect(store.refreshState).toHaveBeenCalledTimes(1)
    expect(store.flowActivity.active).toBe(false)
    expect(store.stoppingFlow).toBe(false)
  })

  it('executeAction starts an auto-run generation job without waiting for chapter completion', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.loadNovel = vi.fn().mockResolvedValue()
    store.loadDashboardSupplemental = vi.fn().mockResolvedValue()
    vi.mocked(api.autoRunChapters).mockResolvedValue({
      job_id: 'job-1',
      status: 'queued',
      job_type: 'chapter_auto_run',
    })

    await store.executeAction('auto_chapter')

    expect(api.autoRunChapters).toHaveBeenCalledWith('novel-1', {
      max_chapters: 1,
      stop_at_volume_end: true,
    })
    expect(store.autoRunJob).toEqual({
      job_id: 'job-1',
      status: 'queued',
      job_type: 'chapter_auto_run',
    })
    expect(store.loadNovel).toHaveBeenCalledWith('novel-1')
    expect(store.loadDashboardSupplemental).not.toHaveBeenCalled()
    expect(store.loadingActions.auto_chapter).toBe(false)
  })

  it('executeAction starts configurable continuous chapter auto-run jobs', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.loadNovel = vi.fn().mockResolvedValue()
    vi.mocked(api.autoRunChapters).mockResolvedValue({
      job_id: 'job-2',
      status: 'queued',
      job_type: 'chapter_auto_run',
    })

    await store.executeAction('auto_chapter', {
      max_chapters: 12,
      stop_at_volume_end: false,
    })

    expect(api.autoRunChapters).toHaveBeenCalledWith('novel-1', {
      max_chapters: 12,
      stop_at_volume_end: false,
    })
    expect(store.autoRunJob.job_id).toBe('job-2')
    expect(store.loadingActions.auto_chapter).toBe(false)
  })

  it('refreshAutoRunJob stores completed failure payload for display', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.autoRunJob = { job_id: 'job-1', status: 'running' }
    vi.mocked(api.getGenerationJob).mockResolvedValue({
      job_id: 'job-1',
      status: 'failed',
      result_payload: {
        stopped_reason: 'failed',
        failed_phase: 'drafting',
        failed_chapter_id: 'ch-1',
        error: 'draft exploded',
      },
    })

    await store.refreshAutoRunJob()

    expect(api.getGenerationJob).toHaveBeenCalledWith('novel-1', 'job-1')
    expect(store.autoRunJob.status).toBe('failed')
    expect(store.autoRunLastResult.error).toBe('draft exploded')
  })

  it('starts and refreshes chapter rewrite jobs independently from auto-run state', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.refreshState = vi.fn().mockResolvedValue()
    store.fetchEntities = vi.fn().mockResolvedValue()
    store.fetchTimelines = vi.fn().mockResolvedValue()
    store.fetchSpacelines = vi.fn().mockResolvedValue()
    store.fetchForeshadowings = vi.fn().mockResolvedValue()
    vi.mocked(api.rewriteChapter).mockResolvedValue({
      job_id: 'job-rewrite-1',
      status: 'queued',
      job_type: 'chapter_rewrite',
      request_payload: { chapter_id: 'ch-1' },
    })
    vi.mocked(api.getGenerationJob).mockResolvedValue({
      job_id: 'job-rewrite-1',
      status: 'succeeded',
      result_payload: { chapter_id: 'ch-1', status: 'succeeded' },
    })

    const job = await store.rewriteChapter('ch-1')
    await store.refreshChapterRewriteJob('ch-1')

    expect(api.rewriteChapter).toHaveBeenCalledWith('novel-1', 'ch-1')
    expect(job.job_type).toBe('chapter_rewrite')
    expect(store.autoRunJob).toBeNull()
    expect(store.chapterRewriteJobs['ch-1'].status).toBe('succeeded')
    expect(store.chapterRewriteLastResults['ch-1']).toEqual({ chapter_id: 'ch-1', status: 'succeeded' })
    expect(store.fetchEntities).toHaveBeenCalledTimes(1)
    expect(store.fetchTimelines).toHaveBeenCalledTimes(1)
    expect(store.fetchSpacelines).toHaveBeenCalledTimes(1)
    expect(store.fetchForeshadowings).toHaveBeenCalledTimes(1)
    expect(store.loadingActions['rewrite:ch-1']).toBe(false)
  })

  it('passes resume options when continuing a failed chapter rewrite', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.refreshState = vi.fn().mockResolvedValue()
    vi.mocked(api.rewriteChapter).mockResolvedValue({
      job_id: 'job-resume-1',
      status: 'queued',
      job_type: 'chapter_rewrite',
      request_payload: {
        chapter_id: 'ch-1',
        resume: true,
        failed_job_id: 'job-failed-1',
      },
    })

    const job = await store.rewriteChapter('ch-1', {
      resume: true,
      failed_job_id: 'job-failed-1',
    })

    expect(api.rewriteChapter).toHaveBeenCalledWith('novel-1', 'ch-1', {
      resume: true,
      failed_job_id: 'job-failed-1',
    })
    expect(job.job_id).toBe('job-resume-1')
    expect(store.chapterRewriteJobs['ch-1'].request_payload.resume).toBe(true)
  })

  it('executeAction stores structured auto-run failure details', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.loadNovel = vi.fn().mockResolvedValue()
    store.loadDashboardSupplemental = vi.fn().mockResolvedValue()
    const error = new Error('Request failed')
    error.response = {
      status: 422,
      data: {
        detail: {
          novel_id: 'novel-1',
          current_phase: 'context_preparation',
          current_chapter_id: 'ch-1',
          completed_chapters: [],
          stopped_reason: 'failed',
          failed_phase: 'context_preparation',
          failed_chapter_id: 'ch-1',
          error: 'context exploded',
        },
      },
    }
    vi.mocked(api.autoRunChapters).mockRejectedValue(error)

    await expect(store.executeAction('auto_chapter')).rejects.toThrow('Request failed')

    expect(store.autoRunLastResult).toEqual(error.response.data.detail)
    expect(store.loadNovel).toHaveBeenCalledWith('novel-1')
    expect(store.loadDashboardSupplemental).not.toHaveBeenCalled()
    expect(store.loadingActions.auto_chapter).toBe(false)
  })

  it('derives stop flow visibility and label from local running actions', () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    expect(store.shouldShowStopFlow).toBe(false)

    store.loadingActions.volume_plan = true

    expect(store.shouldShowStopFlow).toBe(true)
    expect(store.stopFlowLabel).toBe('停止生成大纲')
  })

  it('restores running flow state from replayed logs after refresh', () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    store.syncFlowActivityFromLogs([
      {
        timestamp: '2026-04-25T00:00:00Z',
        agent: 'VolumePlannerAgent',
        status: 'started',
        node: 'volume_plan',
        task: 'generate_volume_plan',
        message: '开始生成卷纲',
      },
    ])

    expect(store.shouldShowStopFlow).toBe(true)
    expect(store.stopFlowLabel).toBe('停止生成大纲')

    store.syncFlowActivityFromLogs([
      {
        timestamp: '2026-04-25T00:00:00Z',
        agent: 'VolumePlannerAgent',
        status: 'started',
        node: 'volume_plan',
        task: 'generate_volume_plan',
        message: '开始生成卷纲',
      },
      {
        timestamp: '2026-04-25T00:01:00Z',
        agent: 'VolumePlannerAgent',
        status: 'succeeded',
        node: 'volume_plan',
        task: 'generate_volume_plan',
        message: '卷纲生成完成',
      },
    ])

    expect(store.shouldShowStopFlow).toBe(false)
  })

  it('clears current outline context and refreshes workbench', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.outlineWorkbench.messages = [{ id: 'm1', content: '旧意见' }]
    store.outlineWorkbench.conversationSummary = '旧摘要'
    store.outlineWorkbench.lastResultSnapshot = { title: '旧快照' }
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    vi.mocked(api.clearOutlineContext).mockResolvedValue({ deleted_messages: 1 })

    await store.clearOutlineContext()

    expect(api.clearOutlineContext).toHaveBeenCalledWith('novel-1', {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
    expect(store.outlineWorkbench.messages).toEqual([])
    expect(store.outlineWorkbench.conversationSummary).toBe('')
    expect(store.outlineWorkbench.lastResultSnapshot).toBeNull()
    expect(store.refreshOutlineWorkbench).toHaveBeenCalledWith({
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })
  })
})
