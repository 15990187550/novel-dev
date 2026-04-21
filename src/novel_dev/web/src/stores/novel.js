import { defineStore } from 'pinia'
import * as api from '@/api.js'

const PHASE_LABELS = {
  brainstorming: '脑暴中',
  volume_planning: '卷规划',
  context_preparation: '上下文准备',
  drafting: '草稿写作',
  reviewing: '审稿中',
  editing: '编辑润色',
  fast_reviewing: '快速审查',
  librarian: '归档中',
  completed: '已完成',
}

const createDashboardPanelState = () => ({
  state: 'idle',
  error: '',
})

const createDashboardPanels = () => ({
  entities: createDashboardPanelState(),
  timelines: createDashboardPanelState(),
  foreshadowings: createDashboardPanelState(),
  pendingDocs: createDashboardPanelState(),
})

const clearSupplementalForPanel = (store, panel) => {
  switch (panel) {
    case 'entities':
      store.entities = []
      store.entityRelationships = []
      break
    case 'timelines':
      store.timelines = []
      break
    case 'foreshadowings':
      store.foreshadowings = []
      break
    case 'pendingDocs':
      store.pendingDocs = []
      break
  }
}

export const useNovelStore = defineStore('novel', {
  state: () => ({
    novelId: '',
    novelState: {},
    archiveStats: {},
    currentChapter: null,
    chapters: [],
    volumePlan: null,
    entities: [],
    entityRelationships: [],
    timelines: [],
    spacelines: [],
    foreshadowings: [],
    pendingDocs: [],
    loadingActions: {},
    dashboardPanels: createDashboardPanels(),
    dashboardLastUpdated: '',
  }),

  getters: {
    novelTitle: (s) => s.novelState.checkpoint_data?.synopsis_data?.title || s.novelId || '未选择小说',
    currentPhaseLabel: (s) => PHASE_LABELS[s.novelState.current_phase] || s.novelState.current_phase || '-',
    currentVolumeChapter: (s) => {
      const v = s.novelState.current_volume_id || '-'
      const c = s.novelState.current_chapter_id || '-'
      return `${v} / ${c}`
    },
    canBrainstorm: (s) => s.novelState.current_phase === 'brainstorming',
    canVolumePlan: (s) => s.novelState.current_phase === 'volume_planning',
    canContext: (s) => s.novelState.current_phase === 'context_preparation',
    canDraft: (s) => s.novelState.current_phase === 'drafting',
    canAdvance: (s) => ['reviewing', 'editing', 'fast_reviewing'].includes(s.novelState.current_phase),
    canLibrarian: (s) => s.novelState.current_phase === 'librarian',
  },

  actions: {
    resetDashboardSupplemental() {
      this.entities = []
      this.entityRelationships = []
      this.timelines = []
      this.foreshadowings = []
      this.pendingDocs = []
      this.dashboardPanels = createDashboardPanels()
      this.dashboardLastUpdated = ''
    },

    syncCurrentChapter() {
      const chapterId = this.novelState.current_chapter_id
      const plan = this.volumePlan?.chapters?.find(c => c.chapter_id === chapterId)
      const chapter = this.chapters.find(c => c.chapter_id === chapterId)
      this.currentChapter = chapter ? { ...chapter, ...(plan || {}) } : plan || null
    },

    setDashboardPanelState(panel, state, error = '') {
      if (!this.dashboardPanels[panel]) return
      this.dashboardPanels[panel].state = state
      this.dashboardPanels[panel].error = error
    },

    async loadNovel(novelId) {
      this.novelId = novelId
      this.resetDashboardSupplemental()
      await this.refreshState()
    },

    async refreshState() {
      if (!this.novelId) return
      const [state, stats, chapters] = await Promise.all([
        api.getNovelState(this.novelId),
        api.getArchiveStats(this.novelId).catch(() => ({})),
        api.getChapters(this.novelId).catch(() => ({ items: [] })),
      ])
      this.novelState = state
      this.archiveStats = stats
      this.chapters = chapters.items || []
      this.volumePlan = state.checkpoint_data?.current_volume_plan || null
      this.syncCurrentChapter()
    },

    async loadDashboardSupplemental() {
      if (!this.novelId) return

      const panelTasks = {
        entities: async () => {
          const [entities, relationships] = await Promise.all([
            api.getEntities(this.novelId),
            api.getEntityRelationships(this.novelId).catch(() => ({ items: [] })),
          ])
          this.entities = entities.items || []
          this.entityRelationships = relationships.items || []
        },
        timelines: async () => {
          const res = await api.getTimelines(this.novelId)
          this.timelines = res.items || []
        },
        foreshadowings: async () => {
          const res = await api.getForeshadowings(this.novelId)
          this.foreshadowings = res.items || []
        },
        pendingDocs: async () => {
          const pending = await api.getPendingDocs(this.novelId)
          this.pendingDocs = pending.items || []
        },
      }

      for (const panel of Object.keys(panelTasks)) {
        this.setDashboardPanelState(panel, 'loading')
        clearSupplementalForPanel(this, panel)
      }

      try {
        await Promise.all(Object.entries(panelTasks).map(async ([panel, task]) => {
          try {
            await task()
            this.setDashboardPanelState(panel, 'ready')
          } catch (error) {
            clearSupplementalForPanel(this, panel)
            this.setDashboardPanelState(panel, 'error', error?.message || '请求失败')
          }
        }))
      } finally {
        this.dashboardLastUpdated = new Date().toISOString()
      }
    },

    async refreshDashboard() {
      if (!this.novelId) return
      await this.refreshState()
      await this.loadDashboardSupplemental()
      this.syncCurrentChapter()
    },

    async executeAction(actionType) {
      this.loadingActions[actionType] = true
      try {
        switch (actionType) {
          case 'brainstorm': await api.brainstorm(this.novelId); break
          case 'volume_plan': await api.planVolume(this.novelId); break
          case 'context':
            await api.prepareContext(this.novelId, this.novelState.current_chapter_id)
            break
          case 'draft':
            await api.draftChapter(this.novelId, this.novelState.current_chapter_id)
            break
          case 'advance': await api.advance(this.novelId); break
          case 'librarian': await api.runLibrarian(this.novelId); break
          case 'export': await api.exportNovel(this.novelId); break
        }
        await this.loadNovel(this.novelId)
      } finally {
        this.loadingActions[actionType] = false
      }
    },

    async fetchEntities() {
      const [entities, relationships] = await Promise.all([
        api.getEntities(this.novelId),
        api.getEntityRelationships(this.novelId).catch(() => ({ items: [] })),
      ])
      this.entities = entities.items || []
      this.entityRelationships = relationships.items || []
    },

    async fetchTimelines() {
      const res = await api.getTimelines(this.novelId)
      this.timelines = res.items || []
    },

    async fetchSpacelines() {
      const res = await api.getSpacelines(this.novelId)
      this.spacelines = res.items || []
    },

    async fetchForeshadowings() {
      const res = await api.getForeshadowings(this.novelId)
      this.foreshadowings = res.items || []
    },

    async fetchDocuments() {
      const pending = await api.getPendingDocs(this.novelId).catch(() => ({ items: [] }))
      this.pendingDocs = pending.items || []
    },
  },
})
