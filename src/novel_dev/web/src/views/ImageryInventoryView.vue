<template>
  <div class="imagery-inventory space-y-4">
    <header class="space-y-1">
      <h2 class="text-xl font-bold text-gray-900 dark:text-gray-100">跨章意象清单</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400">
        展示 Librarian 提取的跨章意象使用情况,帮助识别重复与可避免的描写。
      </p>
    </header>

    <section
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
    >
      <div class="flex flex-wrap items-center gap-3">
        <span class="text-sm text-gray-500 dark:text-gray-400">意象条数</span>
        <span
          class="text-2xl font-bold text-gray-900 dark:text-gray-100"
          data-testid="imagery-count"
        >
          {{ items.length }}
        </span>
        <span class="text-sm text-gray-500 dark:text-gray-400">聚合意象数</span>
        <span
          class="text-2xl font-bold text-gray-900 dark:text-gray-100"
          data-testid="imagery-aggregate-count"
        >
          {{ aggregates.length }}
        </span>
        <el-select
          v-model="windowSize"
          size="small"
          class="imagery-window-select"
          data-testid="imagery-window-select"
          @change="onWindowChange"
        >
          <el-option :value="5" label="最近 5 章" />
          <el-option :value="10" label="最近 10 章" />
          <el-option :value="20" label="最近 20 章" />
        </el-select>
        <el-button
          data-testid="imagery-refresh"
          type="primary"
          size="small"
          :loading="loading"
          @click="fetchInventory"
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
        class="imagery-inventory-empty"
        data-testid="imagery-empty"
      >
        暂无意象记录,等待 Librarian 提取。
      </div>
      <div v-else class="space-y-6" data-testid="imagery-content">
        <div data-testid="imagery-aggregates">
          <h3
            class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-2"
          >
            跨章聚合(按意象文本聚合)
          </h3>
          <ul class="space-y-2">
            <li
              v-for="agg in aggregates"
              :key="agg.item"
              class="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3"
              data-testid="imagery-aggregate-row"
              :data-item="agg.item"
            >
              <div class="flex flex-wrap items-baseline gap-3">
                <span
                  class="text-base font-semibold text-gray-900 dark:text-gray-100"
                  data-testid="imagery-aggregate-item"
                >
                  {{ agg.item }}
                </span>
                <span
                  class="text-xs text-gray-500 dark:text-gray-400"
                  data-testid="imagery-aggregate-type"
                >
                  {{ formatType(agg.item_type) }}
                </span>
                <span
                  class="text-xs text-gray-500 dark:text-gray-400"
                  data-testid="imagery-aggregate-chapter-count"
                >
                  {{ agg.chapter_count }} 章
                </span>
                <span
                  class="text-xs text-gray-500 dark:text-gray-400"
                  data-testid="imagery-aggregate-frequency"
                >
                  累计 {{ agg.total_frequency }} 次
                </span>
              </div>
            </li>
          </ul>
        </div>

        <div data-testid="imagery-raw-list">
          <h3
            class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-2"
          >
            原始记录
          </h3>
          <ul class="space-y-2">
            <li
              v-for="(row, idx) in items"
              :key="`${row.chapter_id}-${row.item}-${idx}`"
              class="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3"
              data-testid="imagery-row"
              :data-item="row.item"
              :data-chapter="row.chapter_id"
            >
              <div class="flex flex-wrap items-baseline gap-3">
                <span
                  class="text-base font-semibold text-gray-900 dark:text-gray-100"
                  data-testid="imagery-row-item"
                >
                  {{ row.item }}
                </span>
                <span
                  class="text-xs text-gray-500 dark:text-gray-400"
                  data-testid="imagery-row-type"
                >
                  {{ formatType(row.item_type) }}
                </span>
                <span
                  class="text-xs text-gray-500 dark:text-gray-400"
                  data-testid="imagery-row-chapter"
                >
                  {{ formatChapter(row.chapter_id) }}
                </span>
                <span
                  class="text-xs text-gray-500 dark:text-gray-400"
                  data-testid="imagery-row-frequency"
                >
                  本章出现 {{ row.frequency_in_chapter }} 次
                </span>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getImageryInventory } from '@/api.js'

const props = defineProps({
  novelId: { type: String, default: '' },
})

const items = ref([])
const windowSize = ref(5)
const loading = ref(false)
const errorMessage = ref('')

const hasData = computed(() => items.value.length > 0)

const TYPE_LABELS = {
  nature: '自然',
  action: '动作',
  emotion: '情感',
  setting: '场景',
  object: '物品',
  metaphor: '隐喻',
  character: '人物',
  sound: '声音',
  color: '色彩',
  abstract: '抽象',
}

function formatType(itemType) {
  if (!itemType) return '未分类'
  const key = String(itemType).toLowerCase()
  return TYPE_LABELS[key] || itemType
}

function formatChapter(chapterId) {
  if (!chapterId) return '未知章节'
  const match = String(chapterId).match(/(\d+)/)
  if (match) return `第 ${match[1]} 章`
  return chapterId
}

const aggregates = computed(() => {
  const map = new Map()
  for (const row of items.value) {
    const key = `${row.item}__${row.item_type}`
    const existing = map.get(key)
    if (existing) {
      existing.chapter_ids.add(row.chapter_id)
      existing.total_frequency += Number(row.frequency_in_chapter || 0)
    } else {
      map.set(key, {
        item: row.item,
        item_type: row.item_type,
        chapter_ids: new Set([row.chapter_id]),
        total_frequency: Number(row.frequency_in_chapter || 0),
      })
    }
  }
  return Array.from(map.values())
    .map((agg) => ({
      item: agg.item,
      item_type: agg.item_type,
      chapter_count: agg.chapter_ids.size,
      total_frequency: agg.total_frequency,
    }))
    .sort((a, b) => {
      if (b.chapter_count !== a.chapter_count) {
        return b.chapter_count - a.chapter_count
      }
      return b.total_frequency - a.total_frequency
    })
})

async function fetchInventory() {
  if (!props.novelId) {
    items.value = []
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await getImageryInventory(props.novelId, windowSize.value)
    const list = Array.isArray(response?.items) ? response.items : []
    items.value = list
  } catch (error) {
    items.value = []
    const detail = error?.response?.data?.detail
    errorMessage.value = detail || error?.message || '意象清单加载失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

function onWindowChange() {
  void fetchInventory()
}

watch(
  () => props.novelId,
  () => {
    void fetchInventory()
  },
)

onMounted(() => {
  void fetchInventory()
})

defineExpose({ fetchInventory })
</script>

<style scoped>
.imagery-inventory-empty {
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

.imagery-window-select {
  min-width: 8rem;
}
</style>