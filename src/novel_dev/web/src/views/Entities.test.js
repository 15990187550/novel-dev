import { defineComponent, h, inject, provide } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import Entities from './Entities.vue'

const EntityTreeStub = defineComponent({
  name: 'EntityTreeStub',
  props: {
    nodes: { type: Array, default: () => [] },
  },
  emits: ['select'],
  setup(props, { emit }) {
    return () =>
      h('div', { class: 'entity-tree-stub' }, [
        props.nodes.map((node) =>
          h(
            'button',
            {
              class: 'tree-node-button',
              type: 'button',
              onClick: () => emit('select', node),
            },
            node.label
          )
        ),
      ])
  },
})

const EntityGroupTableStub = defineComponent({
  name: 'EntityGroupTableStub',
  props: {
    title: { type: String, default: '' },
    items: { type: Array, default: () => [] },
  },
  setup(props) {
    return () => h('div', { class: 'entity-group-table-stub' }, `${props.title}:${props.items.length}`)
  },
})

const EntityDetailPanelStub = defineComponent({
  name: 'EntityDetailPanelStub',
  props: {
    entity: { type: Object, default: null },
  },
  setup(props) {
    return () => h('div', { class: 'entity-detail-panel-stub' }, props.entity?.name || 'empty')
  },
})

const EntityGraphStub = defineComponent({
  name: 'EntityGraphStub',
  props: {
    entities: { type: Array, default: () => [] },
    relationships: { type: Array, default: () => [] },
  },
  setup(props) {
    return () =>
      h(
        'div',
        {
          class: 'entity-graph-stub',
          'data-entities': props.entities.map((item) => item.entity_id).join(','),
          'data-relationships': props.relationships.map((item) => `${item.source_id}->${item.target_id}`).join(','),
        },
        'graph'
      )
  },
})

describe('Entities', () => {
  const radioGroupKey = Symbol('radio-group')
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
  })

  function seedStore() {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.fetchEntities = vi.fn().mockResolvedValue()
    store.entityTree = [
      {
        id: 'category:人物',
        label: '人物',
        nodeType: 'category',
        entityCount: 2,
        children: [
          {
            id: 'group:人物:主角阵营',
            label: '主角阵营',
            nodeType: 'group',
            entityCount: 2,
            children: [
              {
                id: 'entity:lu',
                label: '陆照',
                nodeType: 'entity',
                entityId: 'lu',
                data: { entity_id: 'lu', name: '陆照' },
              },
              {
                id: 'entity:yao',
                label: '妖妖',
                nodeType: 'entity',
                entityId: 'yao',
                data: { entity_id: 'yao', name: '妖妖' },
              },
            ],
          },
        ],
      },
    ]
    store.entities = [
      { entity_id: 'lu', name: '陆照' },
      { entity_id: 'yao', name: '妖妖' },
      { entity_id: 'han', name: '韩广' },
    ]
    store.entityRelationships = [
      { source_id: 'lu', target_id: 'yao', relation_type: '盟友' },
      { source_id: 'lu', target_id: 'han', relation_type: '宿敌' },
      { source_id: 'yao', target_id: 'han', relation_type: '对手' },
    ]
    return store
  }

  function mountView() {
    return mount(Entities, {
      global: {
        plugins: [pinia],
        stubs: {
          EntityTree: EntityTreeStub,
          EntityGroupTable: EntityGroupTableStub,
          EntityDetailPanel: EntityDetailPanelStub,
          EntityGraph: EntityGraphStub,
          ElAlert: true,
          ElEmpty: defineComponent({
            name: 'ElEmptyStub',
            props: { description: { type: String, default: '' } },
            setup(props) {
              return () => h('div', { class: 'el-empty-stub' }, props.description)
            },
          }),
          ElDialog: defineComponent({
            name: 'ElDialogStub',
            setup(_, { slots }) {
              return () => h('div', { class: 'el-dialog-stub' }, slots.default?.())
            },
          }),
          ElRadioGroup: defineComponent({
            name: 'ElRadioGroupStub',
            props: { modelValue: { type: String, default: '' } },
            emits: ['update:modelValue'],
            setup(props, { emit, slots }) {
              provide(radioGroupKey, {
                select: (label) => emit('update:modelValue', label),
                isSelected: (label) => props.modelValue === label,
              })
              return () => h('div', { class: 'el-radio-group-stub' }, slots.default?.())
            },
          }),
          ElRadioButton: defineComponent({
            name: 'ElRadioButtonStub',
            props: { label: { type: String, default: '' } },
            setup(props, { slots }) {
              const group = inject(radioGroupKey, null)
              return () =>
                h(
                  'button',
                  {
                    class: 'el-radio-button-stub',
                    'data-label': props.label,
                    'data-selected': group?.isSelected(props.label) ? 'true' : 'false',
                    onClick: () => group?.select(props.label),
                  },
                  slots.default?.() || props.label
                )
            },
          }),
        },
      },
    })
  }

  it('shows an empty workspace until the user selects a node', async () => {
    seedStore()
    const wrapper = mountView()

    await Promise.resolve()

    expect(wrapper.text()).toContain('请先从左侧目录选择一个分类、分组或实体')
    expect(wrapper.find('.entity-group-table-stub').exists()).toBe(false)
    expect(wrapper.find('.entity-detail-panel-stub').exists()).toBe(false)
  })

  it('filters the graph by the current selection and falls back to full graph without selection', async () => {
    seedStore()
    const wrapper = mountView()

    await Promise.resolve()

    const initialGraph = wrapper.find('.entity-graph-stub')
    expect(initialGraph.exists()).toBe(false)

    await wrapper.find('[data-label="graph"]').trigger('click')

    const fullGraph = wrapper.find('.entity-graph-stub')
    expect(fullGraph.attributes('data-entities')).toBe('lu,yao,han')
    expect(fullGraph.attributes('data-relationships')).toBe('lu->yao,lu->han,yao->han')

    await wrapper.find('.tree-node-button').trigger('click')

    const scopedGraph = wrapper.find('.entity-graph-stub')
    expect(scopedGraph.attributes('data-entities')).toBe('lu,yao')
    expect(scopedGraph.attributes('data-relationships')).toBe('lu->yao')
  })
})
