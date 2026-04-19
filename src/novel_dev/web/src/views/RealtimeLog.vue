<template>
  <div class="h-full flex flex-col">
    <h2 class="text-xl font-bold mb-2">实时日志</h2>
    <LogConsole :logs="logs" :connected="connected" @clear="logs = []" class="flex-1 min-h-0" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { useRealtimeLog } from '@/composables/useRealtimeLog.js'
import LogConsole from '@/components/LogConsole.vue'

const store = useNovelStore()
const novelIdRef = computed(() => store.novelId)
const { logs, connected } = useRealtimeLog(novelIdRef)
</script>
