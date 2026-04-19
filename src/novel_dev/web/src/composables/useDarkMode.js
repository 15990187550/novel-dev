import { useDark, useToggle } from '@vueuse/core'
import { watch } from 'vue'

export function useDarkMode() {
  const isDark = useDark({
    selector: 'html',
    attribute: 'class',
    valueDark: 'dark',
    valueLight: '',
  })
  const toggleDark = useToggle(isDark)

  watch(isDark, (dark) => {
    const el = document.documentElement
    if (dark) {
      el.style.setProperty('--el-bg-color', '#111827')
      el.style.setProperty('--el-bg-color-page', '#0b0f19')
      el.style.setProperty('--el-text-color-primary', '#f3f4f6')
      el.style.setProperty('--el-border-color', '#374151')
    } else {
      el.style.removeProperty('--el-bg-color')
      el.style.removeProperty('--el-bg-color-page')
      el.style.removeProperty('--el-text-color-primary')
      el.style.removeProperty('--el-border-color')
    }
  }, { immediate: true })

  return { isDark, toggleDark }
}
