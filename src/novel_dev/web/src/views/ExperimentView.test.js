import { mount, flushPromises } from '@vue/test-utils';
import { vi } from 'vitest';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia } from 'pinia';
import ExperimentView from './ExperimentView.vue';
import * as api from '@/api';

vi.mock('@/api');

const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div/>' } }] });
const pinia = createPinia();

// 默认 mock 防止 onMounted 中 fetchJudgeCallStats/fetchJudgePromptVersions 未设置时报错
api.fetchJudgeCallStats = vi.fn().mockResolvedValue({ total_calls: 0, total_cost_usd: 0 });
api.fetchJudgePromptVersions = vi.fn().mockResolvedValue([]);

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

describe('ExperimentView Judge tab', () => {
  it('shows judge tab in tab list', async () => {
    api.listABExperiments = vi.fn().mockResolvedValue({ tests: [] });
    const wrapper = mount(ExperimentView, {
      global: { plugins: [router, pinia], stubs: { RouterLink: true } },
    });
    await wrapper.vm.$nextTick();
    await flushPromises();
    const tabs = wrapper.findAll('[data-test="tab"]');
    const labels = tabs.map((t) => t.text());
    expect(labels.some((l) => l.includes('judge'))).toBe(true);
  });

  it('renders judge metric cards when judge tab is active', async () => {
    api.listABExperiments = vi.fn().mockResolvedValue({ tests: [] });
    api.fetchJudgeCallStats = vi.fn().mockResolvedValue({
      total_calls: 12,
      total_cost_usd: 0.0245,
    });
    api.fetchJudgePromptVersions = vi.fn().mockResolvedValue([
      { id: 'pv_1', version: 'v1', is_active: true, last_score: 0.82 },
    ]);
    const wrapper = mount(ExperimentView, {
      global: { plugins: [router, pinia], stubs: { RouterLink: true } },
    });
    await wrapper.vm.$nextTick();
    await flushPromises();
    // 模拟切到 judge tab
    const judgeTab = wrapper.find('[data-test-tab="judge"]');
    expect(judgeTab.exists()).toBe(true);
    await judgeTab.trigger('click');
    await wrapper.vm.$nextTick();
    await flushPromises();
    expect(wrapper.text()).toContain('一致率');
    expect(wrapper.text()).toContain('本月调用');
    expect(wrapper.text()).toContain('本月成本');
  });
});
