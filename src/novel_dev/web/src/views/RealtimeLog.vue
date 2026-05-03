<template>
  <div class="realtime-log-page h-full min-h-0 flex flex-col">
    <div class="mb-2 flex items-center justify-between gap-3">
      <h2 class="text-xl font-bold">实时日志</h2>
      <el-button
        v-if="store.shouldShowStopFlow"
        type="danger"
        plain
        :loading="store.stoppingFlow"
        @click="store.stopCurrentFlow()"
      >
        {{ store.stopFlowLabel }}
      </el-button>
    </div>
    <LogConsole :logs="logs" :connected="connected" @clear="handleClearLogs" class="flex-1 min-h-0" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import * as api from '@/api.js'
import { useNovelStore } from '@/stores/novel.js'
import { useRealtimeLog } from '@/composables/useRealtimeLog.js'
import LogConsole from '@/components/LogConsole.vue'

const store = useNovelStore()
const novelIdRef = computed(() => store.novelId)
const { logs, connected } = useRealtimeLog(novelIdRef)

async function handleClearLogs() {
  if (store.novelId) {
    try {
      const confirmed = await ElMessageBox.confirm(
        '会删除当前小说最近 7 天内已持久化的日志，仅保留一条清空记录。',
        '清空日志',
        {
          confirmButtonText: '清空',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
      if (confirmed !== 'confirm') return
    } catch {
      return
    }
    const result = await api.clearLogs(store.novelId)
    logs.value = result?.audit_log ? [result.audit_log] : []
    return
  }
  logs.value = []
}
</script>
