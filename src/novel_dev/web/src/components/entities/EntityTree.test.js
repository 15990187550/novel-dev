import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import EntityTree from './EntityTree.vue'

const ElTreeStub = defineComponent({
  name: 'ElTreeStub',
  props: {
    data: { type: Array, default: () => [] },
    defaultExpandedKeys: { type: Array, default: undefined },
    defaultExpandAll: { type: Boolean, default: undefined },
  },
  setup(props, { slots }) {
    const renderNode = (node) => h('div', { class: 'tree-node', 'data-node-id': node.id }, slots.default?.({ data: node }))
    const renderTree = (nodes) => nodes.flatMap((node) => [renderNode(node), ...(node.children ? renderTree(node.children) : [])])
    return () => h('div', { class: 'el-tree-stub' }, renderTree(props.data))
  },
})

describe('EntityTree', () => {
  const nodes = [
    {
      id: 'category:other',
      label: '其他',
      nodeType: 'category',
      entityCount: 2,
      children: [
        {
          id: 'group:other:ungrouped',
          label: '未分组',
          nodeType: 'group',
          groupSlug: 'ungrouped',
          entityCount: 2,
          children: [
            {
              id: 'entity:1',
              label: '《冰心诀》',
              nodeType: 'entity',
              entityId: 'entity-1',
              data: {
                entity_id: 'entity-1',
                effective_group_name: '未分组',
                effective_category: '其他',
              },
            },
          ],
        },
      ],
    },
  ]

  function mountTree() {
    return mount(EntityTree, {
      props: {
        nodes,
        totalCount: 2,
        treeNodeCount: 3,
      },
      global: {
        stubs: {
          ElTree: ElTreeStub,
          ElInput: defineComponent({
            name: 'ElInputStub',
            setup(_, { slots }) {
              return () => h('div', { class: 'el-input-stub' }, slots.append?.())
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
          ElEmpty: true,
        },
        directives: {
          loading: () => {},
        },
      },
    })
  }

  it('uses targeted default expansion instead of expanding the full tree', () => {
    const wrapper = mountTree()
    const tree = wrapper.findComponent(ElTreeStub)

    expect(tree.props('defaultExpandAll')).not.toBe(true)
    expect(tree.props('defaultExpandedKeys')).toEqual(['category:other'])
  })

  it('keeps the catalog card full-height while only the tree body scrolls', () => {
    const wrapper = mountTree()

    expect(wrapper.classes()).toEqual(expect.arrayContaining(['h-full', 'min-h-0', 'flex', 'flex-col', 'overflow-hidden']))
    expect(wrapper.get('[data-testid="entity-tree-scroll"]').classes()).toEqual(expect.arrayContaining([
      'min-h-0',
      'flex-1',
      'overflow-auto',
    ]))
  })

  it('contains wheel scrolling inside the tree body', () => {
    const source = fs.readFileSync(path.resolve(__dirname, './EntityTree.vue'), 'utf8')

    expect(source).toMatch(/\.entity-tree__scroll\s*{[\s\S]*overscroll-behavior:\s*contain;/)
    expect(source).toMatch(/\.entity-tree__scroll\s*{[\s\S]*scrollbar-gutter:\s*stable;/)
  })

  it('does not render internal group slugs in the group subtitle', () => {
    const wrapper = mountTree()

    expect(wrapper.text()).toContain('一级分类')
    expect(wrapper.text()).not.toContain('ungrouped')
    expect(wrapper.text()).not.toContain('二级分组 · ungrouped')
  })
})
