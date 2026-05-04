import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import SettingWorkbench from './SettingWorkbench.vue'
import { useNovelStore } from '@/stores/novel.js'
import * as api from '@/api.js'

vi.mock('@/api.js', () => ({
  getPendingDocs: vi.fn().mockResolvedValue({
    items: [
      { id: 'pending-setting', source_filename: '设定.md', extraction_type: 'setting', status: 'pending' },
      { id: 'pending-outline', source_filename: '大纲.md', extraction_type: 'outline', status: 'pending' },
    ],
  }),
  getDocuments: vi.fn().mockResolvedValue({ items: [] }),
  getSettingSessions: vi.fn().mockResolvedValue({ items: [] }),
  getSettingReviewBatches: vi.fn().mockResolvedValue({ items: [] }),
  createSettingSession: vi.fn().mockResolvedValue({
    id: 'sgs-1',
    novel_id: 'novel-1',
    title: '废脉少年',
    status: 'clarifying',
    target_categories: [],
    clarification_round: 0,
  }),
  getSettingSession: vi.fn().mockResolvedValue({
    session: {
      id: 'sgs-1',
      novel_id: 'novel-1',
      title: '废脉少年',
      status: 'clarifying',
      target_categories: [],
      clarification_round: 0,
    },
    messages: [{ id: 'msg-1', role: 'user', content: '废脉少年', session_id: 'sgs-1' }],
  }),
  startSettingConsolidation: vi.fn().mockResolvedValue({
    job_id: 'job-setting-1',
    status: 'queued',
  }),
  getSettingReviewBatch: vi.fn().mockResolvedValue({ batch: null, changes: [] }),
  approveSettingReviewBatch: vi.fn(),
}))

describe('SettingWorkbench', () => {
  it('shows AI setting generation and creates a new session', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'

    const wrapper = mount(SettingWorkbench, {
      global: {
        plugins: [pinia],
        stubs: {
          ElAlert: true,
          ElDialog: {
            template: '<div><slot /><slot name="footer" /></div>',
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('AI 生成设定')
    expect(wrapper.text()).toContain('新建会话')

    await wrapper.get('[data-testid="setting-new-session"]').trigger('click')
    expect(wrapper.find('[data-testid="setting-session-title"]').exists()).toBe(false)
    await wrapper.get('[data-testid="setting-session-idea"]').setValue('废脉少年')
    await wrapper.get('[data-testid="setting-create-session"]').trigger('click')
    await flushPromises()

    expect(api.createSettingSession).toHaveBeenCalledWith('novel-1', {
      title: '废脉少年',
      initial_idea: '废脉少年',
      target_categories: [],
    })
    expect(wrapper.text()).toContain('废脉少年')
  })

  it('hides the standalone page header when embedded in documents', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'

    const wrapper = mount(SettingWorkbench, {
      props: { embedded: true },
      global: {
        plugins: [pinia],
        stubs: {
          ElAlert: true,
          ElDialog: {
            template: '<div><slot /><slot name="footer" /></div>',
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('.page-header').exists()).toBe(false)
    expect(wrapper.text()).toContain('AI 生成设定')
    expect(wrapper.text()).not.toContain('设定工作台')
  })

  it('opens consolidation dialog, selects pending records, and submits selected ids', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'

    const wrapper = mount(SettingWorkbench, {
      global: {
        plugins: [pinia],
        stubs: {
          ElAlert: true,
          ElDialog: {
            template: '<div><slot /><slot name="footer" /></div>',
          },
          teleport: true,
        },
      },
    })
    await flushPromises()

    expect(api.getPendingDocs).toHaveBeenCalledWith('novel-1')

    await wrapper.get('[data-testid="setting-consolidation-open"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="setting-consolidation-pending-pending-setting"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="setting-consolidation-pending-pending-outline"]').exists()).toBe(false)

    await wrapper.get('[data-testid="setting-consolidation-pending-pending-setting"]').setValue(true)
    await wrapper.get('[data-testid="setting-consolidation-submit"]').trigger('click')
    await flushPromises()

    expect(api.startSettingConsolidation).toHaveBeenCalledWith('novel-1', ['pending-setting'])
  })

  it('does not preselect pending records when opening consolidation dialog', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'

    const wrapper = mount(SettingWorkbench, {
      global: {
        plugins: [pinia],
        stubs: {
          ElAlert: true,
          ElDialog: {
            template: '<div><slot /><slot name="footer" /></div>',
          },
        },
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="setting-consolidation-open"]').trigger('click')
    await flushPromises()

    const checkbox = wrapper.get('[data-testid="setting-consolidation-pending-pending-setting"]')
    expect(checkbox.element.checked).toBe(false)

    await wrapper.get('[data-testid="setting-consolidation-submit"]').trigger('click')
    await flushPromises()

    expect(api.startSettingConsolidation).toHaveBeenCalledWith('novel-1', [])
  })
})
