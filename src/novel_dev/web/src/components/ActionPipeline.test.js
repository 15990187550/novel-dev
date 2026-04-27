import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ActionPipeline from './ActionPipeline.vue'

const mockStore = vi.hoisted(() => ({
  stopCurrentFlow: vi.fn(),
  novelState: { current_phase: 'drafting' },
  loadingActions: { draft: true },
  stoppingFlow: false,
  hasRunningFlowAction: true,
  shouldShowStopFlow: true,
  stopFlowLabel: '停止写作草稿',
  canBrainstorm: false,
  canVolumePlan: false,
  canContext: false,
  canDraft: true,
  canAdvance: false,
  canLibrarian: false,
  canAutoRunChapter: true,
  autoRunLastResult: null,
  autoRunJob: null,
  executeAction: vi.fn(),
  refreshAutoRunJob: vi.fn(),
}))

vi.mock('@/stores/novel.js', () => ({
  useNovelStore: () => mockStore,
}))

vi.mock('@/api.js', () => ({
  importSynopsis: vi.fn(),
}))

describe('ActionPipeline', () => {
  beforeEach(() => {
    mockStore.stopCurrentFlow.mockClear()
    mockStore.refreshAutoRunJob.mockClear()
    mockStore.autoRunLastResult = null
    mockStore.autoRunJob = null
  })

  it('shows a stop button while a flow action is running', async () => {
    const wrapper = mount(ActionPipeline, {
      global: {
        stubs: {
          ElButton: {
            props: ['loading', 'disabled', 'type'],
            emits: ['click'],
            template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
          },
          ArrowRight: { template: '<span />' },
          Check: { template: '<span />' },
          CopyDocument: { template: '<span />' },
          Document: { template: '<span />' },
          Upload: { template: '<span />' },
          ElIcon: { template: '<span><slot /></span>' },
          ElTag: { template: '<span><slot /></span>' },
          ElInput: { template: '<textarea />' },
          'el-alert': { template: '<div />' },
        },
      },
    })

    expect(wrapper.text()).toContain('停止写作草稿')
    await wrapper.findAll('button').find(button => button.text().includes('停止写作草稿')).trigger('click')
    expect(mockStore.stopCurrentFlow).toHaveBeenCalledTimes(1)
  })

  it('shows the automatic single-chapter action when chapter generation can run', () => {
    const wrapper = mount(ActionPipeline, {
      global: {
        stubs: {
          ElButton: {
            props: ['loading', 'disabled', 'type'],
            emits: ['click'],
            template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
          },
          ArrowRight: { template: '<span />' },
          Check: { template: '<span />' },
          CopyDocument: { template: '<span />' },
          Document: { template: '<span />' },
          Upload: { template: '<span />' },
          ElIcon: { template: '<span><slot /></span>' },
          ElTag: { template: '<span><slot /></span>' },
          ElInput: { template: '<textarea />' },
          'el-alert': { template: '<div />' },
        },
      },
    })

    expect(wrapper.text()).toContain('自动写一章')
  })

  it('shows structured auto-run failure details', () => {
    mockStore.autoRunLastResult = {
      stopped_reason: 'failed',
      failed_phase: 'context_preparation',
      failed_chapter_id: 'ch-1',
      error: 'context exploded',
    }
    const wrapper = mount(ActionPipeline, {
      global: {
        stubs: {
          ElButton: {
            props: ['loading', 'disabled', 'type'],
            emits: ['click'],
            template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
          },
          ArrowRight: { template: '<span />' },
          Check: { template: '<span />' },
          CopyDocument: { template: '<span />' },
          Document: { template: '<span />' },
          Upload: { template: '<span />' },
          ElIcon: { template: '<span><slot /></span>' },
          ElTag: { template: '<span><slot /></span>' },
          ElInput: { template: '<textarea />' },
          'el-alert': {
            props: ['title', 'description', 'type'],
            template: '<div>{{ title }} {{ description }}</div>',
          },
        },
      },
    })

    expect(wrapper.text()).toContain('自动写章失败')
    expect(wrapper.text()).toContain('context_preparation')
    expect(wrapper.text()).toContain('ch-1')
    expect(wrapper.text()).toContain('context exploded')
  })

  it('shows queued auto-run job status and refresh action', async () => {
    mockStore.autoRunJob = {
      job_id: 'job-1',
      status: 'queued',
    }
    const wrapper = mount(ActionPipeline, {
      global: {
        stubs: {
          ElButton: {
            props: ['loading', 'disabled', 'type'],
            emits: ['click'],
            template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
          },
          ArrowRight: { template: '<span />' },
          Check: { template: '<span />' },
          CopyDocument: { template: '<span />' },
          Document: { template: '<span />' },
          Upload: { template: '<span />' },
          ElIcon: { template: '<span><slot /></span>' },
          ElTag: { template: '<span><slot /></span>' },
          ElInput: { template: '<textarea />' },
          'el-alert': {
            props: ['title', 'description', 'type'],
            template: '<div>{{ title }} {{ description }}<slot /></div>',
          },
        },
      },
    })

    expect(wrapper.text()).toContain('自动写章任务已提交')
    expect(wrapper.text()).toContain('job-1')
    expect(wrapper.text()).toContain('queued')
    await wrapper.findAll('button').find(button => button.text().includes('刷新任务')).trigger('click')
    expect(mockStore.refreshAutoRunJob).toHaveBeenCalledTimes(1)
  })
})
