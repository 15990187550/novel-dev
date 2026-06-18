<template>
  <div class="quality-trends-view space-y-4">
    <header class="space-y-1">
      <h2 class="text-xl font-bold text-gray-900 dark:text-gray-100">章节质量趋势</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400">按章节号展示评分与质量门状态</p>
    </header>

    <section class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm">
      <div class="flex flex-wrap items-end gap-3" data-testid="quality-trends-filters">
        <label class="flex flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
          <span>维度</span>
          <el-select
            v-model="dimension"
            data-testid="quality-trends-dimension"
            size="small"
            style="width: 160px"
            @change="handleRefresh"
          >
            <el-option
              v-for="option in dimensionOptions"
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
            data-testid="quality-trends-from"
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
            data-testid="quality-trends-to"
            :min="1"
            size="small"
            controls-position="right"
            style="width: 140px"
            @change="handleRefresh"
          />
        </label>
        <el-button
          data-testid="quality-trends-refresh"
          type="primary"
          :loading="loading"
          @click="handleRefresh"
        >
          刷新
        </el-button>
        <div class="ml-auto flex flex-wrap items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
          <span class="legend-item legend-item--pass" />
          <span>通过 (≥82)</span>
          <span class="legend-item legend-item--warn" />
          <span>告警</span>
          <span class="legend-item legend-item--block" />
          <span>阻断 (&lt;75)</span>
          <span class="legend-item legend-item--unchecked" />
          <span>未检查</span>
        </div>
      </div>
    </section>

    <section
      v-loading="loading"
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
    >
      <el-skeleton v-if="loading && !hasData" :rows="6" animated />
      <div
        v-else-if="!hasData"
        class="quality-trends-empty"
        data-testid="quality-trends-empty"
      >
        暂无质量数据
      </div>
      <v-chart
        v-else
        class="quality-trends-chart"
        :option="chartOption"
        data-testid="quality-trends-chart"
        autoresize
      />
    </section>

    <section
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
      data-testid="thrills-achievement"
    >
      <header class="mb-3 flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">爽点达成率</h3>
        <span class="text-xs text-gray-500 dark:text-gray-400">规划 vs FastReview 验证</span>
      </header>
      <div v-if="thrillsSummary" class="grid grid-cols-3 gap-4 text-center">
        <div>
          <div class="text-2xl font-bold text-gray-900 dark:text-gray-100" data-testid="thrills-planned">
            {{ thrillsSummary.planned }}
          </div>
          <div class="text-xs text-gray-500 dark:text-gray-400">规划爽点</div>
        </div>
        <div>
          <div class="text-2xl font-bold text-green-600" data-testid="thrills-verified">
            {{ thrillsSummary.verified }}
          </div>
          <div class="text-xs text-gray-500 dark:text-gray-400">已验证</div>
        </div>
        <div>
          <div class="text-2xl font-bold text-blue-600" data-testid="thrills-rate">
            {{ formatRate(thrillsSummary.rate) }}
          </div>
          <div class="text-xs text-gray-500 dark:text-gray-400">达成率</div>
        </div>
      </div>
      <div v-else class="text-sm text-gray-500 dark:text-gray-400" data-testid="thrills-achievement-empty">
        暂无爽点数据
      </div>
    </section>

    <section
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
      data-testid="imagery-top5"
    >
      <header class="mb-3 flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">跨章意象 top 5</h3>
        <span class="text-xs text-gray-500 dark:text-gray-400">最近 {{ window }} 章</span>
      </header>
      <div v-if="imageryTop5.length === 0" class="text-sm text-gray-500 dark:text-gray-400" data-testid="imagery-top5-empty">
        暂无跨章意象数据
      </div>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs text-gray-500 dark:text-gray-400">
            <th class="py-1">意象</th>
            <th class="py-1">类型</th>
            <th class="py-1 text-right">出现章数</th>
            <th class="py-1 text-right">频次合计</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, idx) in imageryTop5"
            :key="`${row.item}-${idx}`"
            class="border-t border-gray-100 dark:border-gray-700"
            :data-testid="`imagery-top5-row-${idx}`"
          >
            <td class="py-1 text-gray-900 dark:text-gray-100">{{ row.item }}</td>
            <td class="py-1 text-gray-700 dark:text-gray-300">{{ row.type }}</td>
            <td class="py-1 text-right text-gray-700 dark:text-gray-300">{{ row.chapter_count }}</td>
            <td class="py-1 text-right text-gray-700 dark:text-gray-300">{{ row.freq_sum }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section
      class="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 shadow-sm"
      data-testid="hook-achievement"
    >
      <header class="mb-3 flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">钩子达成趋势</h3>
        <span class="text-xs text-gray-500 dark:text-gray-400">章末 hook_strength 维度</span>
      </header>
      <div
        v-if="hookTrendStatus === 'unavailable'"
        class="text-sm text-gray-500 dark:text-gray-400"
        data-testid="hook-achievement-empty"
      >
        数据尚未收集 (待 FastReview 钩子验证落库后展示)
      </div>
      <div v-else-if="hookTrend.length === 0" class="text-sm text-gray-500 dark:text-gray-400" data-testid="hook-achievement-empty">
        暂无钩子评分
      </div>
      <ul v-else class="space-y-1 text-sm">
        <li
          v-for="(row, idx) in hookTrend"
          :key="`${row.chapter_id}-${idx}`"
          class="flex items-center justify-between"
          :data-testid="`hook-achievement-row-${idx}`"
        >
          <span class="text-gray-700 dark:text-gray-300">第{{ row.chapter_number }}章</span>
          <span class="font-mono text-gray-900 dark:text-gray-100">{{ row.value ?? '-' }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { getQualityTrends, getQualityTrendsV2 } from '@/api.js'

use([
  CanvasRenderer,
  LineChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
])

const props = defineProps({
  novelId: { type: String, default: '' },
})

const dimensionOptions = [
  { value: 'overall', label: '综合' },
  { value: 'plot_tension', label: '情节张力' },
  { value: 'characterization', label: '人物塑造' },
  { value: 'readability', label: '可读性' },
  { value: 'consistency', label: '一致性' },
  { value: 'humanity', label: '沉浸感' },
  { value: 'hook_strength', label: '章末钩子' },
]

const dimension = ref('overall')
const fromChapter = ref(null)
const toChapter = ref(null)
const window = ref(20)
const loading = ref(false)
const errorMessage = ref('')
const points = ref([])

// V2 cross-metric aggregation state
const thrillsSummary = ref(null) // { planned, verified, rate } | null
const imageryTop5 = ref([]) // [{ item, type, chapter_count, freq_sum }]
const hookTrend = ref([]) // [{ chapter_id, chapter_number, value, source }]
const hookTrendStatus = ref('unavailable') // 'unavailable' | 'ready'

const gateStatusColor = {
  pass: '#22c55e',
  warn: '#f59e0b',
  block: '#ef4444',
  unchecked: '#9ca3af',
  manual_review_required: '#f59e0b',
}

const gateStatusLabel = {
  pass: '通过',
  warn: '告警',
  block: '阻断',
  unchecked: '未检查',
  manual_review_required: '待人工确认',
}

const hasData = computed(() => Array.isArray(points.value) && points.value.length > 0)

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]))
}

function formatIssueCodes(codes) {
  if (!Array.isArray(codes) || !codes.length) return ''
  return `问题码: ${codes.join(', ')}`
}

function buildTooltip(point) {
  const lines = [
    `第${point.chapter_number}章 ${point.title || ''}`.trim(),
    `评分: ${point.value ?? '-'}`,
    `门状态: ${gateStatusLabel[point.gate_status] || point.gate_status || '-'}`,
    `来源: ${point.source === 'chapter_fallback' ? '章节回退' : '指标'}`,
    formatIssueCodes(point.issue_codes),
  ].filter(Boolean)
  return lines.map((line) => `<div>${escapeHtml(line)}</div>`).join('')
}

const chartOption = computed(() => {
  const data = points.value
  const cats = data.map((p) => p.chapter_number)
  const seriesData = data.map((p) => ({
    value: [p.chapter_number, p.value ?? null, p],
    itemStyle: { color: gateStatusColor[p.gate_status] || '#9ca3af' },
  }))

  return {
    tooltip: {
      trigger: 'axis',
      appendToBody: true,
      formatter: (params) => {
        const entry = params?.[0]
        const point = entry?.data?.[2]
        if (!point) return ''
        return buildTooltip(point)
      },
    },
    grid: { top: 32, bottom: 36, left: 48, right: 24 },
    xAxis: {
      type: 'category',
      name: '章节',
      nameLocation: 'middle',
      nameGap: 24,
      data: cats,
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      name: '评分',
      min: 0,
      max: 100,
    },
    series: [
      {
        type: 'line',
        smooth: false,
        symbol: 'circle',
        symbolSize: 12,
        data: seriesData,
        lineStyle: { color: '#3b82f6', width: 2 },
        itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { type: 'dashed', width: 1 },
          label: { position: 'end' },
          data: [
            { yAxis: 82, lineStyle: { color: '#22c55e' }, label: { formatter: '可发布 82' } },
            { yAxis: 75, lineStyle: { color: '#ef4444' }, label: { formatter: '阻断 75' } },
          ],
        },
      },
    ],
  }
})

async function fetchTrends() {
  if (!props.novelId) {
    points.value = []
    resetV2State()
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const params = { dimension: dimension.value, phase: 'final' }
    if (fromChapter.value) params.from_chapter = fromChapter.value
    if (toChapter.value) params.to_chapter = toChapter.value
    const response = await getQualityTrends(props.novelId, params)
    points.value = Array.isArray(response?.points) ? response.points : []
    await fetchV2()
  } catch (error) {
    points.value = []
    resetV2State()
    const detail = error?.response?.data?.detail
    errorMessage.value = detail || error?.message || '质量趋势加载失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

async function fetchV2() {
  if (!props.novelId) {
    resetV2State()
    return
  }
  try {
    const params = { window: window.value, dimension: dimension.value, phase: 'final' }
    if (fromChapter.value) params.from_chapter = fromChapter.value
    if (toChapter.value) params.to_chapter = toChapter.value
    const response = await getQualityTrendsV2(props.novelId, params)
    thrillsSummary.value = {
      planned: Number(response?.thrills_planned ?? 0),
      verified: Number(response?.thrills_verified ?? 0),
      rate: Number(response?.thrills_achievement_rate ?? 0),
    }
    imageryTop5.value = Array.isArray(response?.imagery_repeat_top5) ? response.imagery_repeat_top5 : []
    if (Array.isArray(response?.hook_achievement_trend)) {
      hookTrend.value = response.hook_achievement_trend
      hookTrendStatus.value = 'ready'
    } else {
      hookTrend.value = []
      hookTrendStatus.value = 'unavailable'
    }
  } catch (error) {
    // Don't surface an ElMessage toast here — the main fetch already errored.
    // Just reset to safe defaults so the sections render an empty stub.
    thrillsSummary.value = null
    imageryTop5.value = []
    hookTrend.value = []
    hookTrendStatus.value = 'unavailable'
  }
}

function resetV2State() {
  thrillsSummary.value = null
  imageryTop5.value = []
  hookTrend.value = []
  hookTrendStatus.value = 'unavailable'
}

function formatRate(rate) {
  const value = Number(rate ?? 0)
  if (!Number.isFinite(value)) return '0%'
  return `${Math.round(value * 100)}%`
}

function handleRefresh() {
  void fetchTrends()
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

onBeforeUnmount(() => {
  // nothing to clean up; echarts handled by VChart component lifecycle
})

defineExpose({ fetchTrends })
</script>

<style scoped>
.quality-trends-chart {
  width: 100%;
  height: 420px;
}

.quality-trends-empty {
  align-items: center;
  border: 1px dashed var(--app-border);
  border-radius: 0.75rem;
  color: var(--app-text-muted);
  display: flex;
  font-size: 0.9rem;
  justify-content: center;
  min-height: 320px;
  padding: 1.5rem;
}

.legend-item {
  border-radius: 9999px;
  display: inline-block;
  height: 10px;
  width: 10px;
}

.legend-item--pass { background-color: #22c55e; }
.legend-item--warn { background-color: #f59e0b; }
.legend-item--block { background-color: #ef4444; }
.legend-item--unchecked { background-color: #9ca3af; }
</style>
