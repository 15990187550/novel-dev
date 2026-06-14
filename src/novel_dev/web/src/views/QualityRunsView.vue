<template>
  <div class="quality-runs-view space-y-4">
    <header class="space-y-1">
      <h2 class="text-xl font-bold text-gray-900 dark:text-gray-100">质量运行历史</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400">展示各章节每次质量评估的完整记录（用于排查失败原因）</p>
    </header>

    <section class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm">
      <div class="flex flex-wrap items-end gap-3" data-testid="quality-runs-filters">
        <label class="flex flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
          <span>章节 ID</span>
          <el-input
            v-model="chapterId"
            data-testid="quality-runs-chapter-id"
            size="small"
            placeholder="如 ch-001"
            clearable
            style="width: 180px"
            @change="handleRefresh"
            @clear="handleRefresh"
          />
        </label>
        <label class="flex flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
          <span>阶段</span>
          <el-select
            v-model="phase"
            data-testid="quality-runs-phase"
            size="small"
            style="width: 140px"
            clearable
            placeholder="全部"
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
          <span>返回条数</span>
          <el-input-number
            v-model="limit"
            data-testid="quality-runs-limit"
            :min="1"
            :max="200"
            size="small"
            controls-position="right"
            style="width: 120px"
            @change="handleRefresh"
          />
        </label>
        <el-button
          data-testid="quality-runs-refresh"
          type="primary"
          :loading="loading"
          @click="handleRefresh"
        >
          刷新
        </el-button>
        <el-button
          v-if="hasData"
          data-testid="quality-runs-load-more"
          :disabled="loading"
          @click="handleLoadMore"
        >
          加载更多
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
        class="quality-runs-empty"
        data-testid="quality-runs-empty"
      >
        暂无质量运行记录
      </div>
      <el-table
        v-else
        :data="runs"
        class="quality-runs-table"
        data-testid="quality-runs-table"
        stripe
        row-key="id"
      >
        <el-table-column type="expand" data-testid="quality-runs-col-expand">
          <template #default="{ row }">
            <div class="quality-runs-expanded" :data-run-id="row.id">
              <div class="quality-runs-expanded-section">
                <h4 class="quality-runs-expanded-title">阻断项</h4>
                <pre class="quality-runs-json" data-testid="quality-runs-blocking">{{ formatJson(row.blocking_items) }}</pre>
              </div>
              <div class="quality-runs-expanded-section">
                <h4 class="quality-runs-expanded-title">告警项</h4>
                <pre class="quality-runs-json" data-testid="quality-runs-warnings">{{ formatJson(row.warning_items) }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column
          prop="created_at"
          label="时间"
          min-width="180"
          data-testid="quality-runs-col-time"
        >
          <template #default="{ row }">
            <span class="quality-runs-mono">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="chapter_id"
          label="章节"
          min-width="120"
          data-testid="quality-runs-col-chapter"
        >
          <template #default="{ row }">
            <code class="quality-runs-code">{{ row.chapter_id || '-' }}</code>
          </template>
        </el-table-column>
        <el-table-column
          prop="phase"
          label="阶段"
          min-width="90"
          data-testid="quality-runs-col-phase"
        >
          <template #default="{ row }">
            <span>{{ phaseLabel(row.phase) }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="attempt_index"
          label="尝试"
          min-width="80"
          data-testid="quality-runs-col-attempt"
        >
          <template #default="{ row }">
            <span class="font-semibold">{{ row.attempt_index ?? 0 }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="overall_score"
          label="评分"
          min-width="90"
          data-testid="quality-runs-col-score"
        >
          <template #default="{ row }">
            <span class="font-semibold">{{ row.overall_score ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="gate_status"
          label="门状态"
          min-width="110"
          data-testid="quality-runs-col-gate"
        >
          <template #default="{ row }">
            <el-tag
              :type="gateTagType(row.gate_status)"
              size="small"
              effect="light"
            >
              {{ gateLabel(row.gate_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          prop="issue_codes"
          label="问题码"
          min-width="200"
          data-testid="quality-runs-col-issues"
        >
          <template #default="{ row }">
            <div class="quality-runs-codes" v-if="Array.isArray(row.issue_codes) && row.issue_codes.length">
              <el-tag
                v-for="code in row.issue_codes"
                :key="code"
                size="small"
                type="warning"
                effect="plain"
                class="quality-runs-code-tag"
              >
                {{ code }}
              </el-tag>
            </div>
            <span v-else class="text-gray-400 dark:text-gray-500">-</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="model_version"
          label="模型"
          min-width="180"
          data-testid="quality-runs-col-model"
        >
          <template #default="{ row }">
            <div class="quality-runs-model">
              <code class="quality-runs-code">{{ row.model_version || '-' }}</code>
              <span class="quality-runs-prompt" v-if="row.prompt_version">提示 {{ row.prompt_version }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column
          prop="latency_ms"
          label="耗时"
          min-width="100"
          data-testid="quality-runs-col-latency"
        >
          <template #default="{ row }">
            <span class="quality-runs-mono">{{ formatLatency(row.latency_ms) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getQualityRuns } from '@/api.js'

const props = defineProps({
  novelId: { type: String, default: '' },
})

const phaseOptions = [
  { value: 'final', label: '最终' },
  { value: 'draft', label: '草稿' },
  { value: 'editor', label: '编辑' },
  { value: 'fast_review', label: '快速复核' },
]

const phaseLabels = {
  final: '最终',
  draft: '草稿',
  editor: '编辑',
  fast_review: '快速复核',
}

const gateLabels = {
  pass: '通过',
  warn: '告警',
  block: '阻断',
  unchecked: '未检查',
  manual_review_required: '待人工',
}

const gateTagTypes = {
  pass: 'success',
  warn: 'warning',
  block: 'danger',
  unchecked: 'info',
  manual_review_required: 'warning',
}

const chapterId = ref('')
const phase = ref('')
const limit = ref(50)
const loading = ref(false)
const errorMessage = ref('')
const runs = ref([])

const hasData = computed(() => Array.isArray(runs.value) && runs.value.length > 0)

function gateLabel(status) {
  return gateLabels[status] || status || '-'
}

function gateTagType(status) {
  return gateTagTypes[status] || 'info'
}

function phaseLabel(value) {
  return phaseLabels[value] || value || '-'
}

function formatTime(value) {
  if (!value) return '-'
  try {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z')
  } catch {
    return value
  }
}

function formatLatency(ms) {
  if (ms == null) return '-'
  const seconds = Number(ms) / 1000
  if (Number.isNaN(seconds)) return '-'
  if (seconds < 10) return `${seconds.toFixed(2)}s`
  return `${seconds.toFixed(1)}s`
}

function formatJson(value) {
  if (value == null) return '[]'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

async function fetchRuns({ append = false } = {}) {
  if (!props.novelId) {
    runs.value = []
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const params = { limit: limit.value }
    if (chapterId.value) params.chapter_id = chapterId.value.trim()
    if (phase.value) params.phase = phase.value
    const response = await getQualityRuns(props.novelId, params)
    const fetched = Array.isArray(response?.runs) ? response.runs : []
    runs.value = append ? [...runs.value, ...fetched] : fetched
  } catch (error) {
    if (!append) runs.value = []
    const detail = error?.response?.data?.detail
    errorMessage.value = detail || error?.message || '质量运行历史加载失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

function handleRefresh() {
  void fetchRuns({ append: false })
}

function handleLoadMore() {
  void fetchRuns({ append: true })
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

defineExpose({ fetchRuns })
</script>

<style scoped>
.quality-runs-empty {
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

.quality-runs-table {
  width: 100%;
}

.quality-runs-code {
  background: rgba(148, 163, 184, 0.15);
  border-radius: 0.25rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
  padding: 0.1rem 0.35rem;
}

.quality-runs-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
}

.quality-runs-codes {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.quality-runs-code-tag {
  margin: 0;
}

.quality-runs-model {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.quality-runs-prompt {
  color: var(--app-text-muted);
  font-size: 0.75rem;
}

.quality-runs-expanded {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: 1fr 1fr;
  padding: 0.75rem 1.5rem;
}

.quality-runs-expanded-section {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.quality-runs-expanded-title {
  color: var(--app-text-muted);
  font-size: 0.8rem;
  font-weight: 600;
  margin: 0;
}

.quality-runs-json {
  background: rgba(148, 163, 184, 0.1);
  border-radius: 0.375rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.75rem;
  margin: 0;
  max-height: 240px;
  overflow: auto;
  padding: 0.5rem 0.75rem;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 768px) {
  .quality-runs-expanded {
    grid-template-columns: 1fr;
  }
}
</style>
