import { mount, flushPromises } from '@vue/test-utils';
import { vi } from 'vitest';
import ExperimentView from './ExperimentView.vue';
import * as api from '@/api';

vi.mock('@/api');

it('renders experiment list with status badges', async () => {
  api.listABExperiments = vi.fn().mockResolvedValue({ tests: [
    { id: 'ab_1', agent_name: 'writer', status: 'running', baseline_version: 'v1', challenger_version: 'v2' },
    { id: 'ab_2', agent_name: 'critic', status: 'completed', baseline_version: 'v1', challenger_version: 'v2' },
  ]});
  const wrapper = mount(ExperimentView);
  await flushPromises();
  expect(wrapper.findAll('[data-testid="experiment-row"]').length).toBe(2);
  expect(wrapper.find('[data-testid="status-running"]').exists()).toBe(true);
  expect(wrapper.find('[data-testid="status-completed"]').exists()).toBe(true);
});
