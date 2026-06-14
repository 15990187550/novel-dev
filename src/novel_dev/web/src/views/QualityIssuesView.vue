<template>
  <div class="quality-issues-view space-y-4">
    <header class="space-y-1">
      <h2 class="text-xl font-bold text-gray-900 dark:text-gray-100">质量问题聚合</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400">展示跨章节的重复质量问题（按提示阈值过滤）</p>
    </header>

    <section class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm">
      <div class="flex flex-wrap items-end gap-3" data-testid="quality-issues-filters">
        <label class="flex flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
          <span>阶段</span>
          <el-select
            v-model="phase"
            data-testid="quality-issues-phase"
            size="small"
            style="width: 140px"
            @change="handleRefresh"
          >
            <el-option
              v-for="option in phaseOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </label>
        <label class="flex flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
          <span>起始章节</span>
          <el-input-number
            v-model="fromChapter"
            data-testid="quality-issues-from"
            :min="1"
            size="small"
            controls-position="right"
            style="width: 140px"
            @change="handleRefresh"
          />
        </label>
        <label class="flex flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
          <span>结束章节</span>
          <el-input-number
            v-model="toChapter"
            data-testid="quality-issues-to"
            :min="1"
            size="small"
            controls-position="right"
            style="width: 140px"
            @change="handleRefresh"
          />
        </label>
        <label class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <el-switch
            v-model="onlyMatched"
            data-testid="quality-issues-only-matched"
            size="small"
            @change="handleRefresh"
          />
          <span>仅显示已触发提示</span>
        </label>
        <el-button
          data-testid="quality-issues-refresh"
          type="primary"
          :loading="loading"
          @click="handleRefresh"
        >
          刷新
        </el-button>
      </div>
    </section>

    <section
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
    >
      <div class="flex items-center gap-3" data-testid="quality-issues-summary">
        <span class="text-sm text-gray-500 dark:text-gray-400">扫描章节数</span>
        <span class="text-2xl font-bold text-gray-900 dark:text-gray-100" data-testid="quality-issues-total-chapters">
          {{ totalChapters }}
        </span>
        <span class="text-xs text-gray-400 dark:text-gray-500">总提示数 {{ allHints.length }}</span>
      </div>
    </section>

    <section
      v-loading="loading"
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
    >
      <el-skeleton v-if="loading && !hasData" :rows="6" animated />
      <div
        v-else-if="!hasData"
        class="quality-issues-empty"
        data-testid="quality-issues-empty"
      >
        暂无质量问题
      </div>
      <el-table
        v-else
        :data="visibleHints"
        :row-class-name="rowClassName"
        :default-sort="{ prop: 'occurrences', order: 'descending' }"
        class="quality-issues-table"
        data-testid="quality-issues-table"
        stripe
      >
        <el-table-column
          prop="code"
          label="错误码"
          min-width="160"
          data-testid="quality-issues-col-code"
        >
          <template #default="{ row }">
            <code class="quality-issues-code">{{ row.code }}</code>
          </template>
        </el-table-column>
        <el-table-column
          prop="severity"
          label="严重程度"
          min-width="120"
          data-testid="quality-issues-col-severity"
        >
          <template #default="{ row }">
            <el-tag
              :type="severityTagType(row.severity)"
              size="small"
              effect="light"
            >
              {{ severityLabel(row.severity) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          prop="occurrences"
          label="触发次数"
          min-width="110"
          sortable
          data-testid="quality-issues-col-occurrences"
        >
          <template #default="{ row }">
            <span class="font-semibold">{{ row.occurrences ?? 0 }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="threshold"
          label="阈值"
          min-width="90"
          data-testid="quality-issues-col-threshold"
        >
          <template #default="{ row }">
            <span class="text-gray-500 dark:text-gray-400">{{ row.threshold ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="hint"
          label="提示"
          min-width="280"
          data-testid="quality-issues-col-hint"
        >
          <template #default="{ row }">
            <span class="quality-issues-hint">{{ row.hint }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="matches"
          label="状态"
          min-width="110"
          data-testid="quality-issues-col-matches"
        >
          <template #default="{ row }">
            <el-tag
              :type="row.matches ? 'danger' : 'info'"
              size="small"
              effect="plain"
            >
              {{ row.matches ? '已触发' : '未触发' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getQualityIssues } from '@/api.js'

const props = defineProps({
  novelId: { type: String, default: '' },
})

const phaseOptions = [
  { value: 'final', label: '最终' },
  { value: 'draft', label: '草稿' },
]

const phase = ref('final')
const fromChapter = ref(null)
const toChapter = ref(null)
const onlyMatched = ref(true)
const loading = ref(false)
const errorMessage = ref('')
const allHints = ref([])
const totalChapters = ref(0)

const severityLabel = {
  info: '提示',
  warn: '告警',
  block: '阻断',
  manual_review: '需人工',
}

const severityTagType = (severity) => {
  if (severity === 'block' || severity === 'manual_review') return 'danger'
  if (severity === 'warn') return 'warning'
  return 'info'
}

const visibleHints = computed(() => {
  if (!onlyMatched.value) return allHints.value
  return allHints.value.filter((hint) => hint.matches === true)
})

const hasData = computed(() => visibleHints.value.length > 0)

function rowClassName({ row }) {
  if (row?.matches === true) return 'quality-issues-row--matched'
  return ''
}

async function fetchIssues() {
  if (!props.novelId) {
    allHints.value = []
    totalChapters.value = 0
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const params = { phase: phase.value }
    if (fromChapter.value) params.from_chapter = fromChapter.value
    if (toChapter.value) params.to_chapter = toChapter.value
    const response = await getQualityIssues(props.novelId, params)
    const hints = Array.isArray(response?.hints) ? response.hints : []
    allHints.value = [...hints].sort((a, b) => (b.occurrences ?? 0) - (a.occurrences ?? 0))
    totalChapters.value = Number(response?.total_chapters ?? 0)
  } catch (error) {
    allHints.value = []
    totalChapters.value = 0
    const detail = error?.response?.data?.detail
    errorMessage.value = detail || error?.message || '质量问题加载失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

function handleRefresh() {
  void fetchIssues()
}

watch(
  () => props.novelId,
  () => {
    handleRefresh()
  },
)

onMounted(() => {
  handleRefresh()
})

defineExpose({ fetchIssues })
</script>

<style scoped>
.quality-issues-empty {
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

.quality-issues-table {
  width: 100%;
}

.quality-issues-code {
  background: rgba(148, 163, 184, 0.15);
  border-radius: 0.25rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
  padding: 0.1rem 0.35rem;
}

.quality-issues-hint {
  color: var(--app-text-muted);
  display: inline-block;
  line-height: 1.4;
  max-width: 36rem;
}

:deep(.quality-issues-row--matched td:first-child) {
  border-left: 3px solid #ef4444;
}
</style>
