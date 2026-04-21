import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import VolumePlan from './VolumePlan.vue'

describe('VolumePlan', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads outline workbench when mounted with an active novel id', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()

    mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: true,
          OutlineConversation: true,
        },
      },
    })

    await flushPromises()

    expect(store.refreshOutlineWorkbench).toHaveBeenCalledTimes(1)
  })

  it('reloads outline workbench when novel id changes', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()

    mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: true,
          OutlineConversation: true,
        },
      },
    })

    expect(store.refreshOutlineWorkbench).not.toHaveBeenCalled()

    store.novelId = 'novel-2'
    await flushPromises()

    expect(store.refreshOutlineWorkbench).toHaveBeenCalledTimes(1)
  })
})
