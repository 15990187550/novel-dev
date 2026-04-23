import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EntityTree from './EntityTree.vue'
import EntityGroupTable from './EntityGroupTable.vue'
import EntityDetailPanel from './EntityDetailPanel.vue'

const simpleStubs = {
  ElInput: defineComponent({
    name: 'ElInputStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-input-stub' }, [slots.prepend?.(), slots.append?.()])
    },
  }),
  ElButton: defineComponent({
    name: 'ElButtonStub',
    setup(_, { slots }) {
      return () => h('button', { class: 'el-button-stub' }, slots.default?.())
    },
  }),
  ElTag: defineComponent({
    name: 'ElTagStub',
    setup(_, { slots }) {
      return () => h('span', { class: 'el-tag-stub' }, slots.default?.())
    },
  }),
  ElEmpty: defineComponent({
    name: 'ElEmptyStub',
    props: { description: { type: String, default: '' } },
    setup(props) {
      return () => h('div', { class: 'el-empty-stub' }, props.description)
    },
  }),
  ElTree: defineComponent({
    name: 'ElTreeStub',
    props: { data: { type: Array, default: () => [] } },
    setup(props, { slots }) {
      const renderNode = (node) => h('div', { class: 'tree-node' }, slots.default?.({ data: node }))
      return () => h('div', { class: 'el-tree-stub' }, props.data.map(renderNode))
    },
  }),
  ElTable: defineComponent({
    name: 'ElTableStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-table-stub' }, slots.default?.())
    },
  }),
  ElTableColumn: defineComponent({
    name: 'ElTableColumnStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-table-column-stub' }, slots.default?.({ row: {} }))
    },
  }),
  ElSelect: defineComponent({
    name: 'ElSelectStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-select-stub' }, slots.default?.())
    },
  }),
  ElOption: true,
  ElDescriptions: defineComponent({
    name: 'ElDescriptionsStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-descriptions-stub' }, slots.default?.())
    },
  }),
  ElDescriptionsItem: defineComponent({
    name: 'ElDescriptionsItemStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-descriptions-item-stub' }, slots.default?.())
    },
  }),
  ElAlert: defineComponent({
    name: 'ElAlertStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-alert-stub' }, slots.default?.())
    },
  }),
  ElDialog: defineComponent({
    name: 'ElDialogStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-dialog-stub' }, slots.default?.())
    },
  }),
}

describe('entities theme classes', () => {
  it('applies themed surface class to entity tree', () => {
    const wrapper = mount(EntityTree, {
      props: {
        nodes: [{ id: 'category:1', label: '人物', nodeType: 'category', entityCount: 1 }],
        totalCount: 1,
        treeNodeCount: 1,
      },
      global: {
        stubs: simpleStubs,
        directives: { loading: () => {} },
      },
    })

    expect(wrapper.classes()).toContain('surface-card')
    expect(wrapper.classes()).toContain('entity-tree')
  })

  it('renders themeable badge classes in the entity tree', () => {
    const wrapper = mount(EntityTree, {
      props: {
        nodes: [{
          id: 'category:1',
          label: '人物',
          nodeType: 'category',
          entityCount: 2,
          needsReviewCount: 1,
        }],
        totalCount: 2,
        treeNodeCount: 1,
      },
      global: {
        stubs: simpleStubs,
        directives: { loading: () => {} },
      },
    })

    expect(wrapper.find('.entity-tree__badge').exists()).toBe(true)
    expect(wrapper.find('.entity-tree__badge--warning').exists()).toBe(true)
    expect(wrapper.find('.entity-tree__search').exists()).toBe(true)
  })

  it('applies themed table class to entity group table', () => {
    const wrapper = mount(EntityGroupTable, {
      props: {
        items: [{ entity_id: 'e1', name: '陆照', classification_status: 'auto', latest_state: {} }],
      },
      global: {
        stubs: simpleStubs,
      },
    })

    expect(wrapper.classes()).toContain('surface-card')
    expect(wrapper.find('.entity-group-table__table').exists()).toBe(true)
  })

  it('applies themed description and dialog classes to entity detail panel', () => {
    const wrapper = mount(EntityDetailPanel, {
      props: {
        title: '实体详情',
        entity: {
          entity_id: 'e1',
          name: '陆照',
          type: 'character',
          classification_status: 'auto',
          latest_state: { identity: '主角' },
        },
        relationships: [],
      },
      global: {
        stubs: simpleStubs,
      },
    })

    expect(wrapper.classes()).toContain('surface-card')
    expect(wrapper.find('.entity-detail-panel__descriptions').exists()).toBe(true)
    expect(wrapper.find('.entity-detail-panel__section').exists()).toBe(true)
  })
})
