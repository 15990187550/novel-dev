import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import QualityRecommendationWidget from './QualityRecommendationWidget.vue'

const { mockRecommend, mockAxiosGet } = vi.hoisted(() => ({
  mockRecommend: vi.fn(),
  mockAxiosGet: vi.fn(),
}))

vi.mock('@/api.js', () => ({
  recommendChapterQuality: mockRecommend,
}))

vi.mock('axios', () => ({
  default: { get: mockAxiosGet, post: vi.fn() },
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
      recent_issue_counts: {},
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
      recent_issue_counts: {},
    })
  })

  it('fetches and sends recent issue counts from backend', async () => {
    mockAxiosGet.mockResolvedValueOnce({
      data: { counts: { BEAT_BOUNDARY_VIOLATION: 2, AI_FLAVOR_HIGH: 1 } },
    })
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'n1', chapterId: 'c1' },
    })
    await flushPromises()
    expect(mockAxiosGet).toHaveBeenCalledWith('/api/novels/n1/chapters/recent-issue-counts?window=5')
    const lastCall = mockRecommend.mock.calls.at(-1)
    expect(lastCall[2].recent_issue_counts).toEqual({ BEAT_BOUNDARY_VIOLATION: 2, AI_FLAVOR_HIGH: 1 })
  })

  it('expands to show critic breakdown when the show-breakdown button is clicked', async () => {
    // First axios.get is the recent-issue-counts call inside loadRecommendation;
    // second is the breakdown fetch triggered by clicking the toggle.
    mockAxiosGet
      .mockResolvedValueOnce({ data: { counts: {} } })
      .mockResolvedValueOnce({
        data: {
          chapter_id: 'ch-1',
          overall_score: 80,
          dimensions: { plot_tension: 75, humanity: 88, hook_strength: 70 },
          dimension_feedback: { plot_tension: '张力不足', humanity: '人物鲜活' },
          attempt_index: 0,
        },
      })

    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    // Panel hidden initially
    expect(wrapper.find('[data-testid="critic-breakdown"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="show-breakdown-btn"]').text()).toBe('查看评分明细')

    // Click to expand
    await wrapper.find('[data-testid="show-breakdown-btn"]').trigger('click')
    await flushPromises()

    // Endpoint hit with the correct chapterId
    const breakdownCalls = mockAxiosGet.mock.calls.filter(
      ([url]) => url === '/api/chapters/ch-1/critic-breakdown'
    )
    expect(breakdownCalls.length).toBeGreaterThanOrEqual(1)

    // Toggle label flipped and panel is now rendered
    expect(wrapper.find('[data-testid="show-breakdown-btn"]').text()).toBe('收起评分明细')
    const breakdown = wrapper.find('[data-testid="critic-breakdown"]')
    expect(breakdown.exists()).toBe(true)

    // Overall + attempt info present
    expect(wrapper.find('[data-testid="breakdown-overall"]').text()).toContain('80')
    expect(wrapper.find('[data-testid="breakdown-overall"]').text()).toContain('第 1 次')

    // Each dimension renders as a list item with its score
    expect(wrapper.find('[data-testid="breakdown-dim-plot_tension"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="breakdown-score-plot_tension"]').text()).toBe('75')
    expect(wrapper.find('[data-testid="breakdown-score-humanity"]').text()).toBe('88')
    expect(wrapper.find('[data-testid="breakdown-score-hook_strength"]').text()).toBe('70')
    // Feedback for one of the dimensions renders
    expect(wrapper.find('[data-testid="breakdown-feedback-plot_tension"]').text()).toBe('张力不足')
    // Human label is mapped via SCOPE_LABELS
    expect(wrapper.find('[data-testid="breakdown-dim-plot_tension"]').text()).toContain('情节张力')
  })

  it('collapses the critic breakdown panel when the toggle is clicked twice', async () => {
    mockAxiosGet
      .mockResolvedValueOnce({ data: { counts: {} } })
      .mockResolvedValueOnce({
        data: {
          chapter_id: 'ch-1',
          overall_score: 80,
          dimensions: { plot_tension: 75 },
          dimension_feedback: {},
          attempt_index: 0,
        },
      })

    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    await wrapper.find('[data-testid="show-breakdown-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="critic-breakdown"]').exists()).toBe(true)

    await wrapper.find('[data-testid="show-breakdown-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="critic-breakdown"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="show-breakdown-btn"]').text()).toBe('查看评分明细')
  })

  it('shows the empty-breakdown message when the API returns no dimensions', async () => {
    mockAxiosGet
      .mockResolvedValueOnce({ data: { counts: {} } })
      .mockResolvedValueOnce({
        data: {
          chapter_id: 'ch-1',
          overall_score: null,
          dimensions: {},
          dimension_feedback: {},
          attempt_index: null,
        },
      })

    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'novel-1', chapterId: 'ch-1' },
    })
    await flushPromises()

    await wrapper.find('[data-testid="show-breakdown-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="critic-breakdown"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="breakdown-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="breakdown-empty"]').text()).toBe('暂无评分明细')
  })
})