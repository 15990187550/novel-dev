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

  it('marks warning and error titles for high contrast rendering', () => {
    const wrapper = mount(DashboardStatusCards, {
      props: {
        panels: [
          {
            id: 'warning',
            label: '流程状态',
            title: '脑暴中',
            detail: '当前章待选择',
            route: '/dashboard',
            panelState: 'warning',
          },
          {
            id: 'error',
            label: '日志状态',
            title: '3 条最近日志',
            detail: '未找到设定文档',
            route: '/logs',
            panelState: 'error',
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

    expect(wrapper.findAll('.dashboard-status-card__title--contrast')).toHaveLength(2)
  })
})
