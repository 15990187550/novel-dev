import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import OutlineConversation from './OutlineConversation.vue'

describe('OutlineConversation', () => {
  it('emits submit-feedback when sending conversation input', async () => {
    const wrapper = mount(OutlineConversation, {
      props: {
        messages: [],
        submitting: false,
      },
    })

    await wrapper.get('textarea').setValue('强化第二卷冲突')
    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('submit-feedback')?.[0]).toEqual(['强化第二卷冲突'])
    expect(wrapper.get('textarea').element.value).toBe('')
  })

  it('disables sending while submitting', () => {
    const wrapper = mount(OutlineConversation, {
      props: {
        messages: [],
        submitting: true,
      },
    })

    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('优化中')
    expect(wrapper.text()).toContain('发送中...')
  })
})
