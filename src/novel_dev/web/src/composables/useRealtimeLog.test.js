import { effectScope, ref } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'
import { useRealtimeLog } from './useRealtimeLog.js'

describe('useRealtimeLog', () => {
  beforeEach(() => {
    globalThis.EventSource.reset()
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
})
