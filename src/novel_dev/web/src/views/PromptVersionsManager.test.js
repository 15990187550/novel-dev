import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PromptVersionsManager from './PromptVersionsManager.vue'

vi.mock('axios', () => {
  const get = vi.fn()
  const post = vi.fn().mockResolvedValue({ data: {} })
  const patch = vi.fn().mockResolvedValue({ data: {} })
  const del = vi.fn().mockResolvedValue({ data: {} })
  return {
    default: {
      get,
      post,
      patch,
      delete: del,
    },
    __esModule: true,
  }
})

import axios from 'axios'

describe('PromptVersionsManager', () => {
  beforeEach(() => {
    axios.get.mockReset()
    axios.get.mockResolvedValue({ data: { versions: [] } })
  })

  it('shows empty state when no versions', async () => {
    axios.get.mockResolvedValueOnce({ data: { versions: [] } })

    const wrapper = mount(PromptVersionsManager)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true)
    expect(axios.get).toHaveBeenCalledWith('/api/prompts/writer/versions')
  })

  it('lists versions returned by API', async () => {
    axios.get.mockResolvedValueOnce({
      data: {
        versions: [
          { version: 'v1.0', is_active: true, content: 'a', sample_count: 10, created_at: '2026-06-01T00:00:00Z' },
          { version: 'v2.0', is_active: false, content: 'b', sample_count: 0, created_at: '2026-06-02T00:00:00Z' },
        ],
      },
    })

    const wrapper = mount(PromptVersionsManager)
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="version-row"]')
    expect(rows.length).toBe(2)
    expect(wrapper.find('[data-testid="active-badge"]').exists()).toBe(true)
  })

  it('refetches when selected agent changes', async () => {
    axios.get.mockResolvedValue({ data: { versions: [] } })

    const wrapper = mount(PromptVersionsManager)
    await flushPromises()

    expect(axios.get).toHaveBeenCalledTimes(1)

    const select = wrapper.find('[data-testid="agent-select"]')
    await select.setValue('critic')
    await flushPromises()

    expect(axios.get).toHaveBeenCalledTimes(2)
    expect(axios.get).toHaveBeenLastCalledWith('/api/prompts/critic/versions')
  })
})
