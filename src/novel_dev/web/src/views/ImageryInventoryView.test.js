import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getImageryInventory } from '@/api.js'
import ImageryInventoryView from './ImageryInventoryView.vue'

vi.mock('@/api.js', () => ({
  getImageryInventory: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

const sampleItems = [
  {
    item: '寒月',
    item_type: 'nature',
    chapter_id: 'ch-1',
    frequency_in_chapter: 3,
  },
  {
    item: '寒月',
    item_type: 'nature',
    chapter_id: 'ch-2',
    frequency_in_chapter: 5,
  },
  {
    item: '长剑出鞘',
    item_type: 'action',
    chapter_id: 'ch-2',
    frequency_in_chapter: 1,
  },
]

function mountView(props = { novelId: 'novel-1' }) {
  return mount(ImageryInventoryView, {
    props,
    global: {
      stubs: {
        ElButton: {
          name: 'ElButton',
          props: ['loading'],
          emits: ['click'],
          template:
            '<button v-bind="$attrs" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
        },
        ElSkeleton: { name: 'ElSkeleton', template: '<div class="el-skeleton-stub" />' },
        ElSelect: {
          name: 'ElSelect',
          props: ['modelValue'],
          emits: ['update:modelValue', 'change'],
          template:
            '<select :value="modelValue" data-testid="imagery-window-select-native" @change="$emit(\'update:modelValue\', Number($event.target.value)); $emit(\'change\', Number($event.target.value))"><slot /></select>',
        },
        ElOption: {
          name: 'ElOption',
          props: ['label', 'value'],
          template: '<option :value="value">{{ label }}</option>',
        },
      },
    },
  })
}

describe('ImageryInventoryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches imagery on mount and renders rows with translated fields', async () => {
    getImageryInventory.mockResolvedValueOnce({
      novel_id: 'novel-1',
      window: 5,
      items: sampleItems,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(getImageryInventory).toHaveBeenCalledWith('novel-1', 5)
    const rows = wrapper.findAll('[data-testid="imagery-row"]')
    expect(rows).toHaveLength(3)
    const firstRow = rows[0]
    expect(firstRow.text()).toContain('寒月')
    expect(firstRow.text()).toContain('自然')
    expect(firstRow.text()).toContain('第 1 章')
    expect(firstRow.text()).toContain('本章出现 3 次')
  })

  it('renders an empty state when API returns no imagery rows', async () => {
    getImageryInventory.mockResolvedValueOnce({
      novel_id: 'novel-1',
      window: 5,
      items: [],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="imagery-empty"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="imagery-row"]')).toHaveLength(0)
  })

  it('aggregates imagery items by item text and shows chapter count and total frequency', async () => {
    getImageryInventory.mockResolvedValueOnce({
      novel_id: 'novel-1',
      window: 5,
      items: sampleItems,
    })

    const wrapper = mountView()
    await flushPromises()

    const aggregates = wrapper.findAll('[data-testid="imagery-aggregate-row"]')
    expect(aggregates).toHaveLength(2)
    const hanYueAggregate = aggregates.find((a) => a.attributes('data-item') === '寒月')
    expect(hanYueAggregate.exists()).toBe(true)
    expect(hanYueAggregate.text()).toContain('2 章')
    expect(hanYueAggregate.text()).toContain('累计 8 次')

    expect(wrapper.find('[data-testid="imagery-count"]').text()).toBe('3')
    expect(wrapper.find('[data-testid="imagery-aggregate-count"]').text()).toBe('2')
  })

  it('falls back to the raw item_type when the type is not in the translation map', async () => {
    getImageryInventory.mockResolvedValueOnce({
      novel_id: 'novel-1',
      window: 5,
      items: [
        {
          item: '未知意象',
          item_type: 'something_unknown',
          chapter_id: 'ch-7',
          frequency_in_chapter: 2,
        },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const row = wrapper.find('[data-testid="imagery-row"]')
    expect(row.text()).toContain('something_unknown')
  })

  it('refetches with a new window when the select changes', async () => {
    getImageryInventory.mockResolvedValue({
      novel_id: 'novel-1',
      window: 5,
      items: [],
    })

    const wrapper = mountView()
    await flushPromises()
    expect(getImageryInventory).toHaveBeenCalledWith('novel-1', 5)
    expect(getImageryInventory).toHaveBeenCalledTimes(1)

    const select = wrapper.find('select')
    await select.setValue('10')
    await flushPromises()

    expect(getImageryInventory).toHaveBeenCalledTimes(2)
    expect(getImageryInventory).toHaveBeenLastCalledWith('novel-1', 10)
  })

  it('refetches when the refresh button is clicked', async () => {
    getImageryInventory.mockResolvedValue({
      novel_id: 'novel-1',
      window: 5,
      items: [],
    })

    const wrapper = mountView()
    await flushPromises()
    expect(getImageryInventory).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="imagery-refresh"]').trigger('click')
    await flushPromises()

    expect(getImageryInventory).toHaveBeenCalledTimes(2)
  })

  it('shows an ElMessage error and clears state when the API fails', async () => {
    const { ElMessage } = await import('element-plus')
    getImageryInventory.mockRejectedValueOnce(new Error('boom'))

    const wrapper = mountView()
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith('boom')
    expect(wrapper.find('[data-testid="imagery-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="imagery-count"]').text()).toBe('0')
  })

  it('refetches when the novelId prop changes', async () => {
    getImageryInventory.mockResolvedValue({
      novel_id: 'novel-1',
      window: 5,
      items: [],
    })

    const wrapper = mountView({ novelId: 'novel-1' })
    await flushPromises()
    expect(getImageryInventory).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ novelId: 'novel-2' })
    await flushPromises()

    expect(getImageryInventory).toHaveBeenCalledTimes(2)
    expect(getImageryInventory).toHaveBeenLastCalledWith('novel-2', 5)
  })
})