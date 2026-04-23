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

const DashboardStatusCardsStub = defineComponent({
  name: 'DashboardStatusCardsStub',
  setup() {
    return () => h('section', { class: 'dashboard-status-cards-stub' }, 'status')
  },
})

const DashboardNextActionsStub = defineComponent({
  name: 'DashboardNextActionsStub',
  setup() {
    return () => h('section', { class: 'dashboard-next-actions-stub' }, 'actions')
  },
})

const DashboardVolumeSummaryStub = defineComponent({
  name: 'DashboardVolumeSummaryStub',
  setup() {
    return () => h('section', { class: 'dashboard-volume-summary-stub' }, 'volume')
  },
})

const DashboardInsightsStub = defineComponent({
  name: 'DashboardInsightsStub',
  setup() {
    return () => h('section', { class: 'dashboard-insights-stub' }, 'insights')
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
          DashboardStatusCards: DashboardStatusCardsStub,
          DashboardVolumeSummary: DashboardVolumeSummaryStub,
          DashboardNextActions: DashboardNextActionsStub,
          DashboardInsights: DashboardInsightsStub,
        },
      },
    })
  }

  it('renders next actions above the dashboard content split', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.refreshDashboard = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    const html = wrapper.html()
    const statusIndex = html.indexOf('dashboard-status-cards-stub')
    const actionsIndex = html.indexOf('dashboard-next-actions-stub')
    const volumeIndex = html.indexOf('dashboard-volume-summary-stub')
    const insightsIndex = html.indexOf('dashboard-insights-stub')

    expect(statusIndex).toBeGreaterThan(-1)
    expect(actionsIndex).toBeGreaterThan(statusIndex)
    expect(volumeIndex).toBeGreaterThan(actionsIndex)
    expect(insightsIndex).toBeGreaterThan(volumeIndex)
  })

  it('stacks volume summary and insights vertically', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.refreshDashboard = vi.fn().mockResolvedValue()

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.dashboard-detail-stack').exists()).toBe(true)
  })

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
