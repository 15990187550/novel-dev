import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ABTestConsole from './ABTestConsole.vue'

vi.mock('axios', () => {
  const get = vi.fn()
  const post = vi.fn().mockResolvedValue({ data: {} })
  return {
    default: {
      get,
      post,
    },
    __esModule: true,
  }
})

import axios from 'axios'

describe('ABTestConsole', () => {
  beforeEach(() => {
    axios.get.mockReset()
    axios.post.mockReset()
    axios.get.mockResolvedValue({ data: { tests: [] } })
    axios.post.mockResolvedValue({ data: {} })
    // jsdom does not implement window.confirm by default
    window.confirm = vi.fn(() => true)
  })

  it('shows running tests', async () => {
    axios.get.mockResolvedValueOnce({
      data: {
        tests: [
          {
            id: 't1', agent_name: 'critic',
            baseline_version: 'v1.0', challenger_version: 'v2.0',
            status: 'running', winner: null,
          },
        ],
      },
    })

    const wrapper = mount(ABTestConsole)
    await flushPromises()

    const cards = wrapper.findAll('[data-testid="ab-test-card"]')
    expect(cards.length).toBe(1)
    expect(axios.get).toHaveBeenCalledWith('/api/ab-tests')
  })

  it('shows stop button for running tests', async () => {
    axios.get.mockResolvedValueOnce({
      data: {
        tests: [
          {
            id: 't1', status: 'running', agent_name: 'critic',
            baseline_version: 'v1.0', challenger_version: 'v2.0',
          },
        ],
      },
    })

    const wrapper = mount(ABTestConsole)
    await flushPromises()

    expect(wrapper.find('[data-testid="stop-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="view-results-btn"]').exists()).toBe(true)
  })

  it('shows empty state when no running tests', async () => {
    axios.get.mockResolvedValueOnce({ data: { tests: [] } })

    const wrapper = mount(ABTestConsole)
    await flushPromises()

    expect(wrapper.find('[data-testid="running-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="history-empty"]').exists()).toBe(true)
  })
})
