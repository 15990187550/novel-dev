import { defineComponent, h, inject, provide } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import Entities from './Entities.vue'
import { ElMessageBox } from 'element-plus'

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessageBox: {
      confirm: vi.fn(),
    },
  }
})

const EntityTreeStub = defineComponent({
  name: 'EntityTreeStub',
  props: {
    nodes: { type: Array, default: () => [] },
  },
  emits: ['select'],
  setup(props, { emit }) {
    function renderNode(node) {
      return [
        h(
          'button',
          {
            class: 'tree-node-button',
            type: 'button',
            'data-node-id': node.id,
            onClick: () => emit('select', node),
          },
          node.label
        ),
        ...(node.children || []).flatMap(renderNode),
      ]
    }

    return () =>
      h('div', { class: 'entity-tree-stub' }, [
        props.nodes.flatMap(renderNode),
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
  emits: ['save-entity', 'delete-entity'],
  setup(props, { emit }) {
    return () => h('div', { class: 'entity-detail-panel-stub' }, [
      h('div', props.entity?.name || 'empty'),
      h('button', {
        class: 'save-entity-button',
        type: 'button',
        onClick: () => emit('save-entity', props.entity, {
          name: '林风',
          type: props.entity?.type || 'character',
          aliases: ['Lin Feng'],
          state_fields: {
            identity: '主角',
          },
        }),
      }, 'save-entity'),
      h('button', {
        class: 'delete-entity-button',
        type: 'button',
        onClick: () => emit('delete-entity', props.entity),
      }, 'delete-entity'),
    ])
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
    store.updateEntity = vi.fn().mockResolvedValue()
    store.deleteEntity = vi.fn().mockResolvedValue()
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
      {
        id: 'category:法宝神兵',
        label: '法宝神兵',
        nodeType: 'category',
        entityCount: 1,
        children: [
          {
            id: 'group:法宝神兵:常用',
            label: '常用',
            nodeType: 'group',
            entityCount: 1,
            children: [
              {
                id: 'entity:jade',
                label: '护身玉佩',
                nodeType: 'entity',
                entityId: 'jade',
                data: { entity_id: 'jade', name: '护身玉佩' },
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
      { entity_id: 'jade', name: '护身玉佩' },
    ]
    store.entityRelationships = [
      { source_id: 'lu', target_id: 'yao', relation_type: '盟友' },
      { source_id: 'lu', target_id: 'han', relation_type: '宿敌' },
      { source_id: 'yao', target_id: 'han', relation_type: '对手' },
      { source_id: 'jade', target_id: 'lu', relation_type: '持有' },
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

  it('adds the local entities theme scope on the page root', () => {
    seedStore()
    const wrapper = mountView()

    expect(wrapper.find('.entities-page').exists()).toBe(true)
    expect(wrapper.find('.entities-page').classes()).toContain('entities-theme')
  })

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
    expect(fullGraph.attributes('data-entities')).toBe('lu,yao,han,jade')
    expect(fullGraph.attributes('data-relationships')).toBe('lu->yao,lu->han,yao->han,jade->lu')

    await wrapper.find('.tree-node-button').trigger('click')

    const scopedGraph = wrapper.find('.entity-graph-stub')
    expect(scopedGraph.attributes('data-entities')).toBe('lu,yao,han,jade')
    expect(scopedGraph.attributes('data-relationships')).toBe('lu->yao,lu->han,yao->han,jade->lu')
  })

  it('includes one-hop cross-category relationships when a category is selected in graph view', async () => {
    seedStore()
    const wrapper = mountView()

    await Promise.resolve()
    await wrapper.find('[data-label="graph"]').trigger('click')
    await wrapper.find('[data-node-id="category:法宝神兵"]').trigger('click')

    const scopedGraph = wrapper.find('.entity-graph-stub')
    expect(scopedGraph.attributes('data-entities')).toBe('lu,jade')
    expect(scopedGraph.attributes('data-relationships')).toBe('jade->lu')
  })

  it('updates the selected entity from the detail panel action', async () => {
    const store = seedStore()
    const wrapper = mountView()

    await Promise.resolve()
    await wrapper.find('[data-node-id="entity:lu"]').trigger('click')
    await wrapper.find('.save-entity-button').trigger('click')

    expect(store.updateEntity).toHaveBeenCalledWith('lu', {
      name: '林风',
      type: 'character',
      aliases: ['Lin Feng'],
      state_fields: {
        identity: '主角',
      },
    })
  })

  it('asks for confirmation before deleting the selected entity', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue()
    const store = seedStore()
    const wrapper = mountView()

    await Promise.resolve()
    await wrapper.find('[data-node-id="entity:lu"]').trigger('click')
    await wrapper.find('.delete-entity-button').trigger('click')

    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1)
    expect(store.deleteEntity).toHaveBeenCalledWith('lu')
  })
})
