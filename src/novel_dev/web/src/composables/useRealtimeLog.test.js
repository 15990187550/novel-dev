import { effectScope, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRealtimeLog } from './useRealtimeLog.js'

const { getLogsMock } = vi.hoisted(() => ({
  getLogsMock: vi.fn(),
}))

vi.mock('@/api.js', () => ({
  getLogs: getLogsMock,
}))

describe('useRealtimeLog', () => {
  beforeEach(() => {
    globalThis.EventSource.reset()
    getLogsMock.mockReset()
    getLogsMock.mockResolvedValue({ logs: [] })
  })

  it('shares one live log buffer across consumers for the same novel', () => {
    const novelId = ref('novel-1')
    const appScope = effectScope()
    const pageScope = effectScope()
    let appLogs
    let pageLogs

    appScope.run(() => {
      appLogs = useRealtimeLog(novelId)
    })
    pageScope.run(() => {
      pageLogs = useRealtimeLog(novelId)
    })

    expect(globalThis.EventSource.instances).toHaveLength(1)

    globalThis.EventSource.instances[0].onmessage({
      data: JSON.stringify({ agent: 'WriterAgent', message: '内存日志' }),
    })

    expect(appLogs.logs.value).toHaveLength(1)
    expect(pageLogs.logs.value).toEqual(appLogs.logs.value)

    pageScope.stop()

    expect(globalThis.EventSource.instances[0].closed).toBe(false)
    expect(appLogs.logs.value[0].message).toBe('内存日志')

    appScope.stop()

    expect(globalThis.EventSource.instances[0].closed).toBe(true)
  })

  it('keeps the shared stream open when a secondary consumer calls disconnect', () => {
    const novelId = ref('novel-1')
    const appScope = effectScope()
    const pageScope = effectScope()
    let appLogs
    let pageLogs

    appScope.run(() => {
      appLogs = useRealtimeLog(novelId)
    })
    pageScope.run(() => {
      pageLogs = useRealtimeLog(novelId)
    })

    pageLogs.disconnect()

    expect(globalThis.EventSource.instances[0].closed).toBe(false)

    globalThis.EventSource.instances[0].onmessage({
      data: JSON.stringify({ agent: 'ContextAgent', message: '继续接收' }),
    })

    expect(appLogs.logs.value.map((log) => log.message)).toEqual(['继续接收'])
    expect(pageLogs.logs.value).toEqual([])

    appScope.stop()

    expect(globalThis.EventSource.instances[0].closed).toBe(true)
  })

  it('loads persisted history when connecting and dedupes SSE history replay', async () => {
    getLogsMock.mockResolvedValue({
      logs: [
        { timestamp: '2026-04-28T09:00:00Z', agent: 'WriterAgent', message: '持久化日志' },
      ],
    })
    const novelId = ref('novel-1')
    const scope = effectScope()
    let realtime

    scope.run(() => {
      realtime = useRealtimeLog(novelId)
    })

    await Promise.resolve()
    await Promise.resolve()

    expect(getLogsMock).toHaveBeenCalledWith('novel-1')
    expect(realtime.logs.value.map((log) => log.message)).toEqual(['持久化日志'])

    globalThis.EventSource.instances[0].onmessage({
      data: JSON.stringify({ timestamp: '2026-04-28T09:00:00Z', agent: 'WriterAgent', message: '持久化日志' }),
    })
    globalThis.EventSource.instances[0].onmessage({
      data: JSON.stringify({ timestamp: '2026-04-28T09:01:00Z', agent: 'CriticAgent', message: '新日志' }),
    })

    expect(realtime.logs.value.map((log) => log.message)).toEqual(['持久化日志', '新日志'])

    scope.stop()
  })
})
