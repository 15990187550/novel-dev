import { ref, watch } from 'vue'

export function useRealtimeLog(novelIdRef) {
  const logs = ref([])
  const connected = ref(false)
  let es = null

  function connect() {
    if (es || !novelIdRef.value) return
    es = new EventSource(`/api/novels/${novelIdRef.value}/logs/stream`)
    es.onopen = () => { connected.value = true }
    es.onmessage = (e) => {
      const entry = JSON.parse(e.data)
      logs.value.push(entry)
      if (logs.value.length > 500) logs.value.shift()
    }
    es.onerror = () => { connected.value = false }
  }

  function disconnect() {
    es?.close()
    es = null
    connected.value = false
  }

  watch(novelIdRef, (id, oldId) => {
    if (id && id !== oldId) {
      disconnect()
      logs.value = []
      connect()
    }
  }, { immediate: true })

  return { logs, connected, connect, disconnect }
}
