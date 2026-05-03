import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ChapterProgressGantt from './ChapterProgressGantt.vue'

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    props: ['option'],
    template: '<div class="v-chart-stub" />',
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

enableAutoUnmount(afterEach)

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

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

  it('keeps score tooltip interactive, compact, and shifted away from the left edge', () => {
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
            scoreDetail: '节奏稳定',
            score_breakdown: {
              plot_tension: { score: 78, comment: '开局钩子明确' },
            },
          },
        ],
      },
    })

    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    const tooltip = option.tooltip.formatter([{ dataIndex: 0 }])
    const copyPayload = tooltip.match(/data-score-tooltip-copy="([^"]+)"/)?.[1]

    expect(option.tooltip.enterable).toBe(true)
    expect(option.tooltip.appendToBody).toBe(true)
    expect(option.tooltip.confine).toBe(false)
    expect(option.tooltip.extraCssText).toContain('max-width: 280px')
    expect(option.tooltip.position([40, 80], null, null, null, {
      contentSize: [260, 120],
      viewSize: [480, 200],
    })).toEqual([56, 20])
    expect(option.tooltip.position([420, 80], null, null, null, {
      contentSize: [260, 120],
      viewSize: [480, 200],
    })).toEqual([436, 20])
    expect(tooltip).toContain('data-score-tooltip-copy')
    expect(tooltip).toContain('复制')
    expect(decodeURIComponent(copyPayload)).toContain('道经初现')
    expect(decodeURIComponent(copyPayload)).toContain('情节张力: 78：开局钩子明确')
  })

  it('copies score tooltip text from the tooltip copy button', async () => {
    const writeText = vi.fn().mockResolvedValue()
    vi.stubGlobal('navigator', {
      clipboard: { writeText },
    })
    mount(ChapterProgressGantt, {
      props: {
        mode: 'score',
        chapters: [{ chapter_id: 'ch-1', chapter_number: 1, title: '第一章', displayScore: 82 }],
      },
    })
    const button = document.createElement('button')
    button.dataset.scoreTooltipCopy = encodeURIComponent('第一章\n评分: 82')
    document.body.appendChild(button)

    button.click()
    await Promise.resolve()

    expect(writeText).toHaveBeenCalledWith('第一章\n评分: 82')
  })
})
