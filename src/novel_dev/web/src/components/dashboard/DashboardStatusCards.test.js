import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DashboardStatusCards from './DashboardStatusCards.vue'

describe('DashboardStatusCards', () => {
  it('renders status cards, preserves router targets and applies fallbacks', () => {
    const wrapper = mount(DashboardStatusCards, {
      props: {
        panels: [
          {
            id: 'flow',
            label: '流程状态',
            summary: '流程稳定',
            detail: '当前流程已串联',
            route: '/dashboard',
            state: 'error',
          },
          {
            id: 'data',
            label: '数据状态',
            value: '数据异常',
            detail: '存在待处理数据',
            route: '/documents',
            panelState: 'ok',
          },
          {
            id: 'count',
            label: '统计状态',
            count: 12,
            detail: '计数回退',
            route: '/counts',
            panelState: 'ok',
          },
        ],
      },
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :data-to="to"><slot /></a>',
          },
        },
      },
    })

    expect(wrapper.text()).toContain('流程状态')
    expect(wrapper.text()).toContain('数据状态')
    expect(wrapper.text()).toContain('统计状态')
    expect(wrapper.text()).toContain('流程稳定')
    expect(wrapper.text()).toContain('数据异常')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).toContain('/dashboard')
    expect(wrapper.findAll('a')[0].attributes('data-to')).toBe('/dashboard')
    expect(wrapper.findAll('a')[1].attributes('data-to')).toBe('/documents')
    expect(wrapper.findAll('.dashboard-status-card.is-error')).toHaveLength(1)
  })
})
