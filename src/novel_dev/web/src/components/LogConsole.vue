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
          :key="logKey(log, i)"
          class="log-console__entry rounded px-1 hover:bg-gray-900/50"
          :data-testid="`log-line-${i}`"
        >
          <div class="flex gap-2">
            <span class="text-gray-500 shrink-0">{{ formatTime(log.timestamp) }}</span>
            <span class="shrink-0 font-semibold" :style="{ color: agentColor(log.agent) }">[{{ log.agent }}]</span>
            <span v-if="log.level" class="shrink-0 rounded border px-1 text-[11px]" :class="levelClass(log.level)">{{ log.level }}</span>
            <span v-if="log.status" class="shrink-0 rounded border border-sky-800/70 bg-sky-950/60 px-1 text-[11px] text-sky-200">{{ log.status }}</span>
            <span v-if="log.node" class="shrink-0 rounded border border-gray-700 bg-gray-900 px-1 text-[11px] text-gray-300">{{ log.node }}</span>
            <span class="min-w-0 flex-1 text-gray-300">{{ log.message }}</span>
            <button
              v-if="hasMetadata(log)"
              type="button"
              class="log-console__details-toggle shrink-0"
              :data-testid="`log-details-toggle-${i}`"
              @click="toggleDetails(logKey(log, i))"
            >
              {{ expandedDetails.has(logKey(log, i)) ? '收起' : '详情' }}
            </button>
          </div>
          <pre
            v-if="hasMetadata(log) && expandedDetails.has(logKey(log, i))"
            class="log-console__details"
            :data-testid="`log-details-${i}`"
          >{{ formatMetadata(log.metadata) }}</pre>
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
const expandedDetails = ref(new Set())
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
function logKey(log, index) {
  return `${log.timestamp || ''}:${log.agent || ''}:${log.node || ''}:${log.task || ''}:${index}`
}
function hasMetadata(log) {
  if (!log || log.metadata == null) return false
  if (Array.isArray(log.metadata)) return log.metadata.length > 0
  if (typeof log.metadata === 'object') return Object.keys(log.metadata).length > 0
  return true
}
function formatMetadata(metadata) {
  if (typeof metadata === 'string') return metadata
  return JSON.stringify(metadata, null, 2)
}
function toggleDetails(key) {
  const next = new Set(expandedDetails.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedDetails.value = next
}
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

.log-console__entry {
  min-width: 0;
}

.log-console__details-toggle {
  border: 1px solid rgba(75, 85, 99, 0.8);
  border-radius: 4px;
  background: rgba(17, 24, 39, 0.96);
  padding: 0 0.35rem;
  font-size: 0.6875rem;
  line-height: 1.25rem;
  color: #bfdbfe;
}

.log-console__details {
  margin: 0.25rem 0 0.35rem 5.5rem;
  max-height: 18rem;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border-left: 2px solid rgba(96, 165, 250, 0.45);
  background: rgba(3, 7, 18, 0.72);
  padding: 0.5rem 0.65rem;
  color: #cbd5e1;
  font-size: 0.75rem;
  line-height: 1.45;
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
