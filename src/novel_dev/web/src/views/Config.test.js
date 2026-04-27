import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Config from './Config.vue'
import * as api from '@/api.js'

vi.mock('@/api.js', () => ({
  getLLMConfig: vi.fn(),
  saveLLMConfig: vi.fn(),
}))

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessage: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
    },
  }
})

describe('Config', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows every configured agent in the visual navigation', async () => {
    vi.mocked(api.getLLMConfig).mockResolvedValue({
      defaults: { timeout: 30, retries: 2, temperature: 0.7 },
      models: {
        main: { provider: 'anthropic', model: 'main-model' },
      },
      embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', dimensions: 1024 },
      agents: {
        entity_classifier_agent: { model: 'main' },
        outline_workbench_service: { model: 'main' },
      },
    })

    const wrapper = mount(Config, {
      global: {
        stubs: {
          AgentModelForm: true,
          ElButton: { template: '<button><slot /></button>' },
          ElCollapse: { template: '<div><slot /></div>' },
          ElCollapseItem: { template: '<div><slot /></div>' },
          ElEmpty: true,
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<label><slot /></label>' },
          ElInput: { template: '<input />' },
          ElInputNumber: { template: '<input />' },
          ElOption: true,
          ElRadioButton: { template: '<button><slot /></button>' },
          ElRadioGroup: { template: '<div><slot /></div>' },
          ElSelect: { template: '<select><slot /></select>' },
          ElSlider: true,
          ElSwitch: true,
          ElTag: { template: '<span><slot /></span>' },
          ElText: { template: '<span><slot /></span>' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Entity Classifier')
    expect(wrapper.text()).toContain('Outline Workbench')
  })
})
