import { defineComponent, h, inject, provide } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import EntityDetailPanel from './EntityDetailPanel.vue'
import EntityGroupTable from './EntityGroupTable.vue'
import EntityTree from './EntityTree.vue'

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
      return () => h('div', { class: 'el-table-column-stub', 'data-label': props.label }, rows.length
        ? rows.map((row, index) => h('div', { class: 'el-table-row-stub', key: `${props.prop || props.label || index}-${index}` }, slots.default?.({ row }) ?? row?.[props.prop] ?? ''))
        : [h('div', { class: 'el-table-row-stub' }, slots.default?.({ row: {} }) ?? '')])
    },
  }),
  ElSelect: defineComponent({
    name: 'ElSelectStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-select-stub' }, slots.default?.())
    },
  }),
  ElAlert: defineComponent({
    name: 'ElAlertStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-alert-stub' }, slots.default?.())
    },
  }),
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
  ElDialog: defineComponent({
    name: 'ElDialogStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'el-dialog-stub' }, slots.default?.())
    },
  }),
  ElOption: defineComponent({
    name: 'ElOptionStub',
    setup() {
      return () => h('div', { class: 'el-option-stub' })
    },
  }),
  ElPagination: defineComponent({
    name: 'ElPaginationStub',
    setup() {
      return () => h('div', { class: 'el-pagination-stub' })
    },
  }),
}

describe('entities theme classes', () => {
  it('defines light entity tokens and dark-mode overrides', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../../style.css'), 'utf8')

    expect(css).toMatch(/\.entities-theme\s*{[\s\S]*--entities-panel-bg:\s*rgba\(255,\s*255,\s*255,/)
    expect(css).toMatch(/html\.dark\s+\.entities-theme\s*{[\s\S]*--entities-panel-bg:\s*rgba\(11,\s*20,\s*35,/)
  })

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

  it('renders themeable classes for the entity group table controls', () => {
    const wrapper = mount(EntityGroupTable, {
      props: {
        items: [
          {
            entity_id: 'e1',
            name: '陆照',
            classification_status: 'needs_review',
            system_category: '人物',
            system_group_name: '主角阵营',
            latest_state: {},
          },
          {
            entity_id: 'e2',
            name: '沈青',
            classification_status: 'manual_override',
            system_category: '势力',
            system_group_name: '宗门',
            classification_reason: { source: 'manual' },
            latest_state: { description: '宗门执事' },
          },
        ],
      },
      global: { stubs: simpleStubs },
    })

    expect(wrapper.find('.entity-group-table__table').exists()).toBe(true)
    expect(wrapper.findAll('.entity-group-table__quick-actions')).toHaveLength(2)
    expect(wrapper.findAll('.entity-group-table__select')).toHaveLength(4)
    expect(wrapper.findAll('.entity-group-table__subtext')).toHaveLength(4)
    expect(wrapper.findAll('.entity-group-table__summary')).toHaveLength(2)
  })

  it('renders themeable classes for the detail panel sections', () => {
    const wrapper = mount(EntityDetailPanel, {
      props: {
        title: '实体详情',
        entity: {
          entity_id: 'e1',
          name: '陆照',
          type: 'character',
          classification_status: 'manual_override',
          classification_reason: { reason: 'entity_type_match' },
          latest_state: { identity: '主角' },
        },
        relationships: [
          {
            source_id: 'e1',
            target_id: 'e2',
            relation_type: '师徒',
            is_inferred: false,
          },
        ],
      },
      global: { stubs: simpleStubs },
    })

    expect(wrapper.find('.entity-detail-panel__override').exists()).toBe(true)
    expect(wrapper.find('.entity-detail-panel__reason').exists()).toBe(true)
    expect(wrapper.find('.entity-detail-panel__descriptions').exists()).toBe(true)
    expect(wrapper.findAll('.entity-detail-panel__select')).toHaveLength(2)
    expect(wrapper.find('.entity-detail-panel__relation').exists()).toBe(true)
    expect(wrapper.find('.entity-detail-panel__relation-detail').exists()).toBe(true)
    expect(wrapper.findAll('.entity-detail-panel__payload').length).toBeGreaterThanOrEqual(2)
  })
})
