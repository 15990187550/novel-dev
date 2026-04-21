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

const ENTITY_TYPE_LABELS = {
  character: '人物',
  item: '法宝神兵',
  location: '其他',
  other: '其他',
}

const CATEGORY_ORDER = ['人物', '势力', '功法', '法宝神兵', '天材地宝', '其他']

const TYPE_TO_CATEGORY = {
  character: '人物',
  item: '法宝神兵',
  location: '其他',
  other: '其他',
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
      store.entityTree = []
      store.selectedEntityNode = null
      store.selectedEntityDetail = null
      store.entitySearchQuery = ''
      store.entitySearchResults = []
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

const normalizeLabel = (value, fallback = '未命名') => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || fallback
}

const getEntityTypeLabel = (type) => ENTITY_TYPE_LABELS[type] || type || '其他'

const getEffectiveCategory = (entity) =>
  entity.effective_category || entity.manual_category || entity.system_category || TYPE_TO_CATEGORY[entity.type] || '其他'

const getEffectiveGroupName = (entity) => {
  if (entity.effective_group_name) return entity.effective_group_name
  if (entity.manual_category) return entity.manual_group_name || '未分组'
  return entity.system_group_name || '未分组'
}

const getEffectiveGroupSlug = (entity) => {
  if (entity.effective_group_slug) return entity.effective_group_slug
  if (entity.manual_category) return entity.manual_group_slug || 'ungrouped'
  return entity.system_group_slug || 'ungrouped'
}

const createEntityNode = (entity) => ({
  id: `entity:${entity.entity_id}`,
  label: normalizeLabel(entity.name, '未命名实体'),
  nodeType: 'entity',
  entityId: entity.entity_id,
  data: entity,
  children: [],
})

const buildEntityTreeFromEntities = (entities = []) => {
  const categoryBuckets = new Map()
  for (const entity of entities) {
    const category = getEffectiveCategory(entity)
    const groupLabel = getEffectiveGroupName(entity)
    const groupSlug = getEffectiveGroupSlug(entity)
    if (!categoryBuckets.has(category)) categoryBuckets.set(category, new Map())
    const groupBuckets = categoryBuckets.get(category)
    if (!groupBuckets.has(groupSlug)) {
      groupBuckets.set(groupSlug, {
        label: groupLabel,
        groupSlug,
        entities: [],
      })
    }
    groupBuckets.get(groupSlug).entities.push(entity)
  }

  return [...categoryBuckets.entries()]
    .sort(([left], [right]) => {
      const leftIndex = CATEGORY_ORDER.indexOf(left)
      const rightIndex = CATEGORY_ORDER.indexOf(right)
      if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right, 'zh-Hans-CN')
      if (leftIndex === -1) return 1
      if (rightIndex === -1) return -1
      return leftIndex - rightIndex
    })
    .map(([category, groupBuckets]) => {
      const groups = [...groupBuckets.values()]
        .sort((left, right) => normalizeLabel(left.label, '').localeCompare(normalizeLabel(right.label, ''), 'zh-Hans-CN'))
        .map((group) => {
          const children = group.entities
            .slice()
            .sort((left, right) => normalizeLabel(left.name, '').localeCompare(normalizeLabel(right.name, ''), 'zh-Hans-CN'))
            .map(createEntityNode)
          return {
            id: `group:${category}:${group.groupSlug}`,
            label: normalizeLabel(group.label, '未分组'),
            nodeType: 'group',
            category,
            groupSlug: group.groupSlug,
            entityCount: children.length,
            needsReviewCount: children.filter((child) => child.data?.system_needs_review).length,
            children,
          }
        })

      return {
      id: `category:${category}`,
      label: category,
      nodeType: 'category',
      category,
      entityCount: groups.reduce((total, group) => total + group.entityCount, 0),
      needsReviewCount: groups.reduce((total, group) => total + group.needsReviewCount, 0),
      children: groups,
    }
    })
}

const buildEntityTreeFromSearchResults = (groups = []) => {
  const categoryBuckets = new Map()

  for (const group of groups) {
    const category = group.category || '其他'
    if (!categoryBuckets.has(category)) categoryBuckets.set(category, [])
    categoryBuckets.get(category).push(group)
  }

  return [...categoryBuckets.entries()]
    .map(([category, groupsInCategory]) => {
      const children = groupsInCategory.map((group) => {
        const entityChildren = (group.entities || []).map(createEntityNode)
        return {
          id: `group:${category}:${group.group_id || group.group_slug || group.group_name || 'ungrouped'}`,
          label: normalizeLabel(group.group_name || group.group_slug, '未分组'),
          nodeType: 'group',
          category,
          groupId: group.group_id || null,
          groupSlug: group.group_slug || null,
          entityCount: entityChildren.length,
          needsReviewCount: entityChildren.filter((child) => child.data?.system_needs_review).length,
          children: entityChildren,
        }
      })

      return {
      id: `category:${category}`,
      label: category,
      nodeType: 'category',
      category,
      entityCount: children.reduce((total, group) => total + group.entityCount, 0),
      needsReviewCount: children.reduce((total, group) => total + group.needsReviewCount, 0),
      children,
    }
    })
}

const buildEntityTree = (items = []) => {
  if (!Array.isArray(items) || items.length === 0) return []
  return items.some(item => Array.isArray(item.entities))
    ? buildEntityTreeFromSearchResults(items)
    : buildEntityTreeFromEntities(items)
}

const flattenSearchResults = (groups = []) =>
  groups.flatMap((group) =>
    (group.entities || []).map((entity) => ({
      ...entity,
      type: entity.type || group.category || 'other',
      search_category: group.category || null,
      search_group_id: group.group_id || null,
      search_group_slug: group.group_slug || null,
      search_group_name: group.group_name || null,
      search_match_reason: entity.match_reason || '',
      search_score: entity.score ?? null,
    }))
  )

const findEntityNodeById = (nodes = [], entityId) => {
  if (!entityId) return null
  for (const node of nodes) {
    if (node.entityId === entityId) return node
    const match = findEntityNodeById(node.children || [], entityId)
    if (match) return match
  }
  return null
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
    entityTree: [],
    selectedEntityNode: null,
    entitySearchQuery: '',
    entityCommittedSearchQuery: '',
    entitySearchResults: [],
    selectedEntityDetail: null,
    entityRequestToken: 0,
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
    clearEntityWorkspaceState() {
      this.entityRequestToken += 1
      this.entities = []
      this.entityRelationships = []
      this.entityTree = []
      this.selectedEntityNode = null
      this.entitySearchQuery = ''
      this.entityCommittedSearchQuery = ''
      this.entitySearchResults = []
      this.selectedEntityDetail = null
    },

    resetDashboardSupplemental() {
      this.clearEntityWorkspaceState()
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
      const [state, stats, chapters, synopsis, volumePlan] = await Promise.all([
        api.getNovelState(this.novelId),
        api.getArchiveStats(this.novelId).catch(() => ({})),
        api.getChapters(this.novelId).catch(() => ({ items: [] })),
        api.getSynopsis(this.novelId).catch(() => null),
        api.getVolumePlan(this.novelId).catch(() => null),
      ])
      this.novelState = state
      this.archiveStats = stats
      this.chapters = chapters.items || []
      this.synopsisContent = synopsis?.content || ''
      this.synopsisData = synopsis?.synopsis_data || state.checkpoint_data?.synopsis_data || null
      this.volumePlan = volumePlan || state.checkpoint_data?.current_volume_plan || null
      this.syncCurrentChapter()
    },

    async loadDashboardSupplemental() {
      if (!this.novelId) return

      const panelTasks = {
        entities: async () => { await this.fetchEntities() },
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
      if (!this.novelId) return
      const requestToken = ++this.entityRequestToken
      const requestedNovelId = this.novelId
      const selectedEntityId = this.selectedEntityNode?.entityId || this.selectedEntityDetail?.entity_id || null
      const [entities, relationships] = await Promise.all([
        api.getEntities(this.novelId),
        api.getEntityRelationships(this.novelId).catch(() => ({ items: [] })),
      ])
      if (requestToken !== this.entityRequestToken || requestedNovelId !== this.novelId) return
      this.entities = entities.items || []
      this.entityRelationships = relationships.items || []
      this.entitySearchQuery = ''
      this.entitySearchResults = []
      this.entityTree = buildEntityTree(this.entities)
      const selectedNode = findEntityNodeById(this.entityTree, selectedEntityId)
      this.selectedEntityNode = selectedNode || null
      this.selectedEntityDetail = selectedNode?.data || null
    },

    async searchEntities(query) {
      if (!this.novelId) return
      const normalizedQuery = (query || '').trim()
      if (!normalizedQuery) {
        this.clearEntityWorkspaceState()
        await this.fetchEntities()
        return
      }

      const requestToken = ++this.entityRequestToken
      const requestedNovelId = this.novelId
      this.entityCommittedSearchQuery = normalizedQuery
      const selectedEntityId = this.selectedEntityNode?.entityId || this.selectedEntityDetail?.entity_id || null
      const [results, relationships] = await Promise.all([
        api.searchEntities(this.novelId, { q: normalizedQuery }),
        this.entityRelationships.length
          ? Promise.resolve({ items: this.entityRelationships })
          : api.getEntityRelationships(this.novelId).catch(() => ({ items: [] })),
      ])
      if (requestToken !== this.entityRequestToken || requestedNovelId !== this.novelId) return
      this.entitySearchResults = results.items || []
      this.entityTree = buildEntityTree(this.entitySearchResults)
      this.entities = flattenSearchResults(this.entitySearchResults)
      this.entityRelationships = relationships.items || []
      const selectedNode = findEntityNodeById(this.entityTree, selectedEntityId)
      this.selectedEntityNode = selectedNode || null
      this.selectedEntityDetail = selectedNode?.data || null
    },

    async saveEntityClassification(entityIds, payload) {
      if (!this.novelId) return
      const ids = Array.isArray(entityIds) ? entityIds.filter(Boolean) : [entityIds].filter(Boolean)
      if (!ids.length) return
      await Promise.all(ids.map((entityId) => api.updateEntityClassification(this.novelId, entityId, payload)))
      if (this.entityCommittedSearchQuery) {
        await this.searchEntities(this.entityCommittedSearchQuery)
        return
      }
      await this.fetchEntities()
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
