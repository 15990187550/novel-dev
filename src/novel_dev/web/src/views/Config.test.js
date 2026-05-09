import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Config from './Config.vue'
import * as api from '@/api.js'

vi.mock('@/api.js', () => ({
  getLLMConfig: vi.fn(),
  saveLLMConfig: vi.fn(),
  testLLMModel: vi.fn(),
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
        setting_consolidation_agent: { model: 'main' },
        setting_workbench_service: { model: 'main' },
      },
    })

    const wrapper = mount(Config, {
      global: {
        stubs: {
          AgentModelForm: true,
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
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
    expect(wrapper.text()).toContain('Setting Consolidation')
    expect(wrapper.text()).toContain('Setting Workbench')
  })

  it('tests a model profile and shows the connection result', async () => {
    vi.mocked(api.getLLMConfig).mockResolvedValue({
      defaults: { timeout: 30, retries: 2, temperature: 0.7 },
      models: {
        main: { provider: 'anthropic', model: 'claude-test', base_url: 'https://api.example.test', api_key: 'sk-test' },
      },
      embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', dimensions: 1024 },
      agents: {},
    })
    vi.mocked(api.testLLMModel).mockResolvedValue({
      ok: true,
      status: 'success',
      message: '连接成功',
      latency_ms: 12,
    })

    const wrapper = mount(Config, {
      global: {
        stubs: {
          AgentModelForm: true,
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
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

    await wrapper.findAll('.cursor-pointer').find(item => item.text().includes('模型 Profiles')).trigger('click')
    const testButton = wrapper.get('[data-testid="test-model-main"]')
    await testButton.trigger('click')
    await flushPromises()

    expect(api.testLLMModel).toHaveBeenCalledWith('main', {
      provider: 'anthropic',
      model: 'claude-test',
      base_url: 'https://api.example.test',
      api_key: 'sk-test',
    })
    expect(wrapper.text()).toContain('连接成功')
    expect(wrapper.text()).toContain('12ms')
  })

  it('hydrates masked api keys for env-backed model profiles', async () => {
    vi.mocked(api.getLLMConfig).mockResolvedValue({
      defaults: { timeout: 30, retries: 2, temperature: 0.7 },
      models: {
        deepseek: {
          provider: 'anthropic',
          model: 'deepseek-v4-flash',
          base_url: 'https://api.deepseek.com/anthropic',
          api_key_env: 'DEEPSEEK_API_KEY',
          api_key: '********',
        },
      },
      embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', dimensions: 1024 },
      agents: {},
    })

    const wrapper = mount(Config, {
      global: {
        stubs: {
          AgentModelForm: true,
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
          ElCollapse: { template: '<div><slot /></div>' },
          ElCollapseItem: { template: '<div><slot /></div>' },
          ElEmpty: true,
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<label><slot /></label>' },
          ElInput: {
            props: ['modelValue'],
            template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
          },
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

    await wrapper.findAll('.cursor-pointer').find(item => item.text().includes('模型 Profiles')).trigger('click')
    const inputs = wrapper.findAll('input')
    expect(inputs.some((input) => input.element.value === '********')).toBe(true)
  })

  it('edits orchestration settings from the visual agent panel', async () => {
    vi.mocked(api.getLLMConfig).mockResolvedValue({
      defaults: { timeout: 30, retries: 2, temperature: 0.7 },
      models: {
        main: { provider: 'anthropic', model: 'main-model' },
      },
      embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', dimensions: 1024 },
      agents: {
        context_agent: {
          model: 'main',
          orchestration: {
            enabled: true,
            tool_allowlist: [
              'get_context_location_details',
              'get_context_entity_states',
              'get_novel_state',
            ],
            max_tool_calls: 3,
            tool_timeout_seconds: 5,
            max_tool_result_chars: 1600,
            enable_subtasks: true,
            validator_subtask: 'location_context_quality',
            repairer_subtask: 'schema_repair',
          },
        },
      },
    })
    vi.mocked(api.saveLLMConfig).mockResolvedValue({ saved: true, reloaded: true })

    const wrapper = mount(Config, {
      global: {
        stubs: {
          AgentModelForm: true,
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
          ElCollapse: { template: '<div><slot /></div>' },
          ElCollapseItem: { template: '<div><slot /></div>' },
          ElEmpty: true,
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<label><slot /></label>' },
          ElInput: { template: '<input />' },
          ElInputNumber: {
            props: ['modelValue'],
            template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
          },
          ElOption: true,
          ElRadioButton: { template: '<button><slot /></button>' },
          ElRadioGroup: { template: '<div><slot /></div>' },
          ElSelect: { template: '<select><slot /></select>' },
          ElSlider: true,
          ElSwitch: {
            props: ['modelValue'],
            template: '<input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked); $emit(\'change\', $event.target.checked)" />',
          },
          ElTag: { template: '<span><slot /></span>' },
          ElText: { template: '<span><slot /></span>' },
        },
      },
    })

    await flushPromises()

    await wrapper.findAll('.cursor-pointer').find(item => item.text().includes('Context')).trigger('click')

    expect(wrapper.text()).toContain('新链路 Orchestration')
    expect(wrapper.text()).toContain('批量地点详情')
    expect(wrapper.text()).toContain('批量实体状态')

    await wrapper.get('[data-testid="orchestration-max-tool-calls-context_agent"]').setValue('2')
    await wrapper.get('[data-testid="orchestration-tool-context_agent-get_novel_state"]').setValue(false)
    await wrapper.get('[data-testid="save-config"]').trigger('click')
    await flushPromises()

    const saved = vi.mocked(api.saveLLMConfig).mock.calls[0][0]
    expect(saved.agents.context_agent.orchestration.max_tool_calls).toBe(2)
    expect(saved.agents.context_agent.orchestration.tool_allowlist).toEqual([
      'get_context_location_details',
      'get_context_entity_states',
    ])
  })

  it('edits task-level orchestration settings from the visual agent panel', async () => {
    vi.mocked(api.getLLMConfig).mockResolvedValue({
      defaults: { timeout: 30, retries: 2, temperature: 0.7 },
      models: {
        main: { provider: 'anthropic', model: 'main-model' },
      },
      embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', dimensions: 1024 },
      agents: {
        volume_planner_agent: {
          model: 'main',
          tasks: {
            generate_volume_plan: {
              temperature: 0.85,
              orchestration: {
                enabled: false,
                tool_allowlist: ['get_volume_planner_context', 'get_novel_documents'],
                max_tool_calls: 3,
                max_tool_result_chars: 6000,
                enable_subtasks: true,
                repairer_subtask: 'schema_repair',
              },
            },
          },
        },
      },
    })
    vi.mocked(api.saveLLMConfig).mockResolvedValue({ saved: true, reloaded: true })

    const wrapper = mount(Config, {
      global: {
        stubs: {
          AgentModelForm: true,
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
          ElCollapse: { template: '<div><slot /></div>' },
          ElCollapseItem: { template: '<div><slot /></div>' },
          ElEmpty: true,
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<label><slot /></label>' },
          ElInput: { template: '<input />' },
          ElInputNumber: {
            props: ['modelValue'],
            template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
          },
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

    await wrapper.findAll('.cursor-pointer').find(item => item.text().includes('Volume Planner')).trigger('click')

    expect(wrapper.text()).toContain('任务新链路')
    expect(wrapper.text()).toContain('卷纲规划上下文')

    await wrapper.get('[data-testid="orchestration-enabled-volume_planner_agent-generate_volume_plan"]').setValue(true)
    await wrapper.get('[data-testid="orchestration-max-tool-calls-volume_planner_agent-generate_volume_plan"]').setValue('2')
    await wrapper.get('[data-testid="orchestration-tool-volume_planner_agent-generate_volume_plan-get_novel_documents"]').setValue(false)
    await wrapper.get('[data-testid="save-config"]').trigger('click')
    await flushPromises()

    const saved = vi.mocked(api.saveLLMConfig).mock.calls[0][0]
    const orchestration = saved.agents.volume_planner_agent.tasks.generate_volume_plan.orchestration
    expect(orchestration.enabled).toBe(true)
    expect(orchestration.max_tool_calls).toBe(2)
    expect(orchestration.tool_allowlist).toEqual(['get_volume_planner_context'])
  })

  it('shows orchestration controls for setting workbench service', async () => {
    vi.mocked(api.getLLMConfig).mockResolvedValue({
      defaults: { timeout: 30, retries: 2, temperature: 0.7 },
      models: {
        main: { provider: 'anthropic', model: 'main-model' },
      },
      embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', dimensions: 1024 },
      agents: {
        setting_workbench_service: {
          model: 'main',
          orchestration: {
            enabled: false,
            tool_allowlist: ['get_setting_workbench_context', 'get_novel_documents'],
            max_tool_calls: 3,
            tool_timeout_seconds: 5,
            max_tool_result_chars: 4000,
            enable_subtasks: true,
            repairer_subtask: 'schema_repair',
          },
        },
      },
    })

    const wrapper = mount(Config, {
      global: {
        stubs: {
          AgentModelForm: true,
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
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

    await wrapper.findAll('.cursor-pointer').find(item => item.text().includes('Setting Workbench')).trigger('click')

    expect(wrapper.text()).toContain('新链路 Orchestration')
    expect(wrapper.text()).toContain('设定工作台上下文')
    expect(wrapper.text()).toContain('实体详情')
    expect(wrapper.text()).toContain('文档摘要列表')
    expect(wrapper.text()).toContain('规则域资料检索')
  })
})
