import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getQualityIssues } from '@/api.js'
import QualityIssuesView from './QualityIssuesView.vue'

vi.mock('@/api.js', () => ({
  getQualityIssues: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

const sampleHints = [
  {
    code: 'AI_FLAVOR_HIGH',
    severity: 'warn',
    threshold: 3,
    hint: 'AI 痕迹过高，需要更强的情感锚点和具体细节...',
    occurrences: 5,
    matches: true,
  },
  {
    code: 'TENSION_LOW',
    severity: 'block',
    threshold: 2,
    hint: '情节张力不足，需要在节拍里增加冲突密度。',
    occurrences: 3,
    matches: true,
  },
  {
    code: 'READABILITY_DRIFT',
    severity: 'info',
    threshold: 4,
    hint: '句子长度漂移，建议缩短长句。',
    occurrences: 1,
    matches: false,
  },
]

function mountView(props = { novelId: 'novel-1' }) {
  return mount(QualityIssuesView, {
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
        ElSwitch: {
          name: 'ElSwitch',
          props: ['modelValue'],
          emits: ['update:modelValue', 'change'],
          template: '<input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked); $emit(\'change\', $event.target.checked)" />',
        },
        ElTable: {
          name: 'ElTable',
          props: ['data', 'rowClassName'],
          template: `
            <table class="el-table-stub">
              <tbody>
                <tr
                  v-for="(row, index) in data"
                  :key="index"
                  :class="rowClassName ? rowClassName({ row }) : ''"
                  :data-code="row.code"
                  :data-matches="row.matches"
                >
                  <td v-for="(value, key) in row" :key="key">{{ value }}</td>
                </tr>
              </tbody>
            </table>
          `,
        },
        ElTableColumn: {
          name: 'ElTableColumn',
          template: '<td class="el-table-column-stub" :data-prop="prop"><slot /></td>',
          props: ['prop', 'label'],
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

describe('QualityIssuesView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders filter controls and triggers API call with default phase', async () => {
    getQualityIssues.mockResolvedValueOnce({
      novel_id: 'novel-1',
      phase: 'final',
      hints: sampleHints,
      total_chapters: 12,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-issues-filters"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-issues-phase"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-issues-from"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-issues-to"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-issues-only-matched"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="quality-issues-refresh"]').exists()).toBe(true)

    expect(getQualityIssues).toHaveBeenCalledWith('novel-1', { phase: 'final' })
  })

  it('shows total chapters and the matched hint rows in the table', async () => {
    getQualityIssues.mockResolvedValueOnce({
      novel_id: 'novel-1',
      phase: 'final',
      hints: sampleHints,
      total_chapters: 12,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-issues-total-chapters"]').text()).toBe('12')

    const table = wrapper.find('[data-testid="quality-issues-table"]')
    expect(table.exists()).toBe(true)
    const rows = wrapper.findAll('tbody tr')
    // onlyMatched defaults to true so the unmatched READABILITY_DRIFT row is filtered out
    expect(rows).toHaveLength(2)
    expect(rows[0].attributes('data-code')).toBe('AI_FLAVOR_HIGH')
    expect(rows[1].attributes('data-code')).toBe('TENSION_LOW')
  })

  it('marks matched rows with the highlight class and sorts by occurrences desc', async () => {
    getQualityIssues.mockResolvedValueOnce({
      novel_id: 'novel-1',
      phase: 'final',
      hints: sampleHints,
      total_chapters: 12,
    })

    const wrapper = mountView()
    await flushPromises()

    const table = wrapper.findComponent({ name: 'ElTable' })
    const rows = table.props('data')
    expect(rows).toHaveLength(2)
    // Sorted by occurrences desc: AI_FLAVOR_HIGH (5) before TENSION_LOW (3)
    expect(rows[0].code).toBe('AI_FLAVOR_HIGH')
    expect(rows[1].code).toBe('TENSION_LOW')

    // Verify rowClassName marks matched rows
    const classFn = table.props('rowClassName')
    expect(classFn({ row: rows[0] })).toBe('quality-issues-row--matched')
    expect(classFn({ row: { code: 'X', matches: false } })).toBe('')
  })

  it('shows empty state when API returns no hints', async () => {
    getQualityIssues.mockResolvedValueOnce({
      novel_id: 'novel-1',
      phase: 'final',
      hints: [],
      total_chapters: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="quality-issues-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无质量问题')
  })

  it('refetches when refresh button is clicked', async () => {
    getQualityIssues.mockResolvedValue({
      novel_id: 'novel-1',
      phase: 'final',
      hints: [],
      total_chapters: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(getQualityIssues).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="quality-issues-refresh"]').trigger('click')
    await flushPromises()

    expect(getQualityIssues).toHaveBeenCalledTimes(2)
  })

  it('passes from_chapter, to_chapter, and phase when set via controls', async () => {
    getQualityIssues.mockResolvedValue({
      novel_id: 'novel-1',
      phase: 'draft',
      hints: [],
      total_chapters: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const phaseSelect = wrapper.find('[data-testid="quality-issues-phase"]')
    await phaseSelect.setValue('draft')

    const fromInput = wrapper.find('[data-testid="quality-issues-from"]')
    const toInput = wrapper.find('[data-testid="quality-issues-to"]')
    await fromInput.setValue(2)
    await toInput.setValue(8)
    await flushPromises()

    const lastCallParams = getQualityIssues.mock.calls.at(-1)?.[1]
    expect(lastCallParams).toEqual({ phase: 'draft', from_chapter: 2, to_chapter: 8 })
  })

  it('toggling only-matched off shows the unmatched rows', async () => {
    getQualityIssues.mockResolvedValue({
      novel_id: 'novel-1',
      phase: 'final',
      hints: sampleHints,
      total_chapters: 12,
    })

    const wrapper = mountView()
    await flushPromises()

    const switchEl = wrapper.find('[data-testid="quality-issues-only-matched"]')
    await switchEl.setValue(false)
    await flushPromises()

    const table = wrapper.findComponent({ name: 'ElTable' })
    const rows = table.props('data')
    expect(rows).toHaveLength(3)
    const codes = rows.map((row) => row.code)
    expect(codes).toContain('READABILITY_DRIFT')
  })

  it('shows ElMessage error on API failure', async () => {
    const { ElMessage } = await import('element-plus')
    getQualityIssues.mockRejectedValueOnce(new Error('boom'))

    const wrapper = mountView()
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith('boom')
    expect(wrapper.find('[data-testid="quality-issues-empty"]').exists()).toBe(true)
  })
})
