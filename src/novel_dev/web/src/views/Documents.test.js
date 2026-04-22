import { defineComponent, h, inject, nextTick, provide } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import Documents from './Documents.vue'

function createDeferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const { approvePendingMock, uploadDocumentsBatchMock, rejectPendingMock, successMessageMock } = vi.hoisted(() => ({
  approvePendingMock: vi.fn(),
  uploadDocumentsBatchMock: vi.fn(),
  rejectPendingMock: vi.fn(),
  successMessageMock: vi.fn(),
}))

vi.mock('@/api.js', () => ({
  approvePending: approvePendingMock,
  uploadDocumentsBatch: uploadDocumentsBatchMock,
  rejectPending: rejectPendingMock,
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: successMessageMock,
  },
}))

const ElButtonStub = defineComponent({
  name: 'ElButtonStub',
  props: {
    loading: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    type: { type: String, default: '' },
    size: { type: String, default: '' },
  },
  emits: ['click'],
  setup(props, { emit, slots }) {
    return () =>
      h(
        'button',
        {
          class: 'el-button-stub',
          disabled: props.disabled,
          'data-loading': props.loading ? 'true' : 'false',
          'data-type': props.type,
          'data-size': props.size,
          onClick: () => emit('click'),
        },
        slots.default?.()
      )
  },
})

const ElSelectStub = defineComponent({
  name: 'ElSelectStub',
  props: {
    modelValue: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
    size: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  setup(props, { emit, slots }) {
    return () =>
      h(
        'button',
        {
          class: 'el-select-stub',
          type: 'button',
          disabled: props.disabled,
          'data-size': props.size,
          onClick: () => emit('update:modelValue', 'merge'),
        },
        slots.default?.() || props.modelValue || 'select'
      )
  },
})

const tableRowKey = Symbol('table-row')

const TableRowScope = defineComponent({
  name: 'TableRowScope',
  props: {
    row: { type: Object, required: true },
  },
  setup(props, { slots }) {
    provide(tableRowKey, props.row)
    return () => slots.default?.()
  },
})

describe('Documents', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
  })

  function mountView() {
    return mount(Documents, {
      global: {
        plugins: [pinia],
        stubs: {
          ElAlert: defineComponent({
            name: 'ElAlertStub',
            props: {
              title: { type: String, default: '' },
            },
            setup(props) {
              return () => h('div', { class: 'el-alert-stub' }, props.title)
            },
          }),
          ElTable: defineComponent({
            name: 'ElTableStub',
            props: {
              data: { type: Array, default: () => [] },
            },
            setup(props, { slots }) {
              return () =>
                h(
                  'div',
                  { class: 'el-table-stub' },
                  props.data.map((row) =>
                    h(
                      TableRowScope,
                      { row },
                      {
                        default: () => h('div', { class: 'el-table-row-stub' }, slots.default?.()),
                      }
                    )
                  )
                )
            },
          }),
          ElTableColumn: defineComponent({
            name: 'ElTableColumnStub',
            props: {
              label: { type: String, default: '' },
              prop: { type: String, default: '' },
            },
            setup(_, { slots }) {
              const row = inject(tableRowKey, null)
              return () =>
                h(
                  'div',
                  { class: 'el-table-column-stub' },
                  slots.default?.({ row }) ?? (row && _.prop ? row[_.prop] : '')
                )
            },
          }),
          ElButton: ElButtonStub,
          ElDialog: defineComponent({
            name: 'ElDialogStub',
            setup(_, { slots }) {
              return () => h('div', { class: 'el-dialog-stub' }, slots.default?.())
            },
          }),
          ElCollapse: true,
          ElCollapseItem: true,
          ElEmpty: true,
          ElSelect: ElSelectStub,
          ElOption: defineComponent({
            name: 'ElOptionStub',
            props: {
              label: { type: String, default: '' },
            },
            setup(props) {
              return () => h('span', { class: 'el-option-stub' }, props.label)
            },
          }),
          ElTag: true,
        },
      },
    })
  }

  it('shows loading for the current approve action and disables repeated approvals', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      { id: 'doc-1', source_filename: '设定一.md', extraction_type: 'setting', status: 'pending', created_at: '2026-04-22T00:00:00Z' },
      { id: 'doc-2', source_filename: '设定二.md', extraction_type: 'setting', status: 'pending', created_at: '2026-04-22T00:00:01Z' },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()

    const deferred = createDeferred()
    approvePendingMock.mockReturnValue(deferred.promise)

    const wrapper = mountView()
    await flushPromises()

    const buttons = wrapper.findAll('.el-button-stub')
    const approveButtons = buttons.filter((button) => button.text() === '批准')
    expect(approveButtons).toHaveLength(2)

    await approveButtons[0].trigger('click')
    await nextTick()

    const updatingButtons = wrapper.findAll('.el-button-stub').filter((button) => ['批准', '批准中...'].includes(button.text()))
    expect(updatingButtons[0].text()).toBe('批准中...')
    expect(updatingButtons[0].attributes('data-loading')).toBe('true')
    expect(updatingButtons[0].attributes('disabled')).toBeUndefined()
    expect(updatingButtons[1].attributes('disabled')).toBeDefined()

    deferred.resolve({ documents: [] })
    await flushPromises()

    const settledButtons = wrapper.findAll('.el-button-stub').filter((button) => button.text() === '批准')
    expect(settledButtons[0].attributes('data-loading')).toBe('false')
    expect(settledButtons[0].attributes('disabled')).toBeUndefined()
    expect(settledButtons[1].attributes('disabled')).toBeUndefined()
    expect(store.fetchDocuments).toHaveBeenCalled()
    expect(successMessageMock).toHaveBeenCalledWith('已批准')
  })

  it('renders 导入中 for processing rows restored after remount', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      { id: 'doc-1', source_filename: '设定一.md', extraction_type: 'processing', status: 'processing', created_at: '2026-04-22T00:00:00Z' },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('导入中')
  })

  it('shows merge loading state and refreshes detail results after automatic merge succeeds', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-1',
        source_filename: '设定一.md',
        extraction_type: 'setting',
        status: 'pending',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '1 个冲突',
          entity_diffs: [
            {
              entity_type: 'item',
              entity_name: '道经',
              operation: 'conflict',
              field_changes: [
                {
                  field: 'description',
                  old_value: '旧描述',
                  new_value: '新描述',
                  auto_applicable: false,
                },
              ],
            },
          ],
        },
      },
    ]
    store.fetchDocuments = vi.fn().mockImplementation(async () => {
      store.pendingDocs = [
        {
          id: 'doc-1',
          source_filename: '设定一.md',
          extraction_type: 'setting',
          status: 'approved',
          created_at: '2026-04-22T00:00:00Z',
          diff_result: {
            summary: '1 个冲突',
            entity_diffs: [
              {
                entity_type: 'item',
                entity_name: '道经',
                operation: 'conflict',
                field_changes: [
                  {
                    field: 'description',
                    old_value: '旧描述',
                    new_value: '新描述',
                    auto_applicable: false,
                  },
                ],
              },
            ],
          },
          resolution_result: {
            field_resolutions: [
              {
                entity_name: '道经',
                field: 'description',
                action: 'merge',
                applied: true,
              },
            ],
          },
        },
      ]
    })

    const deferred = createDeferred()
    approvePendingMock.mockReturnValue(deferred.promise)

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await nextTick()

    await wrapper.find('.el-select-stub').trigger('click')
    await nextTick()

    const approveButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '批准')
    await approveButton.trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('自动合并中')
    expect(approvePendingMock).toHaveBeenCalledWith('novel-1', 'doc-1', [
      {
        entity_type: 'item',
        entity_name: '道经',
        field: 'description',
        action: 'merge',
      },
    ])

    deferred.resolve({})
    await flushPromises()

    expect(store.fetchDocuments).toHaveBeenCalled()
    expect(wrapper.text()).toContain('自动合并')
    expect(wrapper.text()).toContain('已写入')
    expect(successMessageMock).toHaveBeenCalledWith('自动合并完成')
  })

  it('preserves conflict selections when the same document detail is reopened', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-1',
        source_filename: '设定一.md',
        extraction_type: 'setting',
        status: 'pending',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '1 个冲突',
          entity_diffs: [
            {
              entity_type: 'item',
              entity_name: '道经',
              operation: 'conflict',
              field_changes: [
                {
                  field: 'description',
                  old_value: '旧描述',
                  new_value: '新描述',
                  auto_applicable: false,
                },
              ],
            },
          ],
        },
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await nextTick()

    expect(wrapper.vm.conflictSelections['item:道经:description']).toBe('merge')

    await wrapper.find('.el-select-stub').trigger('click')
    expect(wrapper.vm.conflictSelections['item:道经:description']).toBe('merge')

    wrapper.vm.detailVisible = false
    await nextTick()

    await detailButton.trigger('click')
    await nextTick()

    expect(wrapper.vm.conflictSelections['item:道经:description']).toBe('merge')
  })

  it('refreshes records after batch upload submission and polls while processing rows exist', async () => {
    vi.useFakeTimers()
    const originalFileReader = global.FileReader
    global.FileReader = class {
      readAsText(file) {
        this.onload?.({ target: { result: `内容:${file.name}` } })
      }
    }

    try {
      const store = useNovelStore()
      store.novelId = 'novel-1'
      store.pendingDocs = []
      let fetchCount = 0
      store.fetchDocuments = vi.fn().mockImplementation(async () => {
        fetchCount += 1
        if (fetchCount >= 2) {
          store.pendingDocs = [
            { id: 'doc-1', source_filename: '设定一.md', extraction_type: 'processing', status: 'processing', created_at: '2026-04-22T00:00:00Z' },
          ]
        }
      })

      uploadDocumentsBatchMock.mockResolvedValue({ total: 1, accepted: 1, failed: 0, items: [{ pending_id: 'doc-1', status: 'processing' }] })

      const wrapper = mountView()
      await flushPromises()
      expect(store.fetchDocuments).toHaveBeenCalledTimes(1)

      const input = wrapper.find('input[type="file"]')
      const file = new File(['世界观：天玄大陆。'], '设定一.md', { type: 'text/markdown' })
      Object.defineProperty(input.element, 'files', {
        value: [file],
        configurable: true,
      })
      await input.trigger('change')
      await flushPromises()

      const uploadButton = wrapper.findAll('.el-button-stub')[0]
      await uploadButton.trigger('click')
      await flushPromises()

      expect(uploadDocumentsBatchMock).toHaveBeenCalledWith('novel-1', [{ filename: '设定一.md', content: '内容:设定一.md' }], 3)
      expect(store.fetchDocuments).toHaveBeenCalledTimes(2)

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(store.fetchDocuments).toHaveBeenCalledTimes(3)
    } finally {
      global.FileReader = originalFileReader
      vi.useRealTimers()
    }
  })
})
