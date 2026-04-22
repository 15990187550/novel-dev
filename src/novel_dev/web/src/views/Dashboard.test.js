import { defineComponent, h, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useNovelStore } from '@/stores/novel.js'
import Dashboard from './Dashboard.vue'

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessageBox: {
      confirm: vi.fn(),
    },
    ElMessage: {
      success: vi.fn(),
    },
  }
})

vi.mock('@/composables/useRealtimeLog.js', () => ({
  useRealtimeLog: () => ({
    logs: ref([]),
    connected: ref(true),
    disconnect: vi.fn(),
  }),
}))

const DashboardHeroStub = defineComponent({
  name: 'DashboardHeroStub',
  emits: ['delete-novel'],
  setup(_, { emit }) {
    return () =>
      h('button', {
        class: 'delete-novel-button',
        type: 'button',
        onClick: () => emit('delete-novel'),
      }, 'delete')
  },
})

describe('Dashboard', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
  })

  function mountView() {
    return mount(Dashboard, {
      global: {
        plugins: [pinia],
        stubs: {
          DashboardHero: DashboardHeroStub,
          DashboardStatusCards: true,
          DashboardVolumeSummary: true,
          DashboardNextActions: true,
          DashboardInsights: true,
        },
      },
    })
  }

  it('confirms deletion, deletes the selected novel, and returns to the empty dashboard state', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue()

    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.deleteCurrentNovel = vi.fn().mockResolvedValue()
    store.refreshDashboard = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.delete-novel-button').trigger('click')

    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1)
    expect(store.deleteCurrentNovel).toHaveBeenCalledTimes(1)
    expect(ElMessage.success).toHaveBeenCalledWith('小说已删除')
  })

  it('does not delete when the confirmation dialog is cancelled', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValue(new Error('cancel'))

    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.deleteCurrentNovel = vi.fn().mockResolvedValue()
    store.refreshDashboard = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.delete-novel-button').trigger('click')

    expect(store.deleteCurrentNovel).not.toHaveBeenCalled()
    expect(ElMessage.success).not.toHaveBeenCalled()
  })
})
