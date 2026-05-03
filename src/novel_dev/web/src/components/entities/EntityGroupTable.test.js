import { defineComponent, h, inject, provide } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EntityGroupTable from './EntityGroupTable.vue'

const stubs = {
  ElEmpty: defineComponent({
    name: 'ElEmptyStub',
    props: { description: { type: String, default: '' } },
    setup(props) {
      return () => h('div', { class: 'el-empty-stub' }, props.description)
    },
  }),
  ElTable: defineComponent({
    name: 'ElTableStub',
    props: { data: { type: Array, default: () => [] } },
    setup(props, { slots }) {
      provide('el-table-rows', props.data)
      return () => h('div', { class: 'el-table-stub' }, slots.default?.())
    },
  }),
  ElTableColumn: defineComponent({
    name: 'ElTableColumnStub',
    props: {
      prop: { type: String, default: '' },
      label: { type: String, default: '' },
    },
    setup(props, { slots }) {
      const rows = inject('el-table-rows', [])
      return () => h('div', { class: 'el-table-column-stub', 'data-label': props.label }, rows.map((row, index) =>
        h('div', { class: 'el-table-row-stub', key: `${props.label}-${index}` }, slots.default?.({ row }) ?? row?.[props.prop] ?? '')
      ))
    },
  }),
  ElTag: defineComponent({
    name: 'ElTagStub',
    setup(_, { slots }) {
      return () => h('span', { class: 'el-tag-stub' }, slots.default?.())
    },
  }),
  ElButton: defineComponent({
    name: 'ElButtonStub',
    emits: ['click'],
    setup(_, { attrs, emit, slots }) {
      return () => h('button', {
        ...attrs,
        class: ['el-button-stub', attrs.class],
        disabled: attrs.disabled,
        onClick: event => emit('click', event),
      }, slots.default?.())
    },
  }),
  ElSelect: defineComponent({
    name: 'ElSelectStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-select-stub' }, slots.default?.())
    },
  }),
  ElOption: defineComponent({
    name: 'ElOptionStub',
    setup() {
      return () => h('div', { class: 'el-option-stub' })
    },
  }),
  ElPagination: defineComponent({
    name: 'ElPagination',
    props: {
      currentPage: { type: Number, default: 1 },
      pageSize: { type: Number, default: 20 },
      total: { type: Number, default: 0 },
    },
    emits: ['update:current-page'],
    setup(props, { emit }) {
      return () => h('button', {
        class: 'entity-pagination-stub',
        onClick: () => emit('update:current-page', 2),
      }, `page ${props.currentPage} / ${props.total}`)
    },
  }),
}

function buildItems(count) {
  return Array.from({ length: count }, (_, index) => ({
    entity_id: `entity-${index + 1}`,
    name: `实体 ${index + 1}`,
    classification_status: 'auto',
    system_category: '人物',
    system_group_name: '测试',
    latest_state: {},
  }))
}

describe('EntityGroupTable pagination', () => {
  it('shows 20 entities per page and switches pages locally', async () => {
    const wrapper = mount(EntityGroupTable, {
      props: {
        items: buildItems(45),
        totalCount: 45,
      },
      global: { stubs },
    })

    expect(wrapper.findComponent({ name: 'ElPagination' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ElTableStub' }).props('data').map(item => item.entity_id)).toEqual(
      buildItems(20).map(item => item.entity_id)
    )

    await wrapper.find('.entity-pagination-stub').trigger('click')

    expect(wrapper.findComponent({ name: 'ElTableStub' }).props('data').map(item => item.entity_id)).toEqual(
      buildItems(45).slice(20, 40).map(item => item.entity_id)
    )
  })

  it('does not render pagination for one page of entities', () => {
    const wrapper = mount(EntityGroupTable, {
      props: {
        items: buildItems(20),
        totalCount: 20,
      },
      global: { stubs },
    })

    expect(wrapper.findComponent({ name: 'ElPagination' }).exists()).toBe(false)
  })

  it('can jump directly to first and last page', async () => {
    const wrapper = mount(EntityGroupTable, {
      props: {
        items: buildItems(45),
        totalCount: 45,
      },
      global: { stubs },
    })
    const table = () => wrapper.findComponent({ name: 'ElTableStub' })

    expect(wrapper.find('[data-testid="entity-first-page"]').attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="entity-last-page"]').trigger('click')

    expect(table().props('data').map(item => item.entity_id)).toEqual(
      buildItems(45).slice(40, 45).map(item => item.entity_id)
    )
    expect(wrapper.find('[data-testid="entity-last-page"]').attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="entity-first-page"]').trigger('click')

    expect(table().props('data').map(item => item.entity_id)).toEqual(
      buildItems(20).map(item => item.entity_id)
    )
  })
})
