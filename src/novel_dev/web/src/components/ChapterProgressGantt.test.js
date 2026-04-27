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
})
