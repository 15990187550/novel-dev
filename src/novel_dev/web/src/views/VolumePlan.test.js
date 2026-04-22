import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import VolumePlan from './VolumePlan.vue'

const outlineDetailPanelStub = {
  props: ['createAction', 'detail'],
  template: '<div class="outline-detail-panel-stub">{{ createAction?.loading ? "创建中..." : (detail?.emptyDescription || createAction?.disabledReason || createAction?.label || "") }}</div>',
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
    expect(firstWrapper.text()).toContain('对话已禁用')
    expect(firstWrapper.text()).toContain('创建中')

    firstWrapper.unmount()

    const secondWrapper = mount(VolumePlan, mountOptions)
    await flushPromises()
    expect(secondWrapper.text()).toContain('对话已禁用')
    expect(secondWrapper.text()).toContain('创建中')
  })

  it('renders brainstorm workspace confirmation and setting drafts', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.submitBrainstormWorkspace = vi.fn().mockResolvedValue()
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
    ]
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {
        'synopsis:synopsis': { title: '总纲' },
      },
      setting_docs_draft: [
        {
          draft_id: 'draft-1',
          source_outline_ref: 'synopsis',
          source_kind: 'character',
          target_import_mode: 'explicit_type',
          target_doc_type: 'concept',
          title: '林风',
          content: '青云宗外门弟子',
          order_index: 1,
        },
      ],
    }

    const wrapper = mount(VolumePlan, {
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

    expect(wrapper.text()).toContain('最终确认')
    expect(wrapper.text()).toContain('设定草稿')
    expect(wrapper.text()).toContain('林风')
    expect(wrapper.text()).not.toContain('请先补齐卷纲')

    await wrapper.get('[data-testid="brainstorm-submit"]').trigger('click')
    expect(store.submitBrainstormWorkspace).toHaveBeenCalledTimes(1)
  })

  it('allows final brainstorm confirmation with only a synopsis draft', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.submitBrainstormWorkspace = vi.fn().mockResolvedValue()
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {
        'synopsis:synopsis': {
          title: '总纲',
          estimated_volumes: 7,
        },
      },
      setting_docs_draft: [],
    }

    const wrapper = mount(VolumePlan, {
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

    const submitButton = wrapper.get('[data-testid="brainstorm-submit"]')
    expect(wrapper.text()).not.toContain('请先补齐卷纲')
    expect(submitButton.attributes('disabled')).toBeUndefined()

    await submitButton.trigger('click')
    expect(store.submitBrainstormWorkspace).toHaveBeenCalledTimes(1)
  })

  it('uses conversation generation instead of a separate create button for missing brainstorm synopsis', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.submitOutlineFeedback = vi.fn().mockResolvedValue()
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {},
      setting_docs_draft: [],
    }

    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
        },
      },
    })

    await flushPromises()

    const buttonLabels = wrapper.findAll('button').map((button) => button.text().trim())
    expect(buttonLabels).not.toContain('一键创建总纲')
    expect(buttonLabels).toContain('生成大纲')

    const submitButton = wrapper.findAll('button').find((button) => button.text().includes('生成大纲'))
    expect(submitButton?.attributes('disabled')).toBeUndefined()

    await submitButton?.trigger('click')

    expect(store.submitOutlineFeedback).toHaveBeenCalledWith({
      content: '请基于当前设定生成完整总纲草稿，补齐一句话梗概、核心冲突、卷数规模、人物弧光和关键里程碑。',
    })
  })

  it('switches the missing-outline action label to confirmation after assistant follow-up questions', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {},
      setting_docs_draft: [],
    }
    store.outlineWorkbench.messages = [
      {
        id: 'assistant-question-1',
        role: 'assistant',
        message_type: 'question',
        content: '先确认几个关键信息。',
        meta: {
          interaction_stage: 'generation_confirmation',
        },
      },
    ]

    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('发送确认信息')
    expect(wrapper.text()).not.toContain('生成大纲')
  })

  it('uses conversation generation instead of a separate create button for missing volume outline', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'volume_planning'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.submitOutlineFeedback = vi.fn().mockResolvedValue()
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
    ]
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    }

    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
        },
      },
    })

    await flushPromises()

    const buttonLabels = wrapper.findAll('button').map((button) => button.text().trim())
    expect(buttonLabels).not.toContain('一键创建第 2 卷')
    expect(buttonLabels).toContain('生成大纲')

    const submitButton = wrapper.findAll('button').find((button) => button.text().includes('生成大纲'))
    expect(submitButton?.attributes('disabled')).toBeUndefined()

    await submitButton?.trigger('click')

    expect(store.submitOutlineFeedback).toHaveBeenCalledWith({
      content: '请基于当前总纲与已完成卷纲，先生成第 2 卷的完整卷纲草稿，补齐卷目标、核心冲突、章节结构和卷末推进。',
    })
  })
})
