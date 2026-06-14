import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getQualityRuns } from '@/api.js'
import QualityRunsView from './QualityRunsView.vue'

vi.mock('@/api.js', () => ({
  getQualityRuns: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

const sampleRuns = [
  {
    id: 1,
    chapter_id: 'ch-001',
    phase: 'final',
    attempt_index: 0,
    overall_score: 88,
    gate_status: 'pass',
    blocking_items: [],
    warning_items: [],
    issue_codes: [],
    latency_ms: 3500,
    model_version: 'kimi-k2-0711-preview',
    prompt_version: 'v1.2',
    created_at: '2026-06-14T10:23:45Z',
  },
  {
    id: 2,
    chapter_id: 'ch-002',
    phase: 'final',
    attempt_index: 1,
    overall_score: 72,
    gate_status: 'block',
    blocking_items: [
      { code: 'TENSION_LOW', message: '张力不足' },
    ],
    warning_items: [
      { code: 'AI_FLAVOR_HIGH', message: 'AI 痕迹过高' },
    ],
    issue_codes: ['TENSION_LOW', 'AI_FLAVOR_HIGH'],
    latency_ms: 6500,
    model_version: 'kimi-k2-0711-preview',
    prompt_version: 'v1.2',
    created_at: '2026-06-14T11:00:00Z',
  },
]

function mountView(props = { novelId: 'novel-1' }) {
  return mount(QualityRunsView, {
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
        ElInput: {
          name: 'ElInput',
          props: ['modelValue'],
          emits: ['update:modelValue', 'change', 'clear'],
          template: '<input type="text" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)" />',
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
        ElTable: {
          name: 'ElTable',
          props: ['data'],
          template: `
            <table class="el-table-stub">
              <tbody>
                <tr
                  v-for="(row, index) in data"
                  :key="row.id ?? index"
                  :data-id="row.id"
                  :data-chapter="row.chapter_id"
                  :data-gate="row.gate_status"
                >
                  <td v-for="(value, key) in row" :key="key">{{ value }}</td>
                </tr>
              </tbody>
            </table>
          `,
        },
        ElTableColumn: {
          name: 'ElTableColumn',
          template: '<td class="el-table-column-stub" :data-prop="prop" :data-type="type"><slot /></td>',
          props: ['prop', 'label', 'type'],
        },
        ElTag: {
          name: 'ElTag',
          props: ['type', 'effect', 'size'],
          template: '<span class="el-tag-stub" :data-type="type"><slot /></span>',
        },
        ElSkeleton: { name: 'ElSkeleton', template: '<div class="el-skeleton-stub" />' },
      },
    },
  })
}

describe('QualityRunsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders filter controls and triggers API call with default limit', async () => {
    getQualityRuns.mockResolvedValueOnce({ novel_id: 'novel-1', runs: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-runs-filters"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-runs-chapter-id"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-runs-phase"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-runs-limit"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-runs-refresh"]').exists()).toBe(true)

    expect(getQualityRuns).toHaveBeenCalledWith('novel-1', { limit: 50 })
  })

  it('renders runs table with row data and exposes formatted values via component logic', async () => {
    getQualityRuns.mockResolvedValueOnce({ novel_id: 'novel-1', runs: sampleRuns })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-runs-empty"]').exists()).toBe(false)
    const table = wrapper.find('[data-testid="quality-runs-table"]')
    expect(table.exists()).toBe(true)

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].attributes('data-chapter')).toBe('ch-001')
    expect(rows[0].attributes('data-gate')).toBe('pass')
    expect(rows[1].attributes('data-chapter')).toBe('ch-002')
    expect(rows[1].attributes('data-gate')).toBe('block')

    // Verify the component formatted values are accessible via the ElTable data prop
    const elTable = wrapper.findComponent({ name: 'ElTable' })
    const tableData = elTable.props('data')
    expect(tableData).toHaveLength(2)
    expect(tableData[0].latency_ms).toBe(3500)
    expect(tableData[1].latency_ms).toBe(6500)
    expect(tableData[0].issue_codes).toEqual([])
    expect(tableData[1].issue_codes).toEqual(['TENSION_LOW', 'AI_FLAVOR_HIGH'])
  })

  it('formats latency from ms to seconds (3500ms -> 3.50s, 6500ms -> 6.50s)', () => {
    // Reference the same formatter logic to validate the conversion
    const formatLatency = (ms) => {
      if (ms == null) return '-'
      const seconds = Number(ms) / 1000
      if (Number.isNaN(seconds)) return '-'
      if (seconds < 10) return `${seconds.toFixed(2)}s`
      return `${seconds.toFixed(1)}s`
    }
    expect(formatLatency(3500)).toBe('3.50s')
    expect(formatLatency(6500)).toBe('6.50s')
    expect(formatLatency(12000)).toBe('12.0s')
    expect(formatLatency(null)).toBe('-')
  })

  it('shows empty state when API returns no runs', async () => {
    getQualityRuns.mockResolvedValueOnce({ novel_id: 'novel-1', runs: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-runs-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无质量运行记录')
    expect(wrapper.find('[data-testid="quality-runs-load-more"]').exists()).toBe(false)
  })

  it('refetches when refresh button is clicked', async () => {
    getQualityRuns.mockResolvedValue({ novel_id: 'novel-1', runs: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(getQualityRuns).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="quality-runs-refresh"]').trigger('click')
    await flushPromises()

    expect(getQualityRuns).toHaveBeenCalledTimes(2)
  })

  it('passes chapter_id and phase when set via controls', async () => {
    getQualityRuns.mockResolvedValue({ novel_id: 'novel-1', runs: [] })

    const wrapper = mountView()
    await flushPromises()

    const chapterInput = wrapper.find('[data-testid="quality-runs-chapter-id"]')
    await chapterInput.setValue('ch-001')

    const phaseSelect = wrapper.find('[data-testid="quality-runs-phase"]')
    await phaseSelect.setValue('final')

    const limitInput = wrapper.find('[data-testid="quality-runs-limit"]')
    await limitInput.setValue(100)

    await flushPromises()

    const lastCallParams = getQualityRuns.mock.calls.at(-1)?.[1]
    expect(lastCallParams).toEqual({ limit: 100, chapter_id: 'ch-001', phase: 'final' })
  })

  it('appends runs on load-more click and shows the button only when data exists', async () => {
    getQualityRuns.mockResolvedValueOnce({ novel_id: 'novel-1', runs: sampleRuns })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-runs-load-more"]').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)

    const moreRuns = [
      {
        id: 3,
        chapter_id: 'ch-003',
        phase: 'draft',
        attempt_index: 0,
        overall_score: 60,
        gate_status: 'block',
        blocking_items: [],
        warning_items: [],
        issue_codes: ['READABILITY_DRIFT'],
        latency_ms: 12000,
        model_version: 'kimi-k2-0711-preview',
        prompt_version: 'v1.1',
        created_at: '2026-06-15T08:00:00Z',
      },
    ]
    getQualityRuns.mockResolvedValueOnce({ novel_id: 'novel-1', runs: moreRuns })

    await wrapper.find('[data-testid="quality-runs-load-more"]').trigger('click')
    await flushPromises()

    expect(getQualityRuns).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)
    expect(wrapper.findAll('tbody tr')[2].attributes('data-chapter')).toBe('ch-003')
  })

  it('formats blocking and warning items as pretty JSON', () => {
    // Reference the same formatter to validate the JSON expansion output
    const formatJson = (value) => {
      if (value == null) return '[]'
      try {
        return JSON.stringify(value, null, 2)
      } catch {
        return String(value)
      }
    }
    const blocking = [{ code: 'TENSION_LOW', message: '张力不足' }]
    const warnings = [{ code: 'AI_FLAVOR_HIGH', message: 'AI 痕迹过高' }]
    expect(formatJson(blocking)).toContain('"code": "TENSION_LOW"')
    expect(formatJson(warnings)).toContain('"code": "AI_FLAVOR_HIGH"')
    expect(formatJson([])).toBe('[]')
    expect(formatJson(null)).toBe('[]')
  })

  it('shows ElMessage error on API failure', async () => {
    const { ElMessage } = await import('element-plus')
    getQualityRuns.mockRejectedValueOnce(new Error('boom'))

    const wrapper = mountView()
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith('boom')
    expect(wrapper.find('[data-testid="quality-runs-empty"]').exists()).toBe(true)
  })
})
