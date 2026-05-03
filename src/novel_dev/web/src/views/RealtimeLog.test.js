import { mount } from '@vue/test-utils'
import { createPinia, getActivePinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import fs from 'node:fs'
import path from 'node:path'
import { useNovelStore } from '@/stores/novel.js'
import RealtimeLog from './RealtimeLog.vue'
import * as api from '@/api.js'

const { mockConfirm } = vi.hoisted(() => ({
  mockConfirm: vi.fn(),
}))
const mockLogs = ref([])

vi.mock('element-plus', () => ({
  ElMessageBox: {
    confirm: mockConfirm,
  },
}))

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
    mockConfirm.mockResolvedValue('confirm')
    mockLogs.value = []
  })

  it('confirms before clearing persisted logs and keeps the audit entry visible', async () => {
    const auditLog = {
      agent: 'LogService',
      message: '日志已清空，删除 1 条历史记录',
      level: 'warning',
      event: 'logs.clear',
    }
    vi.mocked(api.clearLogs).mockResolvedValue({ deleted_count: 1, audit_log: auditLog })
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

    expect(mockConfirm).toHaveBeenCalledWith(
      '会删除当前小说最近 7 天内已持久化的日志，仅保留一条清空记录。',
      '清空日志',
      {
        confirmButtonText: '清空',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    expect(api.clearLogs).toHaveBeenCalledWith('novel-1')
    expect(mockLogs.value).toEqual([auditLog])
  })

  it('does not clear logs when confirmation is cancelled', async () => {
    mockConfirm.mockRejectedValue(new Error('cancel'))
    const store = useNovelStore()
    store.novelId = 'novel-1'
    mockLogs.value = [{ agent: 'WriterAgent', message: '保留日志' }]

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

    expect(api.clearLogs).not.toHaveBeenCalled()
    expect(mockLogs.value).toEqual([{ agent: 'WriterAgent', message: '保留日志' }])
  })

  it('fills the app panel without using viewport calc heights', () => {
    const source = fs.readFileSync(path.resolve(__dirname, './RealtimeLog.vue'), 'utf8')

    expect(source).toContain('realtime-log-page h-full min-h-0 flex flex-col')
    expect(source).toContain('class="flex-1 min-h-0"')
    expect(source).not.toMatch(/\.realtime-log-page\s*{[\s\S]*height:\s*calc\(100vh/)
    expect(source).not.toMatch(/\.realtime-log-page\s*{[\s\S]*max-height:/)
  })
})
