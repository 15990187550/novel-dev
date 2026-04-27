import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LogConsole from './LogConsole.vue'

describe('LogConsole', () => {
  it('renders structured status, level and node labels when present', () => {
    const wrapper = mount(LogConsole, {
      props: {
        connected: true,
        logs: [
          {
            timestamp: '2026-04-25T01:00:00Z',
            agent: 'WriterAgent',
            level: 'warning',
            status: 'failed',
            node: 'generate_beat',
            message: '生成失败',
          },
        ],
      },
      global: {
        stubs: {
          ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
          ElButton: { template: '<button><slot /></button>' },
        },
      },
    })

    expect(wrapper.text()).toContain('warning')
    expect(wrapper.text()).toContain('failed')
    expect(wrapper.text()).toContain('generate_beat')
    expect(wrapper.text()).toContain('生成失败')
  })
})
