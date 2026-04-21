import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DashboardStatusCards from './DashboardStatusCards.vue'

describe('DashboardStatusCards', () => {
  it('renders status cards and marks error panels', () => {
    const wrapper = mount(DashboardStatusCards, {
      props: {
        panels: [
          {
            id: 'flow',
            label: '流程状态',
            title: '流程稳定',
            detail: '当前流程已串联',
            route: '/dashboard',
            panelState: 'ok',
          },
          {
            id: 'data',
            label: '数据状态',
            title: '数据异常',
            detail: '存在待处理数据',
            route: '/documents',
            panelState: 'error',
          },
        ],
      },
      global: {
        stubs: {
          RouterLink: {
            template: '<a><slot /></a>',
          },
        },
      },
    })

    expect(wrapper.text()).toContain('流程状态')
    expect(wrapper.text()).toContain('数据状态')
    expect(wrapper.text()).toContain('流程稳定')
    expect(wrapper.text()).toContain('数据异常')
    expect(wrapper.findAll('.dashboard-status-card.is-error')).toHaveLength(1)
  })
})
