import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import ExperimentWidget from './ExperimentWidget.vue';
import * as api from '@/api';

vi.mock('@/api');

setActivePinia(createPinia());

it('renders recent auto-accepted count', async () => {
  api.getRecentABDecisions.mockResolvedValue({
    decisions: [
      { id: '1', action: 'accept', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
      { id: '2', action: 'evaluate', experiment_id: 'ab_1', decision_at: '2026-06-19T10:01:00' },
    ],
  });
  const wrapper = mount(ExperimentWidget);
  await flushPromises();
  expect(wrapper.find('[data-testid="recent-accepted-count"]').text()).toContain('1');
});

it('shows empty state when no decisions', async () => {
  api.getRecentABDecisions.mockResolvedValue({ decisions: [] });
  const wrapper = mount(ExperimentWidget);
  await flushPromises();
  expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true);
});

describe('ExperimentWidget judge status bar', () => {
  it('shows judge status bar with enabled indicator', async () => {
    api.getRecentABDecisions.mockResolvedValue({ decisions: [] });
    api.fetchJudgePromptVersions.mockResolvedValue([
      { id: 'pv_1', version: 'v1', is_active: true },
    ]);
    api.fetchJudgeCallStats.mockResolvedValue({ total_calls: 5, total_cost_usd: 0.01 });
    const wrapper = mount(ExperimentWidget);
    await flushPromises();
    expect(wrapper.find('[data-testid="judge-status-chip"]').exists()).toBe(true);
  });

  it('shows degraded chip when cost cap nearly reached', async () => {
    api.getRecentABDecisions.mockResolvedValue({ decisions: [] });
    api.fetchJudgePromptVersions.mockResolvedValue([
      { id: 'pv_1', version: 'v1', is_active: true },
    ]);
    api.fetchJudgeCallStats.mockResolvedValue({ total_calls: 50, total_cost_usd: 0.45 });  // 90% of 0.50 cap
    const wrapper = mount(ExperimentWidget);
    await flushPromises();
    expect(wrapper.text()).toContain('接近 cost cap');
  });
});
