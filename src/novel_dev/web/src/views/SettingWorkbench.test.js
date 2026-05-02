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

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: routerPushMock }),
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

  it('shows import and AI entries plus review records', async () => {
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    await flushPromises()

    expect(wrapper.text()).toContain('导入已有资料')
    expect(wrapper.text()).toContain('从想法生成设定')
    expect(wrapper.text()).toContain('审核记录')
    expect(wrapper.text()).toContain('AI 会话')
    expect(wrapper.text()).toContain('导入资料')
    expect(wrapper.text()).toContain('新增 1 张设定卡片，1 个实体')
    expect(wrapper.text()).toContain('导入 2 条世界观设定')

    await wrapper.find('[data-testid="setting-import-entry"]').trigger('click')
    expect(routerPushMock).toHaveBeenCalledWith('/documents')
  })

  it('creates an AI session, sends a reply, and shows the generation action', async () => {
    const wrapper = mountView()
    const store = useNovelStore()
    store.novelId = 'novel-1'
    await flushPromises()

    await wrapper.find('[data-testid="setting-ai-entry"]').trigger('click')
    await wrapper.find('[data-testid="setting-session-title"]').setValue('主角阵营设定')
    await wrapper.find('[data-testid="setting-session-idea"]').setValue('废脉少年建立新的修真阵营')
    await wrapper.find('[data-testid="setting-create-session"]').trigger('click')
    await flushPromises()

    expect(createSettingSessionMock).toHaveBeenCalledWith('novel-1', {
      title: '主角阵营设定',
      initial_idea: '废脉少年建立新的修真阵营',
      target_categories: [],
    })
    expect(wrapper.text()).toContain('主角阵营设定')
    expect(wrapper.text()).toContain('请补充阵营目标。')

    await wrapper.find('[data-testid="setting-reply-input"]').setValue('阵营目标是保护底层散修。')
    await wrapper.find('[data-testid="setting-send-reply"]').trigger('click')
    await flushPromises()

    expect(replySettingSessionMock).toHaveBeenCalledWith('novel-1', 'sgs_2', {
      content: '阵营目标是保护底层散修。',
    })
    expect(wrapper.text()).toContain('信息足够，可以生成。')
    expect(wrapper.text()).toContain('可生成')
    expect(wrapper.find('[data-testid="setting-generate-batch"]').exists()).toBe(true)
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

    await wrapper.find('[data-testid="setting-ai-entry"]').trigger('click')
    await wrapper.find('[data-testid="setting-generate-batch"]').trigger('click')
    await flushPromises()

    expect(generateSettingReviewBatchMock).toHaveBeenCalledWith('novel-1', 'sgs_2', {})
    expect(wrapper.text()).toContain('新增 1 张设定卡片')
  })
})
