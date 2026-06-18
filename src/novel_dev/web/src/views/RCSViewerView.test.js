import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getChapterSynopses } from '@/api.js'
import RCSViewerView from './RCSViewerView.vue'

vi.mock('@/api.js', () => ({
  getChapterSynopses: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

const sampleSynopses = [
  {
    id: 'rcs-1',
    chapter_range: [1, 5],
    narrative_prose: '主角初入门派，遇见师父。',
    structured_json: { themes: ['成长'], conflicts: ['正邪冲突'] },
    trigger_event: { chapter: 5, summary: '突破境界' },
    created_at: '2026-06-17T10:00:00',
  },
  {
    id: 'rcs-2',
    chapter_range: [6, 10],
    narrative_prose: '主角离开门派，踏上复仇之路。',
    structured_json: { themes: ['复仇'], conflicts: ['师门恩怨'] },
    trigger_event: { chapter: 10, summary: '身份暴露' },
    created_at: '2026-06-17T12:00:00',
  },
]

function mountView(props = { novelId: 'novel-1' }) {
  return mount(RCSViewerView, {
    props,
    global: {
      stubs: {
        ElButton: {
          name: 'ElButton',
          props: ['loading'],
          emits: ['click'],
          template: '<button v-bind="$attrs" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
        },
        ElSkeleton: { name: 'ElSkeleton', template: '<div class="el-skeleton-stub" />' },
      },
    },
  })
}

describe('RCSViewerView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches synopses on mount and renders cards', async () => {
    getChapterSynopses.mockResolvedValueOnce({
      novel_id: 'novel-1',
      synopses: sampleSynopses,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(getChapterSynopses).toHaveBeenCalledWith('novel-1')
    const cards = wrapper.findAll('[data-testid="synopsis-card"]')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('第 1 - 5 章')
    expect(cards[0].text()).toContain('主角初入门派，遇见师父。')
    expect(cards[1].text()).toContain('第 6 - 10 章')
    expect(cards[1].text()).toContain('主角离开门派，踏上复仇之路。')
  })

  it('renders a single chapter range without a dash', async () => {
    getChapterSynopses.mockResolvedValueOnce({
      novel_id: 'novel-1',
      synopses: [
        {
          id: 'rcs-solo',
          chapter_range: [3, 3],
          narrative_prose: '单章范围',
          structured_json: {},
          trigger_event: {},
          created_at: '2026-06-17T10:00:00',
        },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="synopsis-range"]').text()).toBe('第 3 章')
  })

  it('pretty-prints structured_json inside the card', async () => {
    getChapterSynopses.mockResolvedValueOnce({
      novel_id: 'novel-1',
      synopses: [
        {
          id: 'rcs-1',
          chapter_range: [1, 5],
          narrative_prose: '正文',
          structured_json: { themes: ['成长'] },
          trigger_event: {},
          created_at: '2026-06-17T10:00:00',
        },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const structured = wrapper.find('[data-testid="synopsis-structured"]')
    expect(structured.exists()).toBe(true)
    expect(structured.text()).toContain('"themes"')
    expect(structured.text()).toContain('"成长"')
  })

  it('hides the trigger event section when trigger_event is empty', async () => {
    getChapterSynopses.mockResolvedValueOnce({
      novel_id: 'novel-1',
      synopses: [
        {
          id: 'rcs-1',
          chapter_range: [1, 5],
          narrative_prose: '正文',
          structured_json: {},
          trigger_event: {},
          created_at: '2026-06-17T10:00:00',
        },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="synopsis-trigger"]').exists()).toBe(false)
  })

  it('shows the empty state when API returns no synopses', async () => {
    getChapterSynopses.mockResolvedValueOnce({
      novel_id: 'novel-1',
      synopses: [],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="synopsis-empty"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="synopsis-card"]')).toHaveLength(0)
  })

  it('shows the count of synopses', async () => {
    getChapterSynopses.mockResolvedValueOnce({
      novel_id: 'novel-1',
      synopses: sampleSynopses,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="rcs-viewer-count"]').text()).toBe('2')
  })

  it('refetches when the refresh button is clicked', async () => {
    getChapterSynopses.mockResolvedValue({
      novel_id: 'novel-1',
      synopses: [],
    })

    const wrapper = mountView()
    await flushPromises()
    expect(getChapterSynopses).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="rcs-viewer-refresh"]').trigger('click')
    await flushPromises()

    expect(getChapterSynopses).toHaveBeenCalledTimes(2)
  })

  it('shows an ElMessage error and clears state when the API fails', async () => {
    const { ElMessage } = await import('element-plus')
    getChapterSynopses.mockRejectedValueOnce(new Error('boom'))

    const wrapper = mountView()
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith('boom')
    expect(wrapper.find('[data-testid="synopsis-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="rcs-viewer-count"]').text()).toBe('0')
  })

  it('refetches when the novelId prop changes', async () => {
    getChapterSynopses.mockResolvedValue({
      novel_id: 'novel-1',
      synopses: [],
    })

    const wrapper = mountView({ novelId: 'novel-1' })
    await flushPromises()
    expect(getChapterSynopses).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ novelId: 'novel-2' })
    await flushPromises()

    expect(getChapterSynopses).toHaveBeenCalledTimes(2)
    expect(getChapterSynopses).toHaveBeenLastCalledWith('novel-2')
  })
})