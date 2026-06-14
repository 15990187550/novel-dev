import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getQualityTrends } from '@/api.js'
import QualityTrendsView from './QualityTrendsView.vue'

vi.mock('@/api.js', () => ({
  getQualityTrends: vi.fn(),
}))

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    props: ['option'],
    template: '<div class="v-chart-stub" :data-points="(option && option.series && option.series[0] && option.series[0].data || []).length" />',
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

const samplePoints = [
  {
    chapter_id: 'ch-1',
    chapter_number: 1,
    title: '道经初现',
    value: 88,
    gate_status: 'pass',
    issue_codes: [],
    source: 'metrics',
    created_at: '2026-05-01T00:00:00Z',
  },
  {
    chapter_id: 'ch-2',
    chapter_number: 2,
    title: '风波再起',
    value: 78,
    gate_status: 'warn',
    issue_codes: ['AI_FLAVOR_HIGH'],
    source: 'metrics',
    created_at: '2026-05-02T00:00:00Z',
  },
  {
    chapter_id: 'ch-3',
    chapter_number: 3,
    title: '谜团',
    value: 72,
    gate_status: 'block',
    issue_codes: ['TENSION_LOW'],
    source: 'chapter_fallback',
    created_at: '2026-05-03T00:00:00Z',
  },
]

function mountView(props = { novelId: 'novel-1' }) {
  return mount(QualityTrendsView, {
    props,
    global: {
      stubs: {
        ElSelect: {
          name: 'ElSelect',
          props: ['modelValue'],
          emits: ['update:modelValue', 'change'],
          template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>',
        },
        ElOption: {
          name: 'ElOption',
          props: ['label', 'value'],
          template: '<option :value="value">{{ label }}</option>',
        },
        ElInputNumber: {
          name: 'ElInputNumber',
          props: ['modelValue'],
          emits: ['update:modelValue', 'change'],
          template: '<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value)); $emit(\'change\', Number($event.target.value))" />',
        },
        ElButton: {
          name: 'ElButton',
          emits: ['click'],
          template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
        },
        ElSkeleton: { name: 'ElSkeleton', template: '<div class="el-skeleton-stub" />' },
      },
    },
  })
}

describe('QualityTrendsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders filter controls and triggers API call with the selected dimension', async () => {
    getQualityTrends.mockResolvedValueOnce({ novel_id: 'novel-1', dimension: 'overall', phase: 'final', points: samplePoints })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-trends-filters"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-trends-dimension"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-trends-from"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-trends-to"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-trends-refresh"]').exists()).toBe(true)

    expect(getQualityTrends).toHaveBeenCalledWith('novel-1', { dimension: 'overall', phase: 'final' })
  })

  it('renders chart with colored points and markLine thresholds when data exists', async () => {
    getQualityTrends.mockResolvedValueOnce({ novel_id: 'novel-1', dimension: 'overall', phase: 'final', points: samplePoints })

    const wrapper = mountView()
    await flushPromises()

    const chart = wrapper.find('[data-testid="quality-trends-chart"]')
    expect(chart.exists()).toBe(true)
    expect(chart.attributes('data-points')).toBe('3')

    // Trigger ECharts tooltip formatter via component computed option
    const vchart = wrapper.findComponent({ name: 'VChart' })
    const option = vchart.props('option')
    expect(option.xAxis.data).toEqual([1, 2, 3])
    expect(option.yAxis.max).toBe(100)
    expect(option.series[0].data[0].itemStyle.color).toBe('#22c55e')
    expect(option.series[0].data[1].itemStyle.color).toBe('#f59e0b')
    expect(option.series[0].data[2].itemStyle.color).toBe('#ef4444')
    expect(option.series[0].markLine.data).toEqual([
      expect.objectContaining({ yAxis: 82 }),
      expect.objectContaining({ yAxis: 75 }),
    ])

    // Tooltip text should include chapter title, score, gate label, and issue code
    // ECharts tooltip formatter receives an array of { data, value, ... } per series point.
    // Our series uses { value: [chapterNumber, value, point] } so data === the array.
    const tooltipHtml = option.tooltip.formatter([{ data: option.series[0].data[0].value }])
    expect(tooltipHtml).toContain('道经初现')
    expect(tooltipHtml).toContain('评分: 88')
    expect(tooltipHtml).toContain('门状态: 通过')
  })

  it('shows empty state when API returns no points', async () => {
    getQualityTrends.mockResolvedValueOnce({ novel_id: 'novel-1', dimension: 'overall', phase: 'final', points: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-trends-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无质量数据')
  })

  it('refetches when refresh button is clicked', async () => {
    getQualityTrends.mockResolvedValue({ novel_id: 'novel-1', dimension: 'overall', phase: 'final', points: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(getQualityTrends).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="quality-trends-refresh"]').trigger('click')
    await flushPromises()

    expect(getQualityTrends).toHaveBeenCalledTimes(2)
  })

  it('passes from_chapter and to_chapter when set via inputs', async () => {
    getQualityTrends.mockResolvedValue({ novel_id: 'novel-1', dimension: 'overall', phase: 'final', points: [] })

    const wrapper = mountView()
    await flushPromises()

    const fromInput = wrapper.find('[data-testid="quality-trends-from"]')
    const toInput = wrapper.find('[data-testid="quality-trends-to"]')

    await fromInput.setValue(2)
    await toInput.setValue(8)
    await flushPromises()

    const lastCallParams = getQualityTrends.mock.calls.at(-1)?.[1]
    expect(lastCallParams).toEqual({ dimension: 'overall', phase: 'final', from_chapter: 2, to_chapter: 8 })
  })
})
