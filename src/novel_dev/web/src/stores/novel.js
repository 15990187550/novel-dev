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

export const useNovelStore = defineStore('novel', {
  state: () => ({
    novelId: '',
    novelState: {},
    archiveStats: {},
    currentChapter: null,
    chapters: [],
    volumePlan: null,
    synopsisContent: '',
    synopsisData: null,
    entities: [],
    entityRelationships: [],
    timelines: [],
    spacelines: [],
    foreshadowings: [],
    pendingDocs: [],
    loadingActions: {},
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
    async loadNovel(novelId) {
      this.novelId = novelId
      const [state, stats, chapters, synopsis, volumePlan] = await Promise.all([
        api.getNovelState(novelId),
        api.getArchiveStats(novelId).catch(() => ({})),
        api.getChapters(novelId).catch(() => ({ items: [] })),
        api.getSynopsis(novelId).catch(() => null),
        api.getVolumePlan(novelId).catch(() => null),
      ])
      this.novelState = state
      this.archiveStats = stats
      this.chapters = chapters.items || []
      this.synopsisContent = synopsis?.content || ''
      this.synopsisData = synopsis?.synopsis_data || state.checkpoint_data?.synopsis_data || null
      this.volumePlan = volumePlan || state.checkpoint_data?.current_volume_plan || null
      const plan = this.volumePlan?.chapters?.find(c => c.chapter_id === state.current_chapter_id)
      const ch = this.chapters.find(c => c.chapter_id === state.current_chapter_id)
      this.currentChapter = ch ? { ...ch, ...plan } : plan || null
    },

    async refreshState() {
      if (!this.novelId) return
      const [state, synopsis, volumePlan] = await Promise.all([
        api.getNovelState(this.novelId),
        api.getSynopsis(this.novelId).catch(() => null),
        api.getVolumePlan(this.novelId).catch(() => null),
      ])
      this.novelState = state
      this.synopsisContent = synopsis?.content || this.synopsisContent
      this.synopsisData = synopsis?.synopsis_data || state.checkpoint_data?.synopsis_data || this.synopsisData
      this.volumePlan = volumePlan || state.checkpoint_data?.current_volume_plan || null
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

    async saveSynopsis(content) {
      if (!this.novelId) return
      await api.importSynopsis(this.novelId, content)
      await this.loadNovel(this.novelId)
    },
  },
})
