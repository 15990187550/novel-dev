import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import OutlineDetailPanel from './OutlineDetailPanel.vue'

describe('OutlineDetailPanel', () => {
  it('shows section summaries and opens full detail entries on demand', async () => {
    const wrapper = mount(OutlineDetailPanel, {
      props: {
        detail: {
          outlineType: 'synopsis',
          status: 'ready',
          statusLabel: '已生成',
          title: '总纲',
          sections: [
            {
              title: '卷级总览',
              items: ['第 1 卷《轮回初醒》：夺回第一枚道印...'],
              detailItems: ['第 1 卷《轮回初醒》；目标：夺回第一枚道印；钩子：第二枚道印现世'],
            },
          ],
        },
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    expect(wrapper.text()).toContain('夺回第一枚道印...')
    expect(wrapper.text()).not.toContain('第二枚道印现世')

    await wrapper.find('button.outline-detail-link').trigger('click')

    expect(wrapper.text()).toContain('第二枚道印现世')
  })
})
