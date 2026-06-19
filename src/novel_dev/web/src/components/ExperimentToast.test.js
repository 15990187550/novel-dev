import { mount, flushPromises } from '@vue/test-utils';
import { vi } from 'vitest';
import ExperimentToast from './ExperimentToast.vue';
import * as api from '@/api';

vi.mock('@/api');

it('shows toast for new accept decision', async () => {
  api.getRecentABDecisions = vi.fn().mockResolvedValue({ decisions: [
    { id: '1', action: 'accept', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
  ]});
  const wrapper = mount(ExperimentToast);
  await flushPromises();
  expect(wrapper.find('[data-testid="toast-accept"]').exists()).toBe(true);
});

it('does not duplicate toasts on repeated polls', async () => {
  api.getRecentABDecisions = vi.fn().mockResolvedValue({ decisions: [
    { id: '1', action: 'accept', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
  ]});
  const wrapper = mount(ExperimentToast);
  await flushPromises();
  await flushPromises();
  expect(wrapper.findAll('[data-testid="toast-accept"]').length).toBe(1);
});

it('shows rolled_back toast with rollback message', async () => {
  api.getRecentABDecisions = vi.fn().mockResolvedValue({ decisions: [
    { id: '2', action: 'rolled_back', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
  ]});
  const wrapper = mount(ExperimentToast);
  await flushPromises();
  expect(wrapper.find('[data-testid="toast-rolled_back"]').exists()).toBe(true);
});
