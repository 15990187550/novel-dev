import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import OutlineSidebar from './OutlineSidebar.vue'

describe('OutlineSidebar', () => {
  it('renders synopsis and volume items in the sidebar', () => {
    const wrapper = mount(OutlineSidebar, {
      props: {
        items: [
          {
            outline_type: 'synopsis',
            outline_ref: 'synopsis',
            key: 'synopsis:synopsis',
            title: '总纲',
            statusLabel: '可编辑',
            isCurrent: true,
          },
          {
            outline_type: 'volume',
            outline_ref: 'vol_1',
            key: 'volume:vol_1',
            title: '第 1 卷',
            statusLabel: '待创建',
            isCurrent: false,
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('大纲规划')
    expect(wrapper.text()).toContain('总纲')
    expect(wrapper.text()).toContain('第 1 卷')
    expect(wrapper.text()).toContain('待创建')
  })

  it('emits select when clicking a sidebar item', async () => {
    const item = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
      key: 'volume:vol_2',
      title: '第 2 卷',
      statusLabel: '可编辑',
      isCurrent: false,
    }
    const wrapper = mount(OutlineSidebar, {
      props: {
        items: [item],
      },
    })

    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('select')?.[0]).toEqual([item])
  })
})
