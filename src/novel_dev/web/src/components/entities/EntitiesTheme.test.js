import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
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
})
