import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DashboardHero from './DashboardHero.vue'

describe('DashboardHero', () => {
  it('renders the delete action in the top action row', () => {
    const wrapper = mount(DashboardHero, {
      props: {
        title: '道照诸天',
        phaseLabel: '脑暴',
        volumeChapter: '第 1 卷 · 第 3 章',
        totalWords: 32000,
        archivedCount: 6,
      },
    })

    const topRow = wrapper.get('.dashboard-hero__top')
    const deleteButton = wrapper.get('.dashboard-hero__delete')

    expect(topRow.find('.dashboard-hero__delete').exists()).toBe(true)
    expect(deleteButton.classes()).toContain('dashboard-hero__action-button')
    expect(wrapper.find('.dashboard-hero__content .dashboard-hero__delete').exists()).toBe(false)
  })
})
