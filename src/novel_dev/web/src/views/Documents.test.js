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

const {
  approvePendingMock,
  deletePendingDocMock,
  uploadDocumentsBatchMock,
  rejectPendingMock,
  updatePendingDraftFieldMock,
  getDocumentLibraryMock,
  getKnowledgeDomainsMock,
  confirmKnowledgeDomainScopeMock,
  disableKnowledgeDomainMock,
  deleteKnowledgeDomainMock,
  updateLibraryDocumentMock,
  rollbackStyleProfileMock,
  successMessageMock,
  confirmMessageBoxMock,
  routerPushMock,
} = vi.hoisted(() => ({
  approvePendingMock: vi.fn(),
  deletePendingDocMock: vi.fn(),
  uploadDocumentsBatchMock: vi.fn(),
  rejectPendingMock: vi.fn(),
  updatePendingDraftFieldMock: vi.fn(),
  getDocumentLibraryMock: vi.fn(),
  getKnowledgeDomainsMock: vi.fn(),
  confirmKnowledgeDomainScopeMock: vi.fn(),
  disableKnowledgeDomainMock: vi.fn(),
  deleteKnowledgeDomainMock: vi.fn(),
  updateLibraryDocumentMock: vi.fn(),
  rollbackStyleProfileMock: vi.fn(),
  successMessageMock: vi.fn(),
  confirmMessageBoxMock: vi.fn(),
  routerPushMock: vi.fn(),
}))

vi.mock('@/api.js', () => ({
  approvePending: approvePendingMock,
  deletePendingDoc: deletePendingDocMock,
  uploadDocumentsBatch: uploadDocumentsBatchMock,
  rejectPending: rejectPendingMock,
  updatePendingDraftField: updatePendingDraftFieldMock,
  getDocumentLibrary: getDocumentLibraryMock,
  getKnowledgeDomains: getKnowledgeDomainsMock,
  confirmKnowledgeDomainScope: confirmKnowledgeDomainScopeMock,
  disableKnowledgeDomain: disableKnowledgeDomainMock,
  deleteKnowledgeDomain: deleteKnowledgeDomainMock,
  updateLibraryDocument: updateLibraryDocumentMock,
  rollbackStyleProfile: rollbackStyleProfileMock,
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: successMessageMock,
  },
  ElMessageBox: {
    confirm: confirmMessageBoxMock,
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: routerPushMock,
  }),
}))

const ElButtonStub = defineComponent({
  name: 'ElButtonStub',
  props: {
    loading: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    type: { type: String, default: '' },
    size: { type: String, default: '' },
    plain: { type: Boolean, default: false },
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
          'data-plain': props.plain ? 'true' : 'false',
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
    getDocumentLibraryMock.mockResolvedValue({ items: [], active_style_profile_version: null })
    getKnowledgeDomainsMock.mockResolvedValue({ items: [] })
    confirmKnowledgeDomainScopeMock.mockResolvedValue({ item: {} })
    disableKnowledgeDomainMock.mockResolvedValue({ item: {} })
    deleteKnowledgeDomainMock.mockResolvedValue({ deleted: true, deleted_documents: 2, deleted_entities: 3 })
    confirmMessageBoxMock.mockResolvedValue()
    rollbackStyleProfileMock.mockResolvedValue({ rolled_back_to_version: 1 })
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
          ElInput: defineComponent({
            name: 'ElInputStub',
            props: {
              modelValue: { type: String, default: '' },
              placeholder: { type: String, default: '' },
              size: { type: String, default: '' },
            },
            emits: ['update:modelValue'],
            setup(props, { emit }) {
              return () => h('input', {
                class: 'el-input-stub',
                value: props.modelValue,
                placeholder: props.placeholder,
                'data-size': props.size,
                onInput: (event) => emit('update:modelValue', event.target.value),
              })
            },
          }),
          ElDialog: defineComponent({
            name: 'ElDialogStub',
            setup(_, { slots }) {
              return () => h('div', { class: 'el-dialog-stub' }, slots.default?.())
            },
          }),
          ElCollapse: defineComponent({
            name: 'ElCollapseStub',
            setup(_, { attrs, slots }) {
              return () => h('div', { class: ['el-collapse-stub', attrs.class] }, slots.default?.())
            },
          }),
          ElCollapseItem: defineComponent({
            name: 'ElCollapseItemStub',
            props: {
              title: { type: String, default: '' },
            },
            setup(props, { slots }) {
              return () => h('section', { class: 'el-collapse-item-stub' }, [
                h('header', { class: 'el-collapse-item-stub__title' }, props.title),
                h('div', { class: 'el-collapse-item-stub__content' }, slots.default?.()),
              ])
            },
          }),
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

  it('keeps approve loading state after remount while the same request is still pending', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      { id: 'doc-1', source_filename: '设定一.md', extraction_type: 'setting', status: 'pending', created_at: '2026-04-22T00:00:00Z' },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()

    const deferred = createDeferred()
    approvePendingMock.mockReturnValue(deferred.promise)

    const firstWrapper = mountView()
    await flushPromises()

    const firstApproveButton = firstWrapper.findAll('.el-button-stub').find((button) => button.text() === '批准')
    await firstApproveButton.trigger('click')
    await nextTick()

    expect(firstWrapper.findAll('.el-button-stub').find((button) => ['批准', '批准中...'].includes(button.text())).text()).toBe('批准中...')

    firstWrapper.unmount()

    const secondWrapper = mountView()
    await flushPromises()

    const secondApproveButton = secondWrapper.findAll('.el-button-stub').find((button) => ['批准', '批准中...'].includes(button.text()))
    expect(secondApproveButton.text()).toBe('批准中...')
    expect(secondApproveButton.attributes('data-loading')).toBe('true')

    deferred.resolve({ documents: [] })
    await flushPromises()

    const settledButton = secondWrapper.findAll('.el-button-stub').find((button) => button.text() === '批准')
    expect(settledButton.attributes('data-loading')).toBe('false')
  })

  it('renders imported setting docs and style profile in the library section', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()

    getDocumentLibraryMock.mockResolvedValue({
      items: [
        {
          id: 'world-1',
          doc_type: 'worldview',
          title: '世界观',
          content: '天玄大陆，万族林立。',
          version: 1,
          updated_at: '2026-04-23T00:00:00Z',
          is_active: true,
        },
        {
          id: 'style-2',
          doc_type: 'style_profile',
          title: '{"perspective":"limited","tone":"热血","writing_rules":["短句推进"]}',
          content: '轻快吐槽里包着热血推进。',
          version: 2,
          updated_at: '2026-04-23T00:00:00Z',
          is_active: true,
          style_config: {
            perspective: 'limited',
            tone: '热血',
            writing_rules: ['短句推进'],
          },
        },
      ],
      active_style_profile_version: 2,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('当前资料库')
    expect(wrapper.text()).toContain('天玄大陆，万族林立。')
    expect(wrapper.text()).toContain('文风档案')
    expect(wrapper.text()).toContain('轻快吐槽里包着热血推进。')
    expect(wrapper.text()).toContain('当前生效')
    expect(wrapper.text()).toContain('短句推进')
  })

  it('renames import review records to unified review records and marks import rows by source', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-1',
        source_filename: '设定.md',
        extraction_type: 'setting',
        status: 'pending',
        diff_result: { summary: '1 个新增实体' },
        created_at: '2026-04-22T00:00:00Z',
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('审核记录')
    expect(wrapper.text()).toContain('导入资料')
    expect(wrapper.text()).toContain('AI 设定会话')
    expect(wrapper.text()).toContain('后续优化')
    expect(wrapper.text()).not.toContain('导入审核记录')
  })

  it('shows AI badge next to AI sourced setting cards and opens the source session', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()

    getDocumentLibraryMock.mockResolvedValue({
      items: [
        {
          id: 'doc-ai',
          doc_type: 'setting',
          title: '修炼体系',
          content: '九境。',
          version: 1,
          updated_at: '2026-04-23T00:00:00Z',
          is_active: true,
          source_type: 'ai',
          source_session_id: 'sgs_1',
          source_review_change_id: 'chg_1',
        },
      ],
      active_style_profile_version: null,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('修炼体系')
    const badge = wrapper.get('.documents-ai-badge')
    expect(badge.text()).toBe('AI')

    await badge.trigger('click')

    expect(routerPushMock).toHaveBeenCalledWith({
      path: '/settings',
      query: { session: 'sgs_1', change: 'chg_1' },
    })
  })

  it('renders knowledge domains and confirms suggested scope', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()

    getKnowledgeDomainsMock
      .mockResolvedValueOnce({
        items: [
          {
            id: 'domain-1',
            novel_id: 'novel-1',
            name: '完美世界',
            domain_type: 'source_work',
            scope_status: 'suggested',
            activation_mode: 'auto',
            activation_keywords: ['完美世界', '映照身'],
            rules: { foreshadow_only: ['高原诡异只能伏笔'], forbidden_now: [] },
            source_doc_ids: [],
            suggested_scopes: [{ scope_type: 'volume', scope_ref: 'vol_2' }],
            confirmed_scopes: [],
            confidence: 'low',
            is_active: true,
          },
        ],
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: 'domain-1',
            novel_id: 'novel-1',
            name: '完美世界',
            domain_type: 'source_work',
            scope_status: 'confirmed',
            activation_mode: 'auto',
            activation_keywords: ['完美世界', '映照身'],
            rules: { foreshadow_only: ['高原诡异只能伏笔'], forbidden_now: [] },
            source_doc_ids: [],
            suggested_scopes: [{ scope_type: 'volume', scope_ref: 'vol_2' }],
            confirmed_scopes: [{ scope_type: 'volume', scope_ref: 'vol_2' }],
            confidence: 'low',
            is_active: true,
          },
        ],
      })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('规则域')
    expect(wrapper.text()).toContain('完美世界')
    expect(wrapper.text()).toContain('高原诡异只能伏笔')

    const confirmButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '确认用于第2卷')
    await confirmButton.trigger('click')
    await flushPromises()

    expect(confirmKnowledgeDomainScopeMock).toHaveBeenCalledWith('novel-1', 'domain-1', {
      scope_type: 'volume',
      scope_refs: ['vol_2'],
    })
    expect(successMessageMock).toHaveBeenCalledWith('规则域绑定已确认')
  })

  it('places the current library above knowledge domains and opens domain details', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()
    const longRule = `高原诡异只能作为远期伏笔，不允许在第一卷正面登场。${'需要持续保持压迫感。'.repeat(12)}`

    getDocumentLibraryMock.mockResolvedValue({
      items: [
        {
          id: 'world-1',
          doc_type: 'worldview',
          title: '世界观',
          content: '天玄大陆，万族林立。',
          version: 1,
          updated_at: '2026-04-23T00:00:00Z',
          is_active: true,
        },
      ],
      active_style_profile_version: null,
    })
    getKnowledgeDomainsMock.mockResolvedValue({
      items: [
        {
          id: 'domain-1',
          novel_id: 'novel-1',
          name: '完美世界',
          domain_type: 'source_work',
          scope_status: 'suggested',
          activation_mode: 'auto',
          activation_keywords: ['完美世界', '映照身', '高原'],
          rules: { foreshadow_only: [longRule], forbidden_now: [] },
          source_doc_ids: [],
          suggested_scopes: [{ scope_type: 'volume', scope_ref: 'vol_2' }],
          confirmed_scopes: [],
          confidence: 'low',
          is_active: true,
        },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const sectionTitles = wrapper.findAll('h3').map((title) => title.text())
    expect(sectionTitles.indexOf('当前资料库')).toBeLessThan(sectionTitles.indexOf('规则域'))
    expect(wrapper.text()).toContain('只能伏笔：高原诡异只能作为远期伏笔')
    expect(wrapper.text()).not.toContain('需要持续保持压迫感。需要持续保持压迫感。需要持续保持压迫感。')

    const detailButtons = wrapper.findAll('.documents-library-card__edit').filter((button) => button.text() === '查看详情')
    const detailButton = detailButtons[detailButtons.length - 1]
    await detailButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(longRule)
  })

  it('keeps long library content collapsed and opens details in a modal', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()
    const longSynopsis = `开篇主角被卷入宗门危机，随后一路推进。${'中段剧情铺陈。'.repeat(40)}最终揭露幕后真相。`

    getDocumentLibraryMock.mockResolvedValue({
      items: [
        {
          id: 'synopsis-1',
          doc_type: 'synopsis',
          title: '剧情概要',
          content: longSynopsis,
          version: 1,
          updated_at: '2026-04-23T00:00:00Z',
          is_active: true,
        },
      ],
      active_style_profile_version: null,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('开篇主角被卷入宗门危机')
    expect(wrapper.text()).not.toContain('最终揭露幕后真相。')

    const detailButton = wrapper.findAll('.documents-library-card__edit').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('最终揭露幕后真相。')
  })

  it('shows only active style profile by default and moves versions into a secondary modal', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()

    getDocumentLibraryMock.mockResolvedValue({
      items: [
        {
          id: 'style-1',
          doc_type: 'style_profile',
          title: '{"tone":"旧"}',
          content: '旧版文风，不应默认铺开。',
          version: 1,
          updated_at: '2026-04-22T00:00:00Z',
          is_active: false,
          style_config: { tone: '旧' },
        },
        {
          id: 'style-2',
          doc_type: 'style_profile',
          title: '{"tone":"新"}',
          content: '当前文风摘要。',
          version: 2,
          updated_at: '2026-04-23T00:00:00Z',
          is_active: true,
          style_config: { tone: '新', writing_rules: ['短句推进'] },
        },
      ],
      active_style_profile_version: 2,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('当前文风版本 v2')
    expect(wrapper.text()).toContain('当前文风摘要。')
    expect(wrapper.text()).not.toContain('旧版文风，不应默认铺开。')

    const versionsButton = wrapper.findAll('.documents-library-card__edit').find((button) => button.text() === '查看更多版本')
    await versionsButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('旧版文风，不应默认铺开。')
    expect(wrapper.text()).toContain('设为当前版本')
  })

  it('edits a library setting document in a modal and saves it as a new version', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()

    getDocumentLibraryMock
      .mockResolvedValueOnce({
        items: [
          {
            id: 'world-1',
            doc_type: 'worldview',
            title: '世界观',
            content: '旧世界观',
            version: 1,
            updated_at: '2026-04-23T00:00:00Z',
            is_active: true,
          },
        ],
        active_style_profile_version: null,
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: 'world-2',
            doc_type: 'worldview',
            title: '世界观',
            content: '新世界观',
            version: 2,
            updated_at: '2026-04-24T00:00:00Z',
            is_active: true,
          },
        ],
        active_style_profile_version: null,
      })
    updateLibraryDocumentMock.mockResolvedValue({
      item: {
        id: 'world-2',
        doc_type: 'worldview',
        title: '世界观',
        content: '新世界观',
        version: 2,
        updated_at: '2026-04-24T00:00:00Z',
        is_active: true,
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('.documents-library-card__edit').find((button) => button.text() === '编辑')
    expect(editButton.exists()).toBe(true)

    await editButton.trigger('click')
    await nextTick()

    const textarea = wrapper.find('.documents-library-editor__textarea')
    await textarea.setValue('新世界观')

    const saveButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '保存为新版本')
    await saveButton.trigger('click')
    await flushPromises()

    expect(updateLibraryDocumentMock).toHaveBeenCalledWith('novel-1', 'world-1', { content: '新世界观' })
    expect(wrapper.text()).toContain('新世界观')
    expect(successMessageMock).toHaveBeenCalledWith('资料已更新为新版本')
  })

  it('edits a style profile in a modal and promotes the new version', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.fetchDocuments = vi.fn().mockResolvedValue()

    getDocumentLibraryMock
      .mockResolvedValueOnce({
        items: [
          {
            id: 'style-2',
            doc_type: 'style_profile',
            title: '{"tone":"热血"}',
            content: '旧文风',
            version: 2,
            updated_at: '2026-04-23T00:00:00Z',
            is_active: true,
            style_config: { tone: '热血' },
          },
        ],
        active_style_profile_version: 2,
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: 'style-3',
            doc_type: 'style_profile',
            title: '{"tone":"冷峻"}',
            content: '新文风',
            version: 3,
            updated_at: '2026-04-24T00:00:00Z',
            is_active: true,
            style_config: { tone: '冷峻' },
          },
        ],
        active_style_profile_version: 3,
      })
    updateLibraryDocumentMock.mockResolvedValue({
      item: {
        id: 'style-3',
        doc_type: 'style_profile',
        title: '{"tone":"冷峻"}',
        content: '新文风',
        version: 3,
        updated_at: '2026-04-24T00:00:00Z',
        is_active: true,
        style_config: { tone: '冷峻' },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('.documents-library-card__edit').find((button) => button.text() === '编辑')
    await editButton.trigger('click')
    await nextTick()

    const textarea = wrapper.find('.documents-library-editor__textarea')
    await textarea.setValue('新文风')

    const saveButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '保存为新版本')
    await saveButton.trigger('click')
    await flushPromises()

    expect(updateLibraryDocumentMock).toHaveBeenCalledWith('novel-1', 'style-2', { content: '新文风' })
    expect(wrapper.text()).toContain('版本 v3')
    expect(wrapper.text()).toContain('新文风')
    expect(successMessageMock).toHaveBeenCalledWith('文风档案已更新并设为当前版本')
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

  it('applies themed classes to the pending docs table and detail action', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      { id: 'doc-1', source_filename: '力量体系.md', extraction_type: 'processing', status: 'processing', created_at: '2026-04-23T06:27:28Z' },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    const themedTable = wrapper.find('.documents-pending-table')
    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')

    expect(themedTable.exists()).toBe(true)
    expect(detailButton.classes()).toContain('documents-pending-table__action')
    expect(detailButton.attributes('data-type')).toBe('info')
    expect(detailButton.attributes('data-plain')).toBe('true')
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

  it('applies themed classes to detail tables inside the import dialog', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-1',
        source_filename: '设定一.md',
        extraction_type: 'setting',
        status: 'approved',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '2 处变更',
          entity_diffs: [
            {
              entity_type: 'item',
              entity_name: '道经',
              operation: 'update',
              field_changes: [
                { field: 'description', old_value: '旧描述', new_value: '新描述' },
              ],
            },
            {
              entity_type: 'item',
              entity_name: '灵剑',
              operation: 'conflict',
              field_changes: [
                { field: 'owner', old_value: '旧主人', new_value: '新主人', auto_applicable: false },
              ],
            },
          ],
        },
        resolution_result: {
          field_resolutions: [
            { entity_name: '灵剑', field: 'owner', action: 'merge', applied: true },
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

    expect(wrapper.findAll('.documents-detail-table')).toHaveLength(3)
  })

  it('applies themed classes to the detail collapse area inside the import dialog', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-1',
        source_filename: '九重天八界.md',
        extraction_type: 'setting',
        status: 'approved',
        created_at: '2026-04-22T00:00:00Z',
        raw_result: { worlds: ['九重天八界'] },
        proposed_entities: [{ name: '九幽', type: 'location' }],
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await nextTick()

    expect(wrapper.find('.documents-detail-collapse').exists()).toBe(true)
    expect(wrapper.findAll('.documents-detail-collapse__panel')).toHaveLength(2)
  })

  it('edits a created entity field and saves it on Enter', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-1',
        source_filename: '九重天八界.md',
        extraction_type: 'setting',
        status: 'pending',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '1 个新增实体',
          entity_diffs: [
            {
              entity_type: 'character',
              entity_name: '孟奇',
              operation: 'create',
              field_changes: [
                { field: 'identity', label: '身份', old_value: '', new_value: '道经传承者' },
              ],
            },
          ],
        },
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()
    updatePendingDraftFieldMock.mockResolvedValue({
      item: {
        ...store.pendingDocs[0],
        diff_result: {
          summary: '1 个新增实体',
          entity_diffs: [
            {
              entity_type: 'character',
              entity_name: '孟奇',
              operation: 'create',
              field_changes: [
                { field: 'identity', label: '身份', old_value: '', new_value: '彼岸传承者' },
              ],
            },
          ],
        },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await nextTick()

    const editButton = wrapper.find('.documents-draft-field__edit')
    await editButton.trigger('click')
    await nextTick()

    const input = wrapper.find('.documents-draft-field__input')
    await input.setValue('彼岸传承者')
    await input.trigger('keydown.enter')
    await flushPromises()

    expect(updatePendingDraftFieldMock).toHaveBeenCalledWith('novel-1', 'doc-1', {
      entity_type: 'character',
      entity_name: '孟奇',
      field: 'identity',
      value: '彼岸传承者',
    })
    expect(wrapper.text()).toContain('彼岸传承者')
  })

  it('saves the active draft field before approving the pending document', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-significance',
        source_filename: '道经.md',
        extraction_type: 'setting',
        status: 'pending',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '1 个新增实体',
          entity_diffs: [
            {
              entity_type: 'item',
              entity_name: '道经',
              operation: 'create',
              field_changes: [
                { field: 'description', label: '描述', old_value: '', new_value: '核心功法' },
                { field: 'significance', label: '重要性', old_value: '', new_value: '旧的重要性' },
              ],
            },
          ],
        },
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()
    const editedSignificance = '让主角提前获得高阶特征，是核心外挂与正统修炼的象征'
    updatePendingDraftFieldMock.mockResolvedValue({
      item: {
        ...store.pendingDocs[0],
        diff_result: {
          summary: '1 个新增实体',
          entity_diffs: [
            {
              entity_type: 'item',
              entity_name: '道经',
              operation: 'create',
              field_changes: [
                { field: 'description', label: '描述', old_value: '', new_value: '核心功法' },
                { field: 'significance', label: '重要性', old_value: '', new_value: editedSignificance },
              ],
            },
          ],
        },
      },
    })
    approvePendingMock.mockResolvedValue({})

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await nextTick()

    const editButtons = wrapper.findAll('.documents-draft-field__edit')
    await editButtons[1].trigger('click')
    await nextTick()

    await wrapper.find('.documents-draft-field__input').setValue(editedSignificance)
    const approveButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '批准')
    await approveButton.trigger('click')
    await flushPromises()

    expect(updatePendingDraftFieldMock).toHaveBeenCalledWith('novel-1', 'doc-significance', {
      entity_type: 'item',
      entity_name: '道经',
      field: 'significance',
      value: editedSignificance,
    })
    expect(approvePendingMock).toHaveBeenCalledWith('novel-1', 'doc-significance', [])
    expect(updatePendingDraftFieldMock.mock.invocationCallOrder[0]).toBeLessThan(
      approvePendingMock.mock.invocationCallOrder[0]
    )
  })

  it('cancels a draft field edit on Escape without closing the detail content', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-esc',
        source_filename: '九重天八界.md',
        extraction_type: 'setting',
        status: 'pending',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '1 个新增实体',
          entity_diffs: [
            {
              entity_type: 'character',
              entity_name: '孟奇',
              operation: 'create',
              field_changes: [
                { field: 'background', label: '背景', old_value: '', new_value: '古老彼岸者' },
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

    const editButton = wrapper.find('.documents-draft-field__edit')
    await editButton.trigger('click')
    await nextTick()

    expect(wrapper.find('.documents-draft-field__input').exists()).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()

    expect(wrapper.find('.documents-draft-field__input').exists()).toBe(false)
    expect(wrapper.text()).toContain('古老彼岸者')
    expect(wrapper.text()).toContain('增量变更')
    expect(updatePendingDraftFieldMock).not.toHaveBeenCalled()
  })

  it('edits an updated entity field and saves it on Enter', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-2',
        source_filename: '九重天八界.md',
        extraction_type: 'setting',
        status: 'pending',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '1 个可自动补充实体',
          entity_diffs: [
            {
              entity_type: 'location',
              entity_name: '真实界',
              operation: 'update',
              field_changes: [
                { field: 'description', label: '描述', old_value: '旧描述', new_value: '核心世界' },
              ],
            },
          ],
        },
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()
    updatePendingDraftFieldMock.mockResolvedValue({
      item: {
        ...store.pendingDocs[0],
        diff_result: {
          summary: '1 个可自动补充实体',
          entity_diffs: [
            {
              entity_type: 'location',
              entity_name: '真实界',
              operation: 'update',
              field_changes: [
                { field: 'description', label: '描述', old_value: '旧描述', new_value: '核心世界，诸天万界中心' },
              ],
            },
          ],
        },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await nextTick()

    const editButtons = wrapper.findAll('.documents-draft-field__edit')
    await editButtons[0].trigger('click')
    await nextTick()

    const input = wrapper.find('.documents-draft-field__input')
    await input.setValue('核心世界，诸天万界中心')
    await input.trigger('keydown.enter')
    await flushPromises()
    await nextTick()

    expect(updatePendingDraftFieldMock).toHaveBeenCalledWith('novel-1', 'doc-2', {
      entity_type: 'location',
      entity_name: '真实界',
      field: 'description',
      value: '核心世界，诸天万界中心',
    })
    expect(wrapper.vm.selectedDoc.diff_result.entity_diffs[0].field_changes[0].new_value).toBe('核心世界，诸天万界中心')
    expect(store.pendingDocs[0].diff_result.entity_diffs[0].field_changes[0].new_value).toBe('核心世界，诸天万界中心')
  })

  it('edits a conflicting entity new value and saves it on Enter', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      {
        id: 'doc-3',
        source_filename: '九重天八界.md',
        extraction_type: 'setting',
        status: 'pending',
        created_at: '2026-04-22T00:00:00Z',
        diff_result: {
          summary: '1 个冲突实体',
          entity_diffs: [
            {
              entity_type: 'item',
              entity_name: '道经',
              operation: 'conflict',
              field_changes: [
                { field: 'description', label: '描述', old_value: '旧描述', new_value: '新描述', auto_applicable: false },
              ],
            },
          ],
        },
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()
    updatePendingDraftFieldMock.mockResolvedValue({
      item: {
        ...store.pendingDocs[0],
        diff_result: {
          summary: '1 个冲突实体',
          entity_diffs: [
            {
              entity_type: 'item',
              entity_name: '道经',
              operation: 'conflict',
              field_changes: [
                { field: 'description', label: '描述', old_value: '旧描述', new_value: '融合后的新描述', auto_applicable: false },
              ],
            },
          ],
        },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '查看详情')
    await detailButton.trigger('click')
    await nextTick()

    const editButtons = wrapper.findAll('.documents-draft-field__edit')
    await editButtons[0].trigger('click')
    await nextTick()

    const input = wrapper.find('.documents-draft-field__input')
    await input.setValue('融合后的新描述')
    await input.trigger('keydown.enter')
    await flushPromises()

    expect(updatePendingDraftFieldMock).toHaveBeenCalledWith('novel-1', 'doc-3', {
      entity_type: 'item',
      entity_name: '道经',
      field: 'description',
      value: '融合后的新描述',
    })
    expect(wrapper.vm.selectedDoc.diff_result.entity_diffs[0].field_changes[0].new_value).toBe('融合后的新描述')
  })

  it('shows delete for failed rows and removes the record after deletion', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      { id: 'doc-failed', source_filename: '诸天万界.md', extraction_type: 'setting', status: 'failed', created_at: '2026-04-23T09:43:45Z' },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()
    deletePendingDocMock.mockResolvedValue({})

    const wrapper = mountView()
    await flushPromises()

    const deleteButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '删除')
    expect(deleteButton).toBeTruthy()

    await deleteButton.trigger('click')
    await flushPromises()

    expect(deletePendingDocMock).toHaveBeenCalledWith('novel-1', 'doc-failed')
    expect(store.fetchDocuments).toHaveBeenCalled()
    expect(successMessageMock).toHaveBeenCalledWith('已删除失败记录')
  })

  it('shows cancel for processing rows and removes the record after cancellation', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = [
      { id: 'doc-processing', source_filename: '完美世界.md', extraction_type: 'processing', status: 'processing', created_at: '2026-04-25T07:45:00Z' },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()
    deletePendingDocMock.mockResolvedValue({})

    const wrapper = mountView()
    await flushPromises()

    const cancelButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '取消')
    expect(cancelButton).toBeTruthy()

    await cancelButton.trigger('click')
    await flushPromises()

    expect(deletePendingDocMock).toHaveBeenCalledWith('novel-1', 'doc-processing')
    expect(store.fetchDocuments).toHaveBeenCalled()
    expect(successMessageMock).toHaveBeenCalledWith('已取消导入')
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

  it('confirms and deletes a knowledge domain with its local documents and entities', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.pendingDocs = []
    store.knowledgeDomains = [
      {
        id: 'domain-1',
        name: '仙逆',
        is_active: true,
        scope_status: 'confirmed',
        activation_mode: 'auto',
        activation_keywords: ['仙逆'],
        suggested_scopes: [],
        confirmed_scopes: [],
        rules: {},
      },
    ]
    store.fetchDocuments = vi.fn().mockResolvedValue()
    store.fetchKnowledgeDomains = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    const deleteButton = wrapper.findAll('.el-button-stub').find((button) => button.text() === '删除')
    expect(deleteButton).toBeTruthy()
    await deleteButton.trigger('click')
    await flushPromises()

    expect(confirmMessageBoxMock).toHaveBeenCalledWith(
      expect.stringContaining('仙逆'),
      '删除规则域',
      expect.objectContaining({ type: 'warning' })
    )
    expect(deleteKnowledgeDomainMock).toHaveBeenCalledWith('novel-1', 'domain-1')
    expect(store.fetchDocuments).toHaveBeenCalled()
    expect(store.fetchKnowledgeDomains).toHaveBeenCalledWith(true)
    expect(successMessageMock).toHaveBeenCalledWith('规则域已删除，已清理 2 份局部文档、3 个局部实体')
  })
})
