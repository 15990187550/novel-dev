import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import VolumePlan from './VolumePlan.vue'

const outlineDetailPanelStub = {
  props: ['createAction'],
  template: '<div class="outline-detail-panel-stub">{{ createAction?.loading ? "创建中..." : (createAction?.disabledReason || createAction?.label || "") }}</div>',
}

const outlineConversationStub = {
  props: ['disabled'],
  template: '<div class="outline-conversation-stub">{{ disabled ? "对话已禁用" : "对话可用" }}</div>',
}

describe('VolumePlan', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads outline workbench when mounted with an active novel id', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()

    mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: true,
          OutlineConversation: true,
        },
      },
    })

    await flushPromises()

    expect(store.refreshOutlineWorkbench).toHaveBeenCalledTimes(1)
  })

  it('reloads outline workbench when novel id changes', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()

    mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: true,
          OutlineConversation: true,
        },
      },
    })

    expect(store.refreshOutlineWorkbench).not.toHaveBeenCalled()

    store.novelId = 'novel-2'
    await flushPromises()

    expect(store.refreshOutlineWorkbench).toHaveBeenCalledTimes(1)
  })

  it('disables creating a later volume when the previous volume outline is missing', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'volume_planning'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.outlineWorkbench.items = [
      {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
        itemId: 'synopsis:synopsis',
        key: 'synopsis:synopsis',
        title: '总纲',
        status: 'ready',
        statusLabel: '已完成',
        summary: '总纲摘要',
      },
      {
        outline_type: 'volume',
        outline_ref: 'vol_2',
        itemId: 'volume:vol_2',
        key: 'volume:vol_2',
        title: '第 2 卷',
        status: 'missing',
        statusLabel: '待创建',
        summary: '第 2 卷尚未生成',
      },
      {
        outline_type: 'volume',
        outline_ref: 'vol_3',
        itemId: 'volume:vol_3',
        key: 'volume:vol_3',
        title: '第 3 卷',
        status: 'missing',
        statusLabel: '待创建',
        summary: '第 3 卷尚未生成',
      },
    ]
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_3',
    }

    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: outlineDetailPanelStub,
          OutlineConversation: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('请先创建第 2 卷，再创建当前卷。')
  })

  it('keeps the create button loading state after remounting the page', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'volume_planning'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.outlineWorkbench.creatingKey = 'volume:vol_1'
    store.outlineWorkbench.items = [
      {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
        itemId: 'synopsis:synopsis',
        key: 'synopsis:synopsis',
        title: '总纲',
        status: 'ready',
        statusLabel: '已完成',
        summary: '总纲摘要',
      },
      {
        outline_type: 'volume',
        outline_ref: 'vol_1',
        itemId: 'volume:vol_1',
        key: 'volume:vol_1',
        title: '第 1 卷',
        status: 'missing',
        statusLabel: '待创建',
        summary: '第 1 卷尚未生成',
      },
    ]
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_1',
    }

    const mountOptions = {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: outlineDetailPanelStub,
          OutlineConversation: outlineConversationStub,
        },
      },
    }

    const firstWrapper = mount(VolumePlan, mountOptions)
    await flushPromises()
    expect(firstWrapper.text()).toContain('创建中...')
    expect(firstWrapper.text()).toContain('对话已禁用')
    expect(firstWrapper.text()).toContain('创建中')

    firstWrapper.unmount()

    const secondWrapper = mount(VolumePlan, mountOptions)
    await flushPromises()
    expect(secondWrapper.text()).toContain('创建中...')
    expect(secondWrapper.text()).toContain('对话已禁用')
    expect(secondWrapper.text()).toContain('创建中')
  })
})
