import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import QualityRecommendationWidget from './QualityRecommendationWidget.vue'

const { mockRecommend } = vi.hoisted(() => ({
  mockRecommend: vi.fn(),
}))

vi.mock('@/api.js', () => ({
  recommendChapterQuality: mockRecommend,
}))

function buildResponse(overrides = {}) {
  return {
    chapter_id: 'ch-1',
    recommendation: 'accept',
    confidence: 0.85,
    rationale: ['score=82 >= publishable, 但未开启 accept_with_warn'],
    suggested_actions: [
      { type: 'targeted_repair', scope: ['plot_tension'], estimated_iterations: null, reason: null },
    ],
    ...overrides,
  }
}

describe('QualityRecommendationWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRecommend.mockResolvedValue(buildResponse())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders accept recommendation with success styling', async () => {
    mockRecommend.mockResolvedValueOnce(
      buildResponse({
        recommendation: 'accept',
        confidence: 0.92,
        rationale: ['达到发布阈值'],
        suggested_actions: [],
      }),
    )
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    const badge = wrapper.find('[data-testid="recommendation-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('可发布')
    expect(wrapper.find('[data-testid="recommendation-confidence"]').text()).toBe('92%')
    expect(wrapper.find('.quality-recommendation-widget').classes()).toContain('quality-recommendation-widget--accept')
    expect(mockRecommend).toHaveBeenCalledWith('novel-1', 'ch-1', {
      current_attempt: 1,
      accept_with_warn: false,
      recent_issue_counts: [],
    })
  })

  it('shows warn + repair messaging for minor_repair', async () => {
    mockRecommend.mockResolvedValueOnce(
      buildResponse({
        recommendation: 'minor_repair',
        confidence: 0.6,
        rationale: ['score=70 在 minor_repair 区间'],
        suggested_actions: [
          {
            type: 'targeted_repair',
            scope: ['plot_tension', 'consistency'],
            estimated_iterations: 2,
            reason: '情节张力不足',
          },
        ],
      }),
    )
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    const badge = wrapper.find('[data-testid="recommendation-badge"]')
    expect(badge.text()).toContain('建议小幅修改')
    expect(wrapper.find('[data-testid="recommendation-confidence"]').text()).toBe('60%')

    const actions = wrapper.findAll('[data-testid="suggested-actions"] > li')
    expect(actions).toHaveLength(1)
    expect(actions[0].text()).toContain('定向修复')
    expect(actions[0].text()).toContain('情节张力')
    expect(actions[0].text()).toContain('一致性')
    expect(actions[0].text()).toContain('≈ 2 轮')
    expect(actions[0].text()).toContain('情节张力不足')
  })

  it('displays stop_and_inspect alert with manual intervention copy', async () => {
    mockRecommend.mockResolvedValueOnce(
      buildResponse({
        recommendation: 'stop_and_inspect',
        confidence: 0.3,
        rationale: ['critical issues detected'],
        suggested_actions: [{ type: 'manual_review', scope: [], estimated_iterations: null, reason: null }],
      }),
    )
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="stop-and-inspect-alert"]').text()).toBe('需人工介入')
    expect(wrapper.find('[data-testid="recommendation-badge"]').text()).toContain('需人工介入')
  })

  it('collapses rationale by default and toggles on click', async () => {
    mockRecommend.mockResolvedValueOnce(
      buildResponse({
        rationale: ['rule 1', 'rule 2'],
      }),
    )
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="rationale-list"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rationale-toggle"]').text()).toBe('查看推理')

    await wrapper.find('[data-testid="rationale-toggle"]').trigger('click')
    expect(wrapper.find('[data-testid="rationale-toggle"]').text()).toBe('收起推理')
    const items = wrapper.findAll('[data-testid="rationale-list"] > li')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toBe('rule 1')
    expect(items[1].text()).toBe('rule 2')
  })

  it('shows an inline error when the API call fails', async () => {
    mockRecommend.mockRejectedValueOnce(new Error('network down'))
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    const root = wrapper.find('.quality-recommendation-widget')
    expect(root.classes()).toContain('is-error')
    expect(wrapper.find('[data-testid="recommendation-error"]').text()).toContain('network down')
  })

  it('emits continue-retry when clicked', async () => {
    mockRecommend.mockResolvedValueOnce({
      recommendation: 'stop_and_inspect',
      confidence: 1,
      rationale: [],
      suggested_actions: [],
    })
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'n1', chapterId: 'c1', currentAttempt: 3 },
    })
    await flushPromises()
    const btn = wrapper.find('[data-testid="continue-retry-btn"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('continue-retry')).toBeTruthy()
  })

  it('shows root cause when present', async () => {
    const wrapper = mount(QualityRecommendationWidget, {
      props: {
        novelId: 'n1', chapterId: 'c1',
        rootCause: {
          summary: 'beat 2 越界',
          suggested_actions: [
            { action: '重写 beat 2', target: 'beat:2', severity: 'high' },
          ],
          confidence: 0.85,
        },
      },
    })
    await flushPromises()
    expect(wrapper.find('[data-testid="root-cause-summary"]').text()).toContain('beat 2 越界')
    expect(wrapper.findAll('[data-testid="root-cause-action"]').length).toBe(1)
  })

  it('refetches when props change', async () => {
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()
    expect(mockRecommend).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ chapterId: 'ch-2', acceptWithWarn: true })
    await flushPromises()

    expect(mockRecommend).toHaveBeenCalledTimes(2)
    expect(mockRecommend).toHaveBeenLastCalledWith('novel-1', 'ch-2', {
      current_attempt: 1,
      accept_with_warn: true,
      recent_issue_counts: [],
    })
  })
})