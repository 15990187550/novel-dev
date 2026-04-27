import { computed, onScopeDispose, ref, watch } from 'vue'

const streams = new Map()

function createStream(novelId) {
  return {
    novelId,
    logs: ref([]),
    connected: ref(false),
    eventSource: null,
    refs: 0,
  }
}

function getStream(novelId) {
  if (!streams.has(novelId)) {
    streams.set(novelId, createStream(novelId))
  }
  return streams.get(novelId)
}

function openStream(stream) {
  if (stream.eventSource || !stream.novelId) return
  const es = new EventSource(`/api/novels/${stream.novelId}/logs/stream`)
  stream.eventSource = es
  es.onopen = () => { stream.connected.value = true }
  es.onmessage = (e) => {
    const entry = JSON.parse(e.data)
    stream.logs.value.push(entry)
    if (stream.logs.value.length > 500) stream.logs.value.shift()
  }
  es.onerror = () => { stream.connected.value = false }
}

function closeStream(stream) {
  stream.eventSource?.close()
  stream.eventSource = null
  stream.connected.value = false
}

export function useRealtimeLog(novelIdRef) {
  const activeNovelId = ref(null)
  let released = false

  function connect() {
    const novelId = novelIdRef.value
    if (!novelId || activeNovelId.value === novelId) return
    releaseActive()
    const stream = getStream(novelId)
    stream.refs += 1
    activeNovelId.value = novelId
    released = false
    openStream(stream)
  }

  function disconnect() {
    releaseActive()
  }

  function releaseActive() {
    if (!activeNovelId.value || released) return
    const stream = streams.get(activeNovelId.value)
    if (stream) {
      stream.refs = Math.max(0, stream.refs - 1)
      if (stream.refs === 0) {
        closeStream(stream)
        streams.delete(activeNovelId.value)
      }
    }
    activeNovelId.value = null
    released = true
  }

  watch(novelIdRef, (id, oldId) => {
    if (id && id !== oldId) {
      connect()
    } else if (!id) {
      disconnect()
    }
  }, { immediate: true })

  onScopeDispose(disconnect)

  const logs = computed({
    get() {
      return streams.get(activeNovelId.value)?.logs.value || []
    },
    set(value) {
      const stream = streams.get(activeNovelId.value)
      if (stream) stream.logs.value = value
    },
  })
  const connected = computed(() => streams.get(activeNovelId.value)?.connected.value || false)

  return { logs, connected, connect, disconnect }
}
