<template>
  <div class="log-console flex flex-col h-full min-h-0 bg-gray-950 text-gray-100 rounded-lg overflow-hidden font-mono text-sm">
    <div class="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-800">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-xs text-gray-400">过滤:</span>
        <el-tag v-for="agent in allAgents" :key="agent" size="small"
          :type="isFiltered(agent) ? '' : 'info'" :effect="isFiltered(agent) ? 'dark' : 'plain'"
          class="cursor-pointer" @click="toggleFilter(agent)">{{ agent }}</el-tag>
      </div>
      <div class="flex items-center gap-2">
        <el-tag size="small" :type="connected ? 'success' : 'danger'">{{ connected ? '已连接' : '断开' }}</el-tag>
        <el-button size="small" @click="paused = !paused">{{ paused ? '继续' : '暂停' }}</el-button>
        <el-button size="small" @click="$emit('clear')">清空</el-button>
      </div>
    </div>
    <div
      ref="logContainer"
      class="log-console__scroll flex-1 overflow-y-auto p-2"
      data-testid="log-scroll-container"
      @scroll="onScroll"
    >
      <div ref="logEntries" class="log-console__entries min-h-full" data-testid="log-entry-list">
        <div
          v-for="(log, i) in visibleLogs"
          :key="i"
          class="flex gap-2 hover:bg-gray-900/50 px-1 rounded"
          :data-testid="`log-line-${i}`"
        >
          <span class="text-gray-500 shrink-0">{{ formatTime(log.timestamp) }}</span>
          <span class="shrink-0 font-semibold" :style="{ color: agentColor(log.agent) }">[{{ log.agent }}]</span>
          <span v-if="log.level" class="shrink-0 rounded border px-1 text-[11px]" :class="levelClass(log.level)">{{ log.level }}</span>
          <span v-if="log.status" class="shrink-0 rounded border border-sky-800/70 bg-sky-950/60 px-1 text-[11px] text-sky-200">{{ log.status }}</span>
          <span v-if="log.node" class="shrink-0 rounded border border-gray-700 bg-gray-900 px-1 text-[11px] text-gray-300">{{ log.node }}</span>
          <span class="text-gray-300">{{ log.message }}</span>
        </div>
      </div>
    </div>
    <button
      v-if="pendingNewLogs > 0"
      type="button"
      class="log-console__new-log-prompt"
      data-testid="new-log-prompt"
      @click="scrollToBottom('smooth')"
    >
      {{ pendingNewLogs }} 条新日志，跳到底部
    </button>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import { formatBeijingTime } from '@/utils/time.js'

const props = defineProps({ logs: { type: Array, default: () => [] }, connected: { type: Boolean, default: false } })
const emit = defineEmits(['clear'])

const paused = ref(false)
const filters = ref(new Set())
const logContainer = ref(null)
const logEntries = ref(null)
const autoScroll = ref(true)
const pendingNewLogs = ref(0)
let resizeObserver = null

const colors = { NovelDirector: '#9ca3af', VolumePlannerAgent: '#60a5fa', WriterAgent: '#4ade80', CriticAgent: '#fb923c', EditorAgent: '#c084fc', FastReviewAgent: '#facc15', LibrarianAgent: '#f472b6', ContextAgent: '#2dd4bf' }

const allAgents = computed(() => Array.from(new Set(props.logs.map(l => l.agent))).sort())
const visibleLogs = computed(() => filters.value.size === 0 ? props.logs : props.logs.filter(l => filters.value.has(l.agent)))

function isFiltered(agent) { return filters.value.size === 0 || filters.value.has(agent) }
function toggleFilter(agent) { filters.value.has(agent) ? filters.value.delete(agent) : filters.value.add(agent) }
function agentColor(agent) { return colors[agent] || '#9ca3af' }
function formatTime(ts) { return formatBeijingTime(ts) }
function levelClass(level) {
  if (level === 'error') return 'border-red-800/80 bg-red-950/70 text-red-200'
  if (level === 'warning') return 'border-amber-800/80 bg-amber-950/70 text-amber-200'
  return 'border-gray-700 bg-gray-900 text-gray-400'
}
function onScroll() {
  const el = logContainer.value
  if (!el) return
  autoScroll.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 20
  if (autoScroll.value) pendingNewLogs.value = 0
}

function afterLayout() {
  return new Promise(resolve => {
    const frame = typeof requestAnimationFrame === 'function'
      ? requestAnimationFrame
      : callback => setTimeout(callback, 0)
    frame(() => frame(resolve))
  })
}

async function scrollToBottom(behavior = 'smooth') {
  await nextTick()
  await afterLayout()
  const el = logContainer.value
  if (!el) return
  if (typeof el.scrollTo === 'function') {
    el.scrollTo({ top: el.scrollHeight, behavior })
  } else {
    el.scrollTop = el.scrollHeight
  }
  autoScroll.value = true
  pendingNewLogs.value = 0
}

onMounted(() => {
  scrollToBottom('auto')
  if (typeof ResizeObserver === 'function' && logEntries.value) {
    resizeObserver = new ResizeObserver(() => {
      if (autoScroll.value && !paused.value) scrollToBottom('auto')
    })
    resizeObserver.observe(logEntries.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})

watch(() => visibleLogs.value.length, async (nextLength, previousLength = 0) => {
  const addedCount = Math.max(0, nextLength - previousLength)
  if (paused.value || !autoScroll.value) {
    if (addedCount > 0) pendingNewLogs.value += addedCount
    return
  }
  await nextTick()
  scrollToBottom('smooth')
})
</script>

<style scoped>
.log-console {
  position: relative;
}

.log-console__scroll {
  min-height: 0;
}

.log-console__entries {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: 0.125rem;
}

.log-console__new-log-prompt {
  position: absolute;
  left: 50%;
  bottom: 0.75rem;
  transform: translateX(-50%);
  border: 1px solid rgba(96, 165, 250, 0.42);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.92);
  padding: 0.35rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 700;
  color: #bfdbfe;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.34);
}
</style>
