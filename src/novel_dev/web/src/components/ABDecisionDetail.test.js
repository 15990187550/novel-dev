import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ABDecisionDetail from './ABDecisionDetail.vue'

const sampleDecision = {
  id: 'dec_1',
  decision_at: '2026-06-19T10:00:00',
  experiment_id: 'ab_1',
  action: 'accept',
  scores: { v1: 75.1, v2: 75.5 },
  judge_triggered: true,
  judge_tie_breaker_baseline: 7.3,
  judge_tie_breaker_challenger: 8.0,
  judge_scores_baseline: { 口吻: 7.0, 叙事连贯: 7.5, 风格调性: 7.5 },
  judge_scores_challenger: { 口吻: 8.0, 叙事连贯: 8.0, 风格调性: 8.0 },
  judge_rationale_baseline: '风格略平淡',
  judge_rationale_challenger: '口吻统一,推进自然',
  judge_model: 'claude-sonnet-4-6',
  judge_error: null,
  meta: { winner: 'v2' },
}

describe('ABDecisionDetail', () => {
  it('renders judge 3-dimension scores when triggered', () => {
    const wrapper = mount(ABDecisionDetail, { props: { decision: sampleDecision } })
    expect(wrapper.text()).toContain('口吻')
    expect(wrapper.text()).toContain('叙事连贯')
    expect(wrapper.text()).toContain('风格调性')
    expect(wrapper.text()).toContain('claude-sonnet-4-6')
  })

  it('shows degraded path notice when judge_triggered is false', () => {
    const wrapper = mount(ABDecisionDetail, {
      props: { decision: { ...sampleDecision, judge_triggered: false, judge_error: 'parse_failed' } },
    })
    expect(wrapper.text()).toContain('parse_failed')
  })

  it('shows clear winner when no judge involvement', () => {
    const wrapper = mount(ABDecisionDetail, {
      props: {
        decision: { ...sampleDecision, judge_triggered: false, judge_error: null, scores: { v1: 75, v2: 85 } },
      },
    })
    expect(wrapper.text()).toContain('85')
  })
})
