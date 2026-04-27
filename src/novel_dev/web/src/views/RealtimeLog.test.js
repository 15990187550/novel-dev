import { mount } from '@vue/test-utils'
import { createPinia, getActivePinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import fs from 'node:fs'
import path from 'node:path'
import { useNovelStore } from '@/stores/novel.js'
import RealtimeLog from './RealtimeLog.vue'
import * as api from '@/api.js'

const mockLogs = ref([])

vi.mock('@/api.js', () => ({
  clearLogs: vi.fn(),
}))

vi.mock('@/composables/useRealtimeLog.js', () => ({
  useRealtimeLog: () => ({
    logs: mockLogs,
    connected: ref(true),
  }),
}))

describe('RealtimeLog', () => {
  beforeEach(() => {
    const pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
    mockLogs.value = []
  })

  it('clears persisted logs before clearing the visible log list', async () => {
    vi.mocked(api.clearLogs).mockResolvedValue({ deleted_count: 1 })
    const store = useNovelStore()
    store.novelId = 'novel-1'
    mockLogs.value = [{ agent: 'WriterAgent', message: '旧日志' }]

    const wrapper = mount(RealtimeLog, {
      global: {
        plugins: [getActivePinia()],
        stubs: {
          LogConsole: {
            emits: ['clear'],
            template: '<button class="clear-log-button" @click="$emit(\'clear\')">清空</button>',
          },
          ElButton: { template: '<button><slot /></button>' },
        },
      },
    })

    await wrapper.get('.clear-log-button').trigger('click')

    expect(api.clearLogs).toHaveBeenCalledWith('novel-1')
    expect(mockLogs.value).toEqual([])
  })

  it('fills the app panel without using viewport calc heights', () => {
    const source = fs.readFileSync(path.resolve(__dirname, './RealtimeLog.vue'), 'utf8')

    expect(source).toContain('realtime-log-page h-full min-h-0 flex flex-col')
    expect(source).toContain('class="flex-1 min-h-0"')
    expect(source).not.toMatch(/\.realtime-log-page\s*{[\s\S]*height:\s*calc\(100vh/)
    expect(source).not.toMatch(/\.realtime-log-page\s*{[\s\S]*max-height:/)
  })
})
