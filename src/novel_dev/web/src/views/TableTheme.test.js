import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import ChapterList from './ChapterList.vue'
import Locations from './Locations.vue'
import Foreshadowings from './Foreshadowings.vue'

describe('view table theming', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
  })

  function mountView(component) {
    return mount(component, {
      global: {
        plugins: [pinia],
        stubs: {
          ChapterProgressGantt: true,
          ElAlert: true,
          ElTag: true,
          ElProgress: true,
          ElButton: true,
          ElTable: {
            props: ['data', 'rowKey', 'treeProps'],
            template: '<div class="el-table-stub" :class="$attrs.class"><slot /></div>',
          },
          ElTableColumn: {
            template: '<div class="el-table-column-stub"><slot :row="{}" /></div>',
          },
        },
        mocks: {
          $router: { push: vi.fn() },
        },
      },
    })
  }

  it('applies themed table class on chapter list, locations, and foreshadowings views', () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.chapters = []
    store.spacelines = []
    store.foreshadowings = []
    store.fetchSpacelines = vi.fn()
    store.fetchForeshadowings = vi.fn()

    const chapterWrapper = mountView(ChapterList)
    const locationWrapper = mountView(Locations)
    const foreshadowingWrapper = mountView(Foreshadowings)

    expect(chapterWrapper.find('.app-themed-table').exists()).toBe(true)
    expect(locationWrapper.find('.app-themed-table').exists()).toBe(true)
    expect(foreshadowingWrapper.find('.app-themed-table').exists()).toBe(true)
  })
})
