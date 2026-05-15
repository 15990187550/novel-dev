import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NovelSelector from './NovelSelector.vue'

const { mockCreateNovel, mockGetNovelCategories, mockListNovels, mockLoadNovel } = vi.hoisted(() => ({
  mockCreateNovel: vi.fn(),
  mockGetNovelCategories: vi.fn(),
  mockListNovels: vi.fn(),
  mockLoadNovel: vi.fn(),
}))

vi.mock('@/api.js', () => ({
  createNovel: mockCreateNovel,
  getNovelCategories: mockGetNovelCategories,
  listNovels: mockListNovels,
}))

vi.mock('@/stores/novel.js', () => ({
  useNovelStore: () => ({
    novelId: '',
    novelTitle: '',
    loadNovel: mockLoadNovel,
  }),
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
  },
}))

const stubs = {
  ElButton: { template: '<button><slot /></button>' },
  ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<label><slot /></label>' },
  ElInput: { template: '<input />' },
  ElOption: { template: '<option />' },
  ElSelect: { template: '<select><slot /></select>' },
  ElSelectV2: { template: '<div />' },
}

describe('NovelSelector', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListNovels.mockResolvedValue({ items: [] })
    mockGetNovelCategories.mockResolvedValue([
      {
        slug: 'xuanhuan',
        name: '玄幻',
        children: [{ slug: 'zhutian', name: '诸天文' }],
      },
    ])
    mockCreateNovel.mockResolvedValue({ novel_id: 'novel-1' })
  })

  it('requires title and both category levels before creating a novel', async () => {
    const wrapper = mount(NovelSelector, {
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.vm.canCreate).toBe(false)
    expect(mockGetNovelCategories).toHaveBeenCalled()

    wrapper.vm.createForm.title = '新小说'
    wrapper.vm.createForm.primary_category_slug = 'xuanhuan'
    await wrapper.vm.$nextTick()
    wrapper.vm.createForm.secondary_category_slug = 'zhutian'
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.canCreate).toBe(true)

    await wrapper.vm.doCreate()

    expect(mockCreateNovel).toHaveBeenCalledWith({
      title: '新小说',
      primary_category_slug: 'xuanhuan',
      secondary_category_slug: 'zhutian',
    })
  })
})
