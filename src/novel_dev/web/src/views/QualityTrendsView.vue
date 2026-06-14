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
import { getQualityTrends } from '@/api.js'

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
const loading = ref(false)
const errorMessage = ref('')
const points = ref([])

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
  } catch (error) {
    points.value = []
    const detail = error?.response?.data?.detail
    errorMessage.value = detail || error?.message || '质量趋势加载失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
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
