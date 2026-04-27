import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ChapterProgressGantt from './ChapterProgressGantt.vue'

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    props: ['option'],
    template: '<div class="v-chart-stub" />',
  },
}))

describe('ChapterProgressGantt', () => {
  it('uses score values and hides unscored chapters in score mode', () => {
    const wrapper = mount(ChapterProgressGantt, {
      props: {
        mode: 'score',
        chapters: [
          {
            chapter_id: 'ch-1',
            chapter_number: 1,
            title: '第一章',
            statusLabel: '已审稿',
            displayScore: 82,
            scoreDetail: '节奏稳定',
          },
          {
            chapter_id: 'ch-2',
            chapter_number: 2,
            title: '第二章',
            statusLabel: '待处理',
          },
        ],
      },
    })

    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.yAxis.name).toBe('评分')
    expect(option.yAxis.max).toBe(100)
    expect(option.xAxis.data).toEqual(['第1章'])
    expect(option.series[0].data[0].value).toBe(82)
    expect(option.tooltip.formatter([{ dataIndex: 0 }])).toContain('节奏稳定')
  })

  it('renders score breakdown dimension names in Chinese in tooltip', () => {
    const wrapper = mount(ChapterProgressGantt, {
      props: {
        mode: 'score',
        chapters: [
          {
            chapter_id: 'ch-1',
            chapter_number: 1,
            title: '道经初现',
            statusLabel: '已编辑',
            displayScore: 81,
            score_breakdown: {
              plot_tension: 78,
              characterization: { score: 80, comment: '动机明确' },
              readability: 85,
              consistency: 90,
              humanity: 78,
              hook_strength: 74,
            },
          },
        ],
      },
    })

    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    const tooltip = option.tooltip.formatter([{ dataIndex: 0 }])

    expect(tooltip).toContain('情节张力: 78')
    expect(tooltip).toContain('人物塑造: 80：动机明确')
    expect(tooltip).toContain('可读性: 85')
    expect(tooltip).toContain('一致性: 90')
    expect(tooltip).toContain('沉浸感: 78')
    expect(tooltip).toContain('章末钩子: 74')
    expect(tooltip).not.toContain('plot_tension')
    expect(tooltip).not.toContain('hook_strength')
  })
})
