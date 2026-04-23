import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DarkModeToggle from './DarkModeToggle.vue'

vi.mock('@/composables/useDarkMode.js', () => ({
  useDarkMode: () => ({
    isDark: false,
    toggleDark: vi.fn(),
  }),
}))

describe('DarkModeToggle', () => {
  it('renders with fixed square sizing classes so it aligns with header chips', () => {
    const wrapper = mount(DarkModeToggle, {
      global: {
        stubs: {
          ElIcon: {
            template: '<span class="el-icon-stub"><slot /></span>',
          },
          Moon: true,
          Sunny: true,
        },
      },
    })

    const button = wrapper.get('button')
    expect(button.classes()).toContain('app-icon-button')
    expect(button.classes()).toContain('app-icon-button--square')
  })
})
