import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingWorkbench from './SettingWorkbench.vue'
import { useNovelStore } from '@/stores/novel.js'

const {
  getSettingWorkbenchMock,
  getSettingSessionMock,
  createSettingSessionMock,
  replySettingSessionMock,
  generateSettingReviewBatchMock,
} = vi.hoisted(() => ({
  getSettingWorkbenchMock: vi.fn(),
  getSettingSessionMock: vi.fn(),
  createSettingSessionMock: vi.fn(),
  replySettingSessionMock: vi.fn(),
  generateSettingReviewBatchMock: vi.fn(),
}))

vi.mock('@/api.js', () => ({
  getSettingWorkbench: getSettingWorkbenchMock,
  getSettingSession: getSettingSessionMock,
  createSettingSession: createSettingSessionMock,
  replySettingSession: replySettingSessionMock,
  generateSettingReviewBatch: generateSettingReviewBatchMock,
}))

const routerPushMock = vi.fn()
const routerReplaceMock = vi.fn()
const routeState = vi.hoisted(() => ({
  query: {},
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: routerPushMock, replace: routerReplaceMock }),
}))

const ElAlertStub = defineComponent({
  name: 'ElAlertStub',
  props: {
    title: { type: String, default: '' },
  },
  setup(props) {
    return () => h('div', { class: 'el-alert-stub' }, props.title)
  },
})

describe('SettingWorkbench', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    routerPushMock.mockReset()
    routerReplaceMock.mockReset()
    routeState.query = {}
    getSettingWorkbenchMock.mockResolvedValue({
      sessions: [
        {
          id: 'sgs_1',
          title: '修炼体系补全',
          status: 'clarifying',
          target_categories: ['功法'],
          clarification_round: 1,
        },
      ],
      review_batches: [
        {
          id: 'srb_1',
          source_type: 'ai_session',
          source_session_id: 'sgs_1',
          status: 'pending',
          summary: '新增 1 张设定卡片，1 个实体',
          counts: { setting_card: 1, entity: 1, relationship: 0 },
          changes: [],
        },
        {
          id: 'srb_import',
          source_type: 'import',
          status: 'pending',
          summary: '导入 2 条世界观设定',
          counts: { setting_card: 2, entity: 0, relationship: 0 },
          changes: [],
        },
      ],
    })
    getSettingSessionMock.mockResolvedValue({
      session: {
        id: 'sgs_2',
        title: '主角阵营设定',
        status: 'clarifying',
        target_categories: ['人物'],
        clarification_round: 0,
      },
      messages: [
        { role: 'assistant', content: '请补充阵营目标。' },
      ],
    })
    createSettingSessionMock.mockResolvedValue({
      id: 'sgs_2',
      title: '主角阵营设定',
      status: 'clarifying',
      target_categories: ['人物'],
      clarification_round: 0,
    })
    replySettingSessionMock.mockResolvedValue({
      session: {
        id: 'sgs_2',
        title: '主角阵营设定',
        status: 'ready_to_generate',
        target_categories: ['人物'],
        clarification_round: 1,
      },
      assistant_message: '信息足够，可以生成。',
      questions: [],
    })
    generateSettingReviewBatchMock.mockResolvedValue({
      id: 'srb_2',
      source_type: 'ai_session',
      source_session_id: 'sgs_2',
      status: 'pending',
      summary: '新增 1 张设定卡片',
      counts: { setting_card: 1, entity: 0, relationship: 0 },
      changes: [],
    })
  })

  function mountView() {
    return mount(SettingWorkbench, {
      global: {
        plugins: [createPinia()],
        stubs: { ElAlert: ElAlertStub },
      },
    })
  }

  it('shows the AI conversation and review records', async () => {
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    await flushPromises()

    expect(wrapper.text()).toContain('AI 生成设定')
    expect(wrapper.text()).toContain('审核记录')
    expect(wrapper.text()).toContain('导入资料')
    expect(wrapper.text()).toContain('新增 1 张设定卡片，1 个实体')
    expect(wrapper.text()).toContain('导入 2 条世界观设定')
  })

  it('creates an AI session from the reply input and shows the generation action', async () => {
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    await flushPromises()

    await wrapper.find('[data-testid="setting-reply-input"]').setValue('废脉少年建立新的修真阵营')
    await wrapper.find('[data-testid="setting-send-reply"]').trigger('click')
    await flushPromises()

    expect(createSettingSessionMock).toHaveBeenCalledWith('novel-1', {
      title: '废脉少年建立新的修真阵营',
      initial_idea: '',
      target_categories: [],
    })
    expect(routerReplaceMock).toHaveBeenCalledWith({ path: '/settings', query: { tab: 'ai', session: 'sgs_2' } })
    expect(replySettingSessionMock).toHaveBeenCalledWith('novel-1', 'sgs_2', {
      content: '废脉少年建立新的修真阵营',
    })
    expect(wrapper.text()).toContain('主角阵营设定')
    expect(wrapper.text()).toContain('信息足够，可以生成。')
    expect(wrapper.text()).toContain('可生成')
    expect(wrapper.find('[data-testid="setting-generate-batch"]').exists()).toBe(true)
  })

  it('renders clarification questions stored in assistant message metadata', async () => {
    getSettingSessionMock.mockResolvedValueOnce({
      session: {
        id: 'sgs_questions',
        title: '诸天万界设定',
        status: 'clarifying',
        target_categories: ['世界观'],
        clarification_round: 1,
      },
      messages: [
        {
          role: 'assistant',
          content: '还需要明确以下关键问题：',
          meta: {
            questions: [
              '诸天万界的范围是原著体系内，还是包含其他小说宇宙？',
              '主角跨界是投影、映照，还是真身穿越？',
            ],
          },
        },
      ],
    })
    routeState.query = { session: 'sgs_questions' }
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    await flushPromises()

    expect(wrapper.text()).toContain('还需要明确以下关键问题：')
    expect(wrapper.text()).toContain('诸天万界的范围是原著体系内，还是包含其他小说宇宙？')
    expect(wrapper.text()).toContain('主角跨界是投影、映照，还是真身穿越？')
  })

  it('adds a review record after generation', async () => {
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.settingWorkbench.selectedSessionId = 'sgs_2'
    store.settingWorkbench.selectedSession = {
      id: 'sgs_2',
      title: '主角阵营设定',
      status: 'ready_to_generate',
    }
    await flushPromises()

    await wrapper.find('[data-testid="setting-generate-batch"]').trigger('click')
    await flushPromises()

    expect(generateSettingReviewBatchMock).toHaveBeenCalledWith('novel-1', 'sgs_2', {})
    expect(wrapper.text()).toContain('新增 1 张设定卡片')
    expect(wrapper.find('[data-testid="setting-generate-batch"]').exists()).toBe(false)
  })

  it('does not show the generate button for already generated sessions', async () => {
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.settingWorkbench.selectedSessionId = 'sgs_done'
    store.settingWorkbench.selectedSession = {
      id: 'sgs_done',
      title: '已生成会话',
      status: 'generated',
    }
    await flushPromises()

    expect(wrapper.text()).toContain('已生成')
    expect(wrapper.find('[data-testid="setting-generate-batch"]').exists()).toBe(false)
  })

  it('keeps reply draft when sending fails', async () => {
    replySettingSessionMock.mockRejectedValueOnce(new Error('网络失败'))
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.settingWorkbench.selectedSessionId = 'sgs_2'
    store.settingWorkbench.selectedSession = {
      id: 'sgs_2',
      title: '主角阵营设定',
      status: 'clarifying',
    }
    await flushPromises()

    await wrapper.find('[data-testid="setting-reply-input"]').setValue('这段回答不能丢')
    await wrapper.find('[data-testid="setting-send-reply"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="setting-reply-input"]').element.value).toBe('这段回答不能丢')
  })

  it('does not clear a new session draft when an old reply resolves', async () => {
    let resolveReply
    replySettingSessionMock.mockReturnValueOnce(new Promise((resolve) => {
      resolveReply = resolve
    }))
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.settingWorkbench.selectedSessionId = 'sgs_a'
    store.settingWorkbench.selectedSession = {
      id: 'sgs_a',
      title: '会话 A',
      status: 'clarifying',
    }
    await flushPromises()

    await wrapper.find('[data-testid="setting-reply-input"]').setValue('A 的回答')
    await wrapper.find('[data-testid="setting-send-reply"]').trigger('click')
    store.settingWorkbench.selectedSessionId = 'sgs_b'
    store.settingWorkbench.selectedSession = {
      id: 'sgs_b',
      title: '会话 B',
      status: 'clarifying',
    }
    await wrapper.find('[data-testid="setting-reply-input"]').setValue('B 的新回答')
    resolveReply({
      session: { id: 'sgs_a', title: '会话 A', status: 'ready_to_generate' },
      assistant_message: 'A 已就绪',
      questions: [],
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="setting-reply-input"]').element.value).toBe('B 的新回答')
  })
})
