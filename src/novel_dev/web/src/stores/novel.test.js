import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api.js'
import { useNovelStore } from './novel.js'

vi.mock('@/api.js', () => ({
  getNovelState: vi.fn(),
  getArchiveStats: vi.fn(),
  getChapters: vi.fn(),
  getEntities: vi.fn(),
  getEntityRelationships: vi.fn(),
  getTimelines: vi.fn(),
  getForeshadowings: vi.fn(),
  getPendingDocs: vi.fn(),
}))

describe('novel store dashboard loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
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

  it('refreshes state and preserves the merged currentChapter result', async () => {
    const store = useNovelStore()

    vi.mocked(api.getNovelState)
      .mockResolvedValueOnce({
        current_phase: 'drafting',
        current_chapter_id: 'ch-1',
        checkpoint_data: {
          current_volume_plan: {
            chapters: [
              { chapter_id: 'ch-1', title: '第一章（计划）' },
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
              { chapter_id: 'ch-2', title: '第二章（刷新后计划）', summary: '刷新后的计划摘要' },
            ],
          },
        },
      })

    vi.mocked(api.getArchiveStats).mockResolvedValue({ total: 2 })
    vi.mocked(api.getChapters).mockResolvedValue({
      items: [
        { chapter_id: 'ch-1', title: '第一章', body: '章节一正文' },
        { chapter_id: 'ch-2', title: '第二章', body: '章节二正文' },
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
      title: '第一章（计划）',
      body: '章节一正文',
    })

    await store.refreshDashboard()

    expect(store.novelState.current_phase).toBe('editing')
    expect(store.currentChapter).toEqual({
      chapter_id: 'ch-2',
      title: '第二章（刷新后计划）',
      body: '章节二正文',
      summary: '刷新后的计划摘要',
    })
    expect(store.dashboardLastUpdated).toBeTruthy()
  })
})
