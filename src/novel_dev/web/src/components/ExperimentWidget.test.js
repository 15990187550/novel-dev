import { mount, flushPromises } from '@vue/test-utils';
import { vi } from 'vitest';
import ExperimentWidget from './ExperimentWidget.vue';
import * as api from '@/api';

vi.mock('@/api');

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
