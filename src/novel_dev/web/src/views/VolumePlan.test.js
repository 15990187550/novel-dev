import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import VolumePlan from './VolumePlan.vue'

const outlineDetailPanelStub = {
  name: 'OutlineDetailPanel',
  props: ['createAction', 'detail'],
  template: `
    <div class="outline-detail-panel-stub">
      {{ createAction?.loading ? "创建中..." : (detail?.emptyDescription || createAction?.disabledReason || createAction?.label || "") }}
      <section v-for="section in detail?.sections || []" :key="section.title">
        <h3>{{ section.title }}</h3>
        <p v-for="item in section.items" :key="item">{{ item }}</p>
        <button v-if="section.detailItems?.length">查看详情</button>
      </section>
    </div>
  `,
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

  it('keeps outline workbench busy while volume planning action is running', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'volume_planning'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.loadingActions.volume_plan = true
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

    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: true,
          OutlineConversation: outlineConversationStub,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('生成中')
    expect(wrapper.text()).toContain('对话已禁用')
  })

  it('shows a precise stop flow button only while outline generation is running', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.stopCurrentFlow = vi.fn().mockResolvedValue()

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

    expect(wrapper.findAll('button').some((button) => button.text().includes('停止生成大纲'))).toBe(false)

    store.outlineWorkbench.submitting = true
    await flushPromises()

    const stopButton = wrapper.findAll('button').find((button) => button.text().includes('停止生成大纲'))
    expect(stopButton).toBeTruthy()
    await stopButton.trigger('click')
    expect(store.stopCurrentFlow).toHaveBeenCalledTimes(1)
  })

  it('renders brainstorm workspace confirmation and setting drafts', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.submitBrainstormWorkspace = vi.fn().mockResolvedValue()
    store.brainstormWorkspace.lastRoundSummary = { created: 1, updated: 0, superseded: 0, unresolved: 1 }
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
      setting_suggestion_cards: [
        {
          card_id: 'card-1',
          card_type: 'character',
          merge_key: 'character:lin-feng',
          title: '林风',
          summary: '建议补充：他的主要动机与关键成长节点。',
          status: 'unresolved',
          source_outline_refs: ['synopsis'],
          display_order: 1,
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
    expect(wrapper.text()).toContain('设定建议卡')
    expect(wrapper.text()).toContain('本轮设定更新')
    expect(wrapper.text()).toContain('设定草稿')
    expect(wrapper.text()).toContain('林风')
    expect(wrapper.text()).not.toContain('请先补齐卷纲')

    await wrapper.get('[data-testid="brainstorm-submit"]').trigger('click')
    expect(store.submitBrainstormWorkspace).toHaveBeenCalledTimes(1)
  })

  it('uses dark-mode friendly text classes for brainstorm draft section headings', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
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
      setting_docs_draft: [],
      setting_suggestion_cards: [],
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

    const heading = wrapper.findAll('h2').find((node) => node.text() === '设定草稿')
    expect(heading.classes()).toContain('dark:text-gray-100')
  })

  it('renders brainstorm draft panels before the main workbench', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
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
      setting_suggestion_cards: [
        {
          card_id: 'card-1',
          card_type: 'character',
          merge_key: 'character:lin-feng',
          title: '林风',
          summary: '建议补充：他的主要动机与关键成长节点。',
          status: 'unresolved',
          source_outline_refs: ['synopsis'],
          display_order: 1,
        },
      ],
    }

    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: { template: '<div>OUTLINE SIDEBAR</div>' },
          OutlineDetailPanel: { template: '<div>OUTLINE DETAIL</div>' },
          OutlineConversation: { template: '<div>OUTLINE CONVERSATION</div>' },
        },
      },
    })

    await flushPromises()

    const text = wrapper.text()
    expect(text.indexOf('设定草稿')).toBeGreaterThan(-1)
    expect(text.indexOf('设定建议卡')).toBeGreaterThan(-1)
    expect(text.indexOf('设定草稿')).toBeLessThan(text.indexOf('OUTLINE SIDEBAR'))
    expect(text.indexOf('设定建议卡')).toBeLessThan(text.indexOf('OUTLINE SIDEBAR'))
  })

  it('renders brainstorm submit warnings from workspace data', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
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
      setting_docs_draft: [],
      setting_suggestion_cards: [],
      submit_warnings: ['关系卡存在未解析项，最终确认时将跳过部分关系导入。'],
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

    expect(wrapper.text()).toContain('关系卡存在未解析项')
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

  it('renders synopsis volume outline contracts in detail panel', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'volume_planning'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.outlineWorkbench.items = [
      {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
        key: 'synopsis:synopsis',
        title: '总纲',
        status: 'ready',
      },
    ]
    store.synopsisData = {
      title: '道照诸天',
      logline: '陆照争夺超脱路径。',
      core_conflict: '陆照 vs 轮回空间',
      estimated_volumes: 2,
      estimated_total_chapters: 60,
      volume_outlines: [
        {
          volume_number: 1,
          title: '轮回初醒',
          main_goal: '夺回第一枚道印',
          main_conflict: '陆照 vs 轮回使者',
          climax: '夺印成功',
          hook_to_next: '第二枚道印现世',
        },
      ],
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

    expect(wrapper.text()).toContain('卷级总览')
    expect(wrapper.text()).toContain('第 1 卷《轮回初醒》')
    expect(wrapper.text()).toContain('夺回第一枚道印')
    expect(wrapper.text()).toContain('查看详情')

    const detail = wrapper.findComponent(outlineDetailPanelStub).props('detail')
    const volumeOverview = detail.sections.find((section) => section.title === '卷级总览')
    expect(volumeOverview.items[0]).not.toContain('第二枚道印现世')
    expect(volumeOverview.detailItems[0]).toContain('第二枚道印现世')
  })

  it('renders milestone summaries with detail entries in synopsis detail panel', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'volume_planning'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.outlineWorkbench.items = [
      {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
        key: 'synopsis:synopsis',
        title: '总纲',
        status: 'ready',
      },
    ]
    store.synopsisData = {
      title: '道照诸天',
      milestones: [
        {
          act: '第一幕',
          summary: '陆照在轮回试炼里发现道印线索，并意识到师门旧案与轮回空间有关。',
          consequence: '他决定主动进入下一场试炼追查真相。',
        },
      ],
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

    const detail = wrapper.findComponent(outlineDetailPanelStub).props('detail')
    const milestones = detail.sections.find((section) => section.title === '关键剧情里程碑')
    expect(milestones.items[0]).toContain('第一幕：陆照在轮回试炼里发现道印线索')
    expect(milestones.items[0]).not.toContain('主动进入下一场试炼')
    expect(milestones.detailItems[0]).toContain('主动进入下一场试炼')
  })

  it('renders review status and score details for failed auto revise volume outlines', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'volume_planning'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.outlineWorkbench.items = [
      {
        outline_type: 'volume',
        outline_ref: 'vol_1',
        itemId: 'volume:vol_1',
        key: 'volume:vol_1',
        title: '第 1 卷',
        status: 'needs_revision',
        statusLabel: '需人工处理',
        summary: '卷纲初稿',
      },
    ]
    store.outlineWorkbench.selection = {
      outline_type: 'volume',
      outline_ref: 'vol_1',
    }
    store.outlineWorkbench.lastResultSnapshot = {
      volume_id: 'vol_1',
      volume_number: 1,
      title: '第 1 卷',
      summary: '卷纲初稿',
      total_chapters: 1,
      estimated_total_words: 3000,
      chapters: [],
      review_status: {
        status: 'revise_failed',
        reason: '自动修订失败: parse failed',
        score: {
          overall: 50,
          outline_fidelity: 60,
          character_plot_alignment: 55,
          hook_distribution: 40,
          foreshadowing_management: 70,
          chapter_hooks: 45,
          page_turning: 50,
          summary_feedback: '爽点不足',
        },
      },
    }

    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineConversation: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('需人工处理')
    expect(wrapper.text()).toContain('自动修订失败')
    expect(wrapper.text()).toContain('parse failed')
    expect(wrapper.text()).toContain('评分明细')
    expect(wrapper.text()).toContain('整体评分：50')
    expect(wrapper.text()).toContain('评审意见：爽点不足')
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
