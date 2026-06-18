<template>
  <div class="rcs-viewer space-y-4">
    <header class="space-y-1">
      <h2 class="text-xl font-bold text-gray-900 dark:text-gray-100">滚动章节摘要</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400">
        展示 Librarian 触发的滚动叙事摘要，每条覆盖一段章节范围
      </p>
    </header>

    <section
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
    >
      <div class="flex items-center gap-3" data-testid="rcs-viewer-summary">
        <span class="text-sm text-gray-500 dark:text-gray-400">摘要条数</span>
        <span
          class="text-2xl font-bold text-gray-900 dark:text-gray-100"
          data-testid="rcs-viewer-count"
        >
          {{ synopses.length }}
        </span>
        <el-button
          data-testid="rcs-viewer-refresh"
          type="primary"
          size="small"
          :loading="loading"
          @click="fetchSynopses"
        >
          刷新
        </el-button>
      </div>
    </section>

    <section
      v-loading="loading"
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
    >
      <el-skeleton v-if="loading && !hasData" :rows="6" animated />
      <div
        v-else-if="!hasData"
        class="rcs-viewer-empty"
        data-testid="synopsis-empty"
      >
        暂无滚动摘要，等待 Librarian 触发生成
      </div>
      <div v-else class="rcs-viewer-list space-y-3" data-testid="rcs-viewer-list">
        <article
          v-for="synopsis in synopses"
          :key="synopsis.id"
          class="rcs-viewer-card rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-4"
          :data-id="synopsis.id"
          data-testid="synopsis-card"
        >
          <header class="flex flex-wrap items-baseline gap-3">
            <h3
              class="text-lg font-semibold text-gray-900 dark:text-gray-100"
              data-testid="synopsis-range"
            >
              第 {{ formatRange(synopsis.chapter_range) }} 章
            </h3>
            <span
              v-if="synopsis.created_at"
              class="text-xs text-gray-500 dark:text-gray-400"
              data-testid="synopsis-created-at"
            >
              {{ formatDate(synopsis.created_at) }}
            </span>
          </header>

          <div
            class="rcs-viewer-prose mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-800 dark:text-gray-200"
            data-testid="synopsis-prose"
          >
            {{ synopsis.narrative_prose }}
          </div>

          <details class="rcs-viewer-details mt-3">
            <summary class="cursor-pointer text-xs text-gray-500 dark:text-gray-400">
              查看结构化字段
            </summary>
            <pre
              class="rcs-viewer-json mt-2 overflow-auto rounded bg-white dark:bg-gray-800 p-2 text-xs"
              data-testid="synopsis-structured"
            >{{ formatJson(synopsis.structured_json) }}</pre>
          </details>

          <details
            v-if="hasTrigger(synopsis)"
            class="rcs-viewer-details mt-2"
          >
            <summary class="cursor-pointer text-xs text-gray-500 dark:text-gray-400">
              查看触发事件
            </summary>
            <pre
              class="rcs-viewer-json mt-2 overflow-auto rounded bg-white dark:bg-gray-800 p-2 text-xs"
              data-testid="synopsis-trigger"
            >{{ formatJson(synopsis.trigger_event) }}</pre>
          </details>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getChapterSynopses } from '@/api.js'

const props = defineProps({
  novelId: { type: String, default: '' },
})

const synopses = ref([])
const loading = ref(false)
const errorMessage = ref('')

const hasData = computed(() => synopses.value.length > 0)

function formatRange(range) {
  if (!Array.isArray(range) || range.length < 2) return '?'
  const [start, end] = range
  if (start === end) return `${start}`
  return `${start} - ${end}`
}

function formatDate(value) {
  if (!value) return ''
  try {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleString()
  } catch (e) {
    return value
  }
}

function formatJson(value) {
  if (value == null) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch (e) {
    return String(value)
  }
}

function hasTrigger(synopsis) {
  const trigger = synopsis?.trigger_event
  if (!trigger) return false
  if (Array.isArray(trigger)) return trigger.length > 0
  if (typeof trigger === 'object') return Object.keys(trigger).length > 0
  return Boolean(trigger)
}

async function fetchSynopses() {
  if (!props.novelId) {
    synopses.value = []
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await getChapterSynopses(props.novelId)
    const list = Array.isArray(response?.synopses) ? response.synopses : []
    synopses.value = [...list].sort((a, b) => {
      const aStart = Array.isArray(a.chapter_range) ? a.chapter_range[0] : 0
      const bStart = Array.isArray(b.chapter_range) ? b.chapter_range[0] : 0
      return aStart - bStart
    })
  } catch (error) {
    synopses.value = []
    const detail = error?.response?.data?.detail
    errorMessage.value = detail || error?.message || '滚动摘要加载失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.novelId,
  () => {
    void fetchSynopses()
  },
)

onMounted(() => {
  void fetchSynopses()
})

defineExpose({ fetchSynopses })
</script>

<style scoped>
.rcs-viewer-empty {
  align-items: center;
  border: 1px dashed var(--app-border);
  border-radius: 0.75rem;
  color: var(--app-text-muted);
  display: flex;
  font-size: 0.9rem;
  justify-content: center;
  min-height: 200px;
  padding: 1.5rem;
}

.rcs-viewer-card {
  transition: box-shadow 0.15s ease;
}

.rcs-viewer-card:hover {
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}

.rcs-viewer-prose {
  max-width: 64rem;
}

.rcs-viewer-json {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  max-height: 18rem;
}
</style>