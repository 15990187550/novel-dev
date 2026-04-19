<template>
  <div class="flex flex-col h-full bg-gray-950 text-gray-100 rounded-lg overflow-hidden font-mono text-sm">
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
    <div ref="logContainer" class="flex-1 overflow-y-auto p-2 space-y-0.5" @scroll="onScroll">
      <div v-for="(log, i) in visibleLogs" :key="i" class="flex gap-2 hover:bg-gray-900/50 px-1 rounded">
        <span class="text-gray-500 shrink-0">{{ formatTime(log.timestamp) }}</span>
        <span class="shrink-0 font-semibold" :style="{ color: agentColor(log.agent) }">[{{ log.agent }}]</span>
        <span class="text-gray-300">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps({ logs: { type: Array, default: () => [] }, connected: { type: Boolean, default: false } })
const emit = defineEmits(['clear'])

const paused = ref(false)
const filters = ref(new Set())
const logContainer = ref(null)
const autoScroll = ref(true)

const colors = { NovelDirector: '#9ca3af', VolumePlannerAgent: '#60a5fa', WriterAgent: '#4ade80', CriticAgent: '#fb923c', EditorAgent: '#c084fc', FastReviewAgent: '#facc15', LibrarianAgent: '#f472b6', ContextAgent: '#2dd4bf' }

const allAgents = computed(() => Array.from(new Set(props.logs.map(l => l.agent))).sort())
const visibleLogs = computed(() => filters.value.size === 0 ? props.logs : props.logs.filter(l => filters.value.has(l.agent)))

function isFiltered(agent) { return filters.value.size === 0 || filters.value.has(agent) }
function toggleFilter(agent) { filters.value.has(agent) ? filters.value.delete(agent) : filters.value.add(agent) }
function agentColor(agent) { return colors[agent] || '#9ca3af' }
function formatTime(ts) { return ts ? new Date(ts).toLocaleTimeString('zh-CN', { hour12: false }) : '' }
function onScroll() {
  const el = logContainer.value
  if (el) autoScroll.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 20
}

watch(() => props.logs.length, async () => {
  if (paused.value || !autoScroll.value) return
  await nextTick()
  logContainer.value?.scrollTo({ top: logContainer.value.scrollHeight, behavior: 'smooth' })
})
</script>
