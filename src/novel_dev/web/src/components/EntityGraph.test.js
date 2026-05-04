import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { vi } from 'vitest'
import { describe, expect, it } from 'vitest'
import EntityGraph from './EntityGraph.vue'

vi.mock('vue-echarts', () => ({
  default: defineComponent({
    name: 'VChartStub',
    props: {
      option: { type: Object, default: () => ({}) },
    },
    setup(props) {
      return () => h('div', {
        class: 'v-chart-stub',
        'data-series-count': String(props.option?.series?.length || 0),
      })
    },
  }),
}))

describe('EntityGraph', () => {
  it('builds a high-contrast graph option for clearer relationship rendering', () => {
    const wrapper = mount(EntityGraph, {
      props: {
        entities: [
          { entity_id: 'hero', name: '陆照', type: 'character', current_version: 2 },
          {
            entity_id: 'manual',
            name: '道经',
            type: 'item',
            current_version: 1,
            effective_category: '功法',
          },
        ],
        relationships: [
          { source_id: 'hero', target_id: 'manual', relation_type: '持有' },
        ],
      },
      global: { stubs: { ElButton: true } },
    })

    const option = wrapper.vm.option
    const series = option.series[0]

    expect(option.legend[0].data).toEqual(['人物', '功法'])
    expect(series.label.fontWeight).toBe(700)
    expect(series.lineStyle.width).toBe(2)
    expect(series.edgeLabel.backgroundColor).toBe('rgba(255,255,255,0.92)')
    expect(series.emphasis.focus).toBe('adjacency')
    expect(series.blur.lineStyle.opacity).toBe(0.15)
    expect(series.edgeSymbol).toEqual(['none', 'arrow'])
    expect(series.data[0].itemStyle.borderWidth).toBe(3)
    expect(series.data[0].symbolSize).toBeGreaterThan(40)
    expect(series.data[1].category).toBe('功法')
    expect(series.data[1].itemStyle.color).toBe('#7c3aed')
    expect(series.categories[1].itemStyle.color).toBe('#7c3aed')
  })

  it('renders an empty state when graph data is incomplete', () => {
    const wrapper = mount(EntityGraph, {
      props: {
        entities: [{ entity_id: 'hero', name: '陆照', type: 'character' }],
        relationships: [],
      },
      global: { stubs: { ElButton: true } },
    })

    expect(wrapper.text()).toContain('暂无关系图谱数据')
  })

  it('uses entity ids as graph node keys when display names are duplicated', () => {
    const wrapper = mount(EntityGraph, {
      props: {
        entities: [
          { entity_id: 'dao-local', name: '道经', type: 'item', effective_category: '功法' },
          { entity_id: 'dao-domain', name: '道经', type: 'item', effective_category: '功法' },
          { entity_id: 'mengqi', name: '孟奇', type: 'character', effective_category: '人物' },
        ],
        relationships: [
          { source_id: 'mengqi', target_id: 'dao-local', relation_type: '关联' },
        ],
      },
      global: { stubs: { ElButton: true } },
    })

    const series = wrapper.vm.option.series[0]
    expect(series.data.map((node) => node.name)).toEqual(['dao-local', 'dao-domain', 'mengqi'])
    expect(series.data.map((node) => node.displayName)).toEqual(['道经', '道经', '孟奇'])
    expect(series.label.formatter({ data: series.data[0] })).toBe('道经')
    expect(series.links[0]).toMatchObject({
      source: 'mengqi',
      target: 'dao-local',
      sourceName: '孟奇',
      targetName: '道经',
    })
  })
})
