import { defineStore } from 'pinia'
import * as api from '@/api.js'
import { buildOutlineWorkbenchItems, resolveOutlineWorkbenchSelection } from '@/views/outline/outlineWorkbench.js'

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
const FLOW_ACTION_KEYS = ['brainstorm', 'volume_plan', 'context', 'draft', 'advance', 'librarian', 'auto_chapter']
const FLOW_ACTION_LABELS = {
  brainstorm: '停止脑暴',
  volume_plan: '停止生成大纲',
  context: '停止准备上下文',
  draft: '停止写作草稿',
  advance: '停止推进流程',
  librarian: '停止归档',
  auto_chapter: '停止自动写章',
}
const FLOW_TASK_LABELS = {
  brainstorm: '停止脑暴',
  generate_synopsis: '停止生成大纲',
  revise_synopsis: '停止生成大纲',
  revise_synopsis_with_feedback: '停止生成大纲',
  generate_volume_plan: '停止生成大纲',
  revise_volume_plan: '停止生成大纲',
  expand_volume_plan_batch: '停止生成大纲',
  plan: '停止生成大纲',
  context: '停止准备上下文',
  prepare_context: '停止准备上下文',
  draft: '停止写作草稿',
  write: '停止写作草稿',
  write_chapter: '停止写作草稿',
  advance: '停止推进流程',
  librarian: '停止归档',
  auto_run: '停止自动写章',
}
const FLOW_STARTED_STATUSES = new Set(['started', 'llm_call'])
const FLOW_TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'stopped', 'cancelled', 'canceled', 'completed', 'stop_requested'])

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

const createOutlineWorkbenchState = () => ({
  state: 'idle',
  error: '',
  submitting: false,
  reviewing: false,
  creatingKey: '',
  items: [],
  selection: null,
  currentItem: null,
  messages: [],
  sessionId: '',
  conversationSummary: '',
  lastResultSnapshot: null,
  requestToken: 0,
})

const createBrainstormWorkspaceState = () => ({
  state: 'idle',
  error: '',
  submitting: false,
  updatingCardId: '',
  data: null,
  lastRoundSummary: null,
  requestToken: 0,
})

const createSettingWorkbenchState = () => ({
  state: 'idle',
  error: '',
  sessions: [],
  reviewBatches: [],
  selectedSessionId: '',
  selectedSession: null,
  selectedMessages: [],
  selectedReviewBatch: null,
  selectedReviewChanges: [],
  requestToken: 0,
  sessionRequestToken: 0,
  consolidationRequestToken: 0,
  reviewBatchesRequestToken: 0,
  selectedReviewBatchRequestToken: 0,
  localMessageSeq: 0,
  creatingSession: false,
  replying: false,
  generating: false,
  applyingBatch: false,
  consolidationSubmitting: false,
  consolidationJob: null,
})

const createPendingDocActionState = () => ({
  approvingPendingId: '',
  rejectingPendingId: '',
  deletingPendingId: '',
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

const getEntityScope = (entity) => {
  const usage = entity.knowledge_usage || entity.latest_state?._knowledge_usage
  if (usage !== 'domain') {
    return {
      id: 'scope:global',
      label: '全局实体',
      scopeType: 'global',
      domainId: null,
      domainName: null,
    }
  }
  const domainId = entity.knowledge_domain_id || entity.latest_state?._knowledge_domain_id || 'unknown'
  const domainName = normalizeLabel(entity.knowledge_domain_name || entity.latest_state?._knowledge_domain_name, '未命名规则域')
  return {
    id: `scope:domain:${domainId}`,
    label: domainName,
    scopeType: 'domain',
    domainId,
    domainName,
  }
}

const createEntityNode = (entity) => ({
  id: `entity:${entity.entity_id}`,
  label: normalizeLabel(entity.name, '未命名实体'),
  nodeType: 'entity',
  entityId: entity.entity_id,
  data: entity,
  children: [],
})

const buildEntityCategoryNodes = (entities = [], scopeId = '') => {
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
            id: `${scopeId}:group:${category}:${group.groupSlug}`,
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
      id: `${scopeId}:category:${category}`,
      label: category,
      nodeType: 'category',
      category,
      entityCount: groups.reduce((total, group) => total + group.entityCount, 0),
      needsReviewCount: groups.reduce((total, group) => total + group.needsReviewCount, 0),
      children: groups,
    }
    })
}

const buildEntityTreeFromEntities = (entities = []) => {
  const scopeBuckets = new Map()
  for (const entity of entities) {
    const scope = getEntityScope(entity)
    if (!scopeBuckets.has(scope.id)) {
      scopeBuckets.set(scope.id, {
        ...scope,
        entities: [],
      })
    }
    scopeBuckets.get(scope.id).entities.push(entity)
  }

  return [...scopeBuckets.values()]
    .sort((left, right) => {
      if (left.scopeType !== right.scopeType) return left.scopeType === 'global' ? -1 : 1
      return normalizeLabel(left.label, '').localeCompare(normalizeLabel(right.label, ''), 'zh-Hans-CN')
    })
    .map((scope) => {
      const children = buildEntityCategoryNodes(scope.entities, scope.id)
      return {
        id: scope.id,
        label: scope.scopeType === 'global' ? '全局实体' : `规则域：${scope.label}`,
        nodeType: 'scope',
        scopeType: scope.scopeType,
        domainId: scope.domainId,
        domainName: scope.domainName,
        entityCount: scope.entities.length,
        needsReviewCount: children.reduce((total, category) => total + category.needsReviewCount, 0),
        children,
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

const flowKeyFromLog = (log = {}) => [
  log.agent || '',
  log.node || '',
  log.task || '',
].join(':')

const resolveFlowLabelFromLog = (log = {}) => {
  const task = log.task || log.node || ''
  if (FLOW_TASK_LABELS[task]) return FLOW_TASK_LABELS[task]
  const message = log.message || ''
  if (message.includes('大纲') || message.includes('卷纲') || message.includes('总纲')) return '停止生成大纲'
  if (message.includes('脑暴')) return '停止脑暴'
  if (message.includes('上下文')) return '停止准备上下文'
  if (message.includes('草稿') || message.includes('写作')) return '停止写作草稿'
  if (message.includes('归档')) return '停止归档'
  return '停止当前流程'
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
    pendingDocsRequestToken: 0,
    knowledgeDomains: [],
    pendingDocActions: createPendingDocActionState(),
    outlineWorkbench: createOutlineWorkbenchState(),
    brainstormWorkspace: createBrainstormWorkspaceState(),
    settingWorkbench: createSettingWorkbenchState(),
    documents: [],
    documentDetail: null,
    documentVersions: [],
    loadingActions: {},
    flowActivity: {
      active: false,
      label: '',
      updatedAt: '',
    },
    autoRunJob: null,
    autoRunLastResult: null,
    chapterRewriteJobs: {},
    chapterRewriteLastResults: {},
    worldStateReviews: [],
    worldStateReviewRequestToken: 0,
    globalConsistencyAudit: null,
    stoppingFlow: false,
    dashboardPanels: createDashboardPanels(),
    dashboardLastUpdated: '',
  }),

  getters: {
    novelTitle: (s) => (
      s.novelState.title
      || s.novelState.checkpoint_data?.novel_title
      || s.novelState.checkpoint_data?.title
      || s.novelId
      || '未选择小说'
    ),
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
    canAutoRunChapter: (s) => ['context_preparation', 'drafting', 'reviewing', 'editing', 'fast_reviewing', 'librarian'].includes(s.novelState.current_phase),
    hasRunningFlowAction: (s) => FLOW_ACTION_KEYS.some(key => Boolean(s.loadingActions?.[key])),
    shouldShowStopFlow: (s) => (
      Boolean(s.novelId)
      && (
        FLOW_ACTION_KEYS.some(key => Boolean(s.loadingActions?.[key]))
        || Boolean(s.outlineWorkbench.submitting)
        || Boolean(s.outlineWorkbench.creatingKey)
        || Boolean(s.brainstormWorkspace.submitting)
        || Boolean(s.flowActivity.active)
      )
    ),
    stopFlowLabel: (s) => {
      const activeKey = FLOW_ACTION_KEYS.find(key => Boolean(s.loadingActions?.[key]))
      if (activeKey && FLOW_ACTION_LABELS[activeKey]) return FLOW_ACTION_LABELS[activeKey]
      if (s.outlineWorkbench.submitting || s.outlineWorkbench.creatingKey) return '停止生成大纲'
      if (s.brainstormWorkspace.submitting) return '停止脑暴'
      return s.flowActivity.label || '停止当前流程'
    },
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
      this.documents = []
      this.documentDetail = null
      this.documentVersions = []
      this.pendingDocActions = createPendingDocActionState()
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

    resetCurrentNovel() {
      this.novelId = ''
      this.novelState = {}
      this.archiveStats = {}
      this.currentChapter = null
      this.chapters = []
      this.volumePlan = null
      this.synopsisContent = ''
      this.synopsisData = null
      this.spacelines = []
      this.outlineWorkbench = createOutlineWorkbenchState()
      this.brainstormWorkspace = createBrainstormWorkspaceState()
      this.settingWorkbench = createSettingWorkbenchState()
      this.loadingActions = {}
      this.flowActivity = { active: false, label: '', updatedAt: '' }
      this.autoRunJob = null
      this.autoRunLastResult = null
      this.chapterRewriteJobs = {}
      this.chapterRewriteLastResults = {}
      this.worldStateReviews = []
      this.worldStateReviewRequestToken += 1
      this.globalConsistencyAudit = null
      this.stoppingFlow = false
      this.resetDashboardSupplemental()
    },

    async loadNovel(novelId) {
      this.novelId = novelId
      this.resetDashboardSupplemental()
      this.settingWorkbench = createSettingWorkbenchState()
      await this.refreshState()
    },

    async updateNovelTitle(title) {
      if (!this.novelId) return null
      const updated = await api.updateNovel(this.novelId, title)
      this.novelState = {
        ...this.novelState,
        ...updated,
        checkpoint_data: updated.checkpoint_data || this.novelState.checkpoint_data || {},
      }
      return updated
    },

    async refreshState() {
      if (!this.novelId) return
      const state = await api.getNovelState(this.novelId)
      const shouldLoadVolumePlan = !!state.checkpoint_data?.current_volume_plan
      const [stats, chapters, synopsis, volumePlan, rewriteJobs] = await Promise.all([
        api.getArchiveStats(this.novelId).catch(() => ({})),
        api.getChapters(this.novelId).catch(() => ({ items: [] })),
        api.getSynopsis(this.novelId).catch(() => null),
        shouldLoadVolumePlan ? api.getVolumePlan(this.novelId).catch(() => null) : Promise.resolve(null),
        api.getChapterRewriteJobs(this.novelId).catch(() => ({ items: [] })),
      ])
      this.novelState = state
      this.archiveStats = stats
      this.chapters = chapters.items || []
      this.synopsisContent = synopsis?.content || ''
      this.synopsisData = synopsis?.synopsis_data || state.checkpoint_data?.synopsis_data || null
      this.volumePlan = volumePlan || state.checkpoint_data?.current_volume_plan || null
      this.chapterRewriteJobs = Object.fromEntries(
        (rewriteJobs.items || [])
          .filter(item => item?.chapter_id && item?.job)
          .map(item => [item.chapter_id, item.job]),
      )
      if (state.current_phase !== 'brainstorming') {
        this.brainstormWorkspace = createBrainstormWorkspaceState()
      }
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

    async executeAction(actionType, options = {}) {
      this.loadingActions[actionType] = true
      try {
        const shouldRefreshDashboard = false
        if (actionType === 'auto_chapter') {
          this.autoRunLastResult = null
        }
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
          case 'auto_chapter':
            this.autoRunJob = await api.autoRunChapters(this.novelId, {
              max_chapters: Number.isFinite(Number(options.max_chapters)) ? Math.max(1, Math.floor(Number(options.max_chapters))) : 1,
              stop_at_volume_end: options.stop_at_volume_end ?? true,
            })
            break
          case 'export': await api.exportNovel(this.novelId); break
        }
        await this.loadNovel(this.novelId)
        if (shouldRefreshDashboard) {
          await this.loadDashboardSupplemental()
        }
      } catch (error) {
        if (actionType === 'auto_chapter') {
          const detail = error?.response?.data?.detail
          if (detail && typeof detail === 'object') {
            this.autoRunLastResult = detail
            if (detail.stopped_reason === 'waiting_world_state_review') {
              await this.fetchWorldStateReviews('pending').catch(() => null)
            }
            await this.loadNovel(this.novelId)
          }
        }
        throw error
      } finally {
        this.loadingActions[actionType] = false
      }
    },

    async refreshAutoRunJob() {
      if (!this.novelId || !this.autoRunJob?.job_id) return
      const job = await api.getGenerationJob(this.novelId, this.autoRunJob.job_id)
      this.autoRunJob = job
      const result = job.result_payload
      if (result && result.stopped_reason === 'failed') {
        this.autoRunLastResult = result
      }
      if (['succeeded', 'failed', 'cancelled'].includes(job.status)) {
        await this.refreshState()
      }
    },

    async rewriteChapter(chapterId, options = {}) {
      if (!this.novelId || !chapterId) return null
      const loadingKey = `rewrite:${chapterId}`
      this.loadingActions[loadingKey] = true
      try {
        const hasOptions = options && Object.keys(options).length > 0
        const job = hasOptions
          ? await api.rewriteChapter(this.novelId, chapterId, options)
          : await api.rewriteChapter(this.novelId, chapterId)
        this.chapterRewriteJobs = {
          ...this.chapterRewriteJobs,
          [chapterId]: job,
        }
        await this.refreshState()
        return job
      } finally {
        this.loadingActions[loadingKey] = false
      }
    },

    async refreshChapterRewriteJob(chapterId) {
      if (!this.novelId || !chapterId) return null
      const current = this.chapterRewriteJobs?.[chapterId]
      if (!current?.job_id) return null
      const job = await api.getGenerationJob(this.novelId, current.job_id)
      this.chapterRewriteJobs = {
        ...this.chapterRewriteJobs,
        [chapterId]: job,
      }
      if (job.result_payload) {
        this.chapterRewriteLastResults = {
          ...this.chapterRewriteLastResults,
          [chapterId]: job.result_payload,
        }
      }
      if (['succeeded', 'failed', 'cancelled'].includes(job.status)) {
        await Promise.all([
          this.refreshState(),
          this.fetchEntities().catch(() => null),
          this.fetchTimelines().catch(() => null),
          this.fetchSpacelines().catch(() => null),
          this.fetchForeshadowings().catch(() => null),
        ])
      }
      return job
    },

    async fetchWorldStateReviews(status = '') {
      if (!this.novelId) {
        this.worldStateReviews = []
        return []
      }
      const requestedNovelId = this.novelId
      const requestToken = this.worldStateReviewRequestToken + 1
      this.worldStateReviewRequestToken = requestToken
      const payload = await api.getWorldStateReviews(requestedNovelId, status)
      if (requestedNovelId !== this.novelId || requestToken !== this.worldStateReviewRequestToken) {
        return this.worldStateReviews
      }
      this.worldStateReviews = payload?.items || []
      return this.worldStateReviews
    },

    async resolveWorldStateReview(reviewId, payload) {
      if (!this.novelId || !reviewId) return null
      const review = await api.resolveWorldStateReview(this.novelId, reviewId, payload)
      this.worldStateReviews = this.worldStateReviews.map((item) =>
        item.id === review.id ? review : item
      )
      await Promise.all([
        this.fetchEntities().catch(() => null),
        this.fetchTimelines().catch(() => null),
        this.fetchSpacelines().catch(() => null),
        this.fetchForeshadowings().catch(() => null),
      ])
      return review
    },

    async runGlobalConsistencyAudit() {
      if (!this.novelId) return null
      const result = await api.runGlobalConsistencyAudit(this.novelId)
      this.globalConsistencyAudit = result
      return result
    },

    async stopCurrentFlow() {
      if (!this.novelId) return
      if (this.stoppingFlow) return
      this.stoppingFlow = true
      try {
        await api.stopCurrentFlow(this.novelId)
        await this.refreshState()
        this.flowActivity = { active: false, label: '', updatedAt: new Date().toISOString() }
      } finally {
        this.stoppingFlow = false
      }
    },

    syncFlowActivityFromLogs(logs = []) {
      const activeByKey = new Map()
      for (const log of logs || []) {
        if (!log?.status) continue
        const key = flowKeyFromLog(log)
        if (!key.trim()) continue
        if (FLOW_STARTED_STATUSES.has(log.status)) {
          activeByKey.set(key, {
            label: resolveFlowLabelFromLog(log),
            updatedAt: log.timestamp || '',
          })
        } else if (FLOW_TERMINAL_STATUSES.has(log.status)) {
          activeByKey.delete(key)
        }
      }

      const active = Array.from(activeByKey.values()).pop()
      this.flowActivity = active
        ? { active: true, label: active.label, updatedAt: active.updatedAt }
        : { active: false, label: '', updatedAt: this.flowActivity.updatedAt }
    },

    async fetchEntities(options = {}) {
      if (!this.novelId) return
      const params = options.includeArchived ? { include_archived: true } : {}
      const requestToken = ++this.entityRequestToken
      const requestedNovelId = this.novelId
      const selectedEntityId = this.selectedEntityNode?.entityId || this.selectedEntityDetail?.entity_id || null
      const [entities, relationships] = await Promise.all([
        api.getEntities(this.novelId, params),
        api.getEntityRelationships(this.novelId, params).catch(() => ({ items: [] })),
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

    async searchEntities(query, options = {}) {
      if (!this.novelId) return
      const normalizedQuery = (query || '').trim()
      if (!normalizedQuery) {
        this.clearEntityWorkspaceState()
        await this.fetchEntities(options)
        return
      }

      const params = options.includeArchived ? { include_archived: true } : {}
      const requestToken = ++this.entityRequestToken
      const requestedNovelId = this.novelId
      this.entityCommittedSearchQuery = normalizedQuery
      const selectedEntityId = this.selectedEntityNode?.entityId || this.selectedEntityDetail?.entity_id || null
      const [results, relationships] = await Promise.all([
        api.searchEntities(this.novelId, { q: normalizedQuery, ...params }),
        this.entityRelationships.length && !options.includeArchived
          ? Promise.resolve({ items: this.entityRelationships })
          : api.getEntityRelationships(this.novelId, params).catch(() => ({ items: [] })),
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

    async saveEntityClassification(entityIds, payload, options = {}) {
      if (!this.novelId) return
      const ids = Array.isArray(entityIds) ? entityIds.filter(Boolean) : [entityIds].filter(Boolean)
      if (!ids.length) return
      await Promise.all(ids.map((entityId) => api.updateEntityClassification(this.novelId, entityId, payload)))
      if (this.entityCommittedSearchQuery) {
        await this.searchEntities(this.entityCommittedSearchQuery, options)
        return
      }
      await this.fetchEntities(options)
    },

    async updateEntity(entityId, payload, options = {}) {
      if (!this.novelId || !entityId) return
      await api.updateEntity(this.novelId, entityId, payload)
      if (this.entityCommittedSearchQuery) {
        await this.searchEntities(this.entityCommittedSearchQuery, options)
        return
      }
      await this.fetchEntities(options)
    },

    async deleteEntity(entityId, options = {}) {
      if (!this.novelId || !entityId) return
      await api.deleteEntity(this.novelId, entityId)
      if (this.entityCommittedSearchQuery) {
        await this.searchEntities(this.entityCommittedSearchQuery, options)
        return
      }
      await this.fetchEntities(options)
    },

    async deleteCurrentNovel() {
      if (!this.novelId) return
      const novelId = this.novelId
      await api.deleteNovel(novelId)
      this.resetCurrentNovel()
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
      if (!this.novelId) return []
      const requestedNovelId = this.novelId
      const requestToken = this.pendingDocsRequestToken + 1
      this.pendingDocsRequestToken = requestToken
      const [pending, documents] = await Promise.all([
        Promise.resolve(api.getPendingDocs(requestedNovelId)).catch(() => ({ items: [] })),
        Promise.resolve(api.getDocuments(requestedNovelId)).catch(() => ({ items: [] })),
      ])
      if (requestToken !== this.pendingDocsRequestToken || requestedNovelId !== this.novelId) return []
      this.pendingDocs = pending.items || []
      this.documents = documents.items || []
      return this.pendingDocs
    },

    async fetchDocumentDetail(documentId) {
      this.documentDetail = await api.getDocumentDetail(this.novelId, documentId)
    },

    async fetchDocumentVersions(docType) {
      const res = await api.getDocumentVersions(this.novelId, docType)
      this.documentVersions = res.items || []
    },

    async saveDocumentVersion(documentId, payload) {
      const saved = await api.saveDocumentVersion(this.novelId, documentId, payload)
      await this.fetchDocuments()
      await this.fetchDocumentDetail(saved.id)
      await this.fetchDocumentVersions(saved.doc_type)
      return saved
    },

    async reindexDocument(documentId) {
      return api.reindexDocument(this.novelId, documentId)
    },

    async fetchSettingWorkbench() {
      if (!this.novelId) {
        this.settingWorkbench = createSettingWorkbenchState()
        return
      }
      this.settingWorkbench.state = 'loading'
      this.settingWorkbench.error = ''
      const requestedNovelId = this.novelId
      const token = this.settingWorkbench.requestToken + 1
      this.settingWorkbench.requestToken = token
      try {
        const payload = await api.getSettingWorkbench(requestedNovelId)
        if (token !== this.settingWorkbench.requestToken || requestedNovelId !== this.novelId) return
        this.settingWorkbench.sessions = payload?.sessions || []
        this.settingWorkbench.reviewBatches = payload?.review_batches || []
        if (this.settingWorkbench.selectedSessionId) {
          this.settingWorkbench.selectedSession = this.settingWorkbench.sessions.find(
            (session) => session.id === this.settingWorkbench.selectedSessionId
          ) || this.settingWorkbench.selectedSession
        }
        this.settingWorkbench.state = 'ready'
      } catch (error) {
        if (token !== this.settingWorkbench.requestToken || requestedNovelId !== this.novelId) return
        this.settingWorkbench.state = 'error'
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '加载设定工作台失败'
      }
    },

    async fetchSettingSessions() {
      if (!this.novelId) {
        this.settingWorkbench = createSettingWorkbenchState()
        return []
      }
      this.settingWorkbench.state = 'loading'
      this.settingWorkbench.error = ''
      const requestedNovelId = this.novelId
      const token = this.settingWorkbench.requestToken + 1
      this.settingWorkbench.requestToken = token
      try {
        const payload = await api.getSettingSessions(requestedNovelId)
        if (token !== this.settingWorkbench.requestToken || requestedNovelId !== this.novelId) {
          return this.settingWorkbench.sessions
        }
        this.settingWorkbench.sessions = payload?.items || payload?.sessions || []
        if (this.settingWorkbench.selectedSessionId) {
          this.settingWorkbench.selectedSession = this.settingWorkbench.sessions.find(
            (session) => session.id === this.settingWorkbench.selectedSessionId
          ) || this.settingWorkbench.selectedSession
        }
        this.settingWorkbench.state = 'ready'
        return this.settingWorkbench.sessions
      } catch (error) {
        if (token !== this.settingWorkbench.requestToken || requestedNovelId !== this.novelId) {
          return this.settingWorkbench.sessions
        }
        this.settingWorkbench.state = 'error'
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '加载设定会话失败'
        throw error
      }
    },

    async createSettingSession(payload) {
      if (!this.novelId) return null
      const requestedNovelId = this.novelId
      this.settingWorkbench.creatingSession = true
      this.settingWorkbench.error = ''
      try {
        const session = await api.createSettingSession(requestedNovelId, payload)
        if (requestedNovelId !== this.novelId) return null
        this.settingWorkbench.requestToken += 1
        this.settingWorkbench.sessions = [
          session,
          ...this.settingWorkbench.sessions.filter((item) => item.id !== session.id),
        ]
        this.settingWorkbench.selectedSessionId = session.id
        this.settingWorkbench.selectedSession = session
        this.settingWorkbench.selectedMessages = []
        await this.loadSettingSession(session.id)
        return session
      } catch (error) {
        if (requestedNovelId !== this.novelId) return null
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '创建设定会话失败'
        throw error
      } finally {
        if (requestedNovelId === this.novelId) {
          this.settingWorkbench.creatingSession = false
        }
      }
    },

    async loadSettingSession(sessionId) {
      if (!this.novelId || !sessionId) return null
      this.settingWorkbench.error = ''
      const requestedNovelId = this.novelId
      const token = this.settingWorkbench.sessionRequestToken + 1
      this.settingWorkbench.sessionRequestToken = token
      try {
        const payload = await api.getSettingSession(requestedNovelId, sessionId)
        if (token !== this.settingWorkbench.sessionRequestToken || requestedNovelId !== this.novelId) return null
        this.settingWorkbench.selectedSessionId = sessionId
        this.settingWorkbench.selectedSession = payload?.session || this.settingWorkbench.sessions.find((session) => session.id === sessionId) || null
        this.settingWorkbench.selectedMessages = payload?.messages || payload?.recent_messages || []
        return payload
      } catch (error) {
        if (token !== this.settingWorkbench.sessionRequestToken || requestedNovelId !== this.novelId) return null
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '加载设定会话失败'
        throw error
      }
    },

    async replySettingSession(content) {
      if (!this.novelId || !this.settingWorkbench.selectedSessionId) return null
      const sessionId = this.settingWorkbench.selectedSessionId
      this.settingWorkbench.replying = true
      this.settingWorkbench.error = ''
      try {
        const payload = await api.replySettingSession(this.novelId, sessionId, { content })
        if (this.settingWorkbench.selectedSessionId !== sessionId) return payload
        this.settingWorkbench.selectedSession = payload?.session || this.settingWorkbench.selectedSession
        this.settingWorkbench.sessions = this.settingWorkbench.sessions.map((session) =>
          session.id === sessionId
            ? { ...session, ...this.settingWorkbench.selectedSession }
            : session
        )
        const nextLocalMessageId = () => {
          this.settingWorkbench.localMessageSeq += 1
          return `${sessionId}:local:${this.settingWorkbench.localMessageSeq}`
        }
        this.settingWorkbench.selectedMessages.push({ id: nextLocalMessageId(), role: 'user', content })
        if (payload?.assistant_message) {
          this.settingWorkbench.selectedMessages.push({
            id: nextLocalMessageId(),
            role: 'assistant',
            content: payload.assistant_message,
            meta: { questions: payload.questions || [] },
          })
        }
        return payload
      } catch (error) {
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '发送澄清回答失败'
        throw error
      } finally {
        this.settingWorkbench.replying = false
      }
    },

    async generateSettingReviewBatch(payload = {}) {
      if (!this.novelId || !this.settingWorkbench.selectedSessionId) return null
      const sessionId = this.settingWorkbench.selectedSessionId
      this.settingWorkbench.generating = true
      this.settingWorkbench.error = ''
      try {
        const batch = await api.generateSettingReviewBatch(this.novelId, sessionId, payload)
        this.settingWorkbench.reviewBatches = [
          batch,
          ...this.settingWorkbench.reviewBatches.filter((item) => item.id !== batch.id),
        ]
        if (this.settingWorkbench.selectedSessionId === sessionId && this.settingWorkbench.selectedSession) {
          this.settingWorkbench.selectedSession = {
            ...this.settingWorkbench.selectedSession,
            status: 'generated',
          }
          this.settingWorkbench.sessions = this.settingWorkbench.sessions.map((session) =>
            session.id === sessionId
              ? { ...session, status: 'generated' }
              : session
          )
        }
        return batch
      } catch (error) {
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '生成审核记录失败'
        throw error
      } finally {
        this.settingWorkbench.generating = false
      }
    },

    async startSettingConsolidation(selectedPendingIds = []) {
      if (!this.novelId) return null
      if (this.settingWorkbench.consolidationSubmitting) return null
      const requestedNovelId = this.novelId
      const requestToken = this.settingWorkbench.consolidationRequestToken + 1
      this.settingWorkbench.consolidationRequestToken = requestToken
      this.settingWorkbench.consolidationSubmitting = true
      this.settingWorkbench.error = ''
      try {
        const job = await api.startSettingConsolidation(requestedNovelId, selectedPendingIds)
        if (requestedNovelId !== this.novelId || requestToken !== this.settingWorkbench.consolidationRequestToken) return null
        this.settingWorkbench.consolidationJob = job
        return job
      } catch (error) {
        if (requestedNovelId !== this.novelId || requestToken !== this.settingWorkbench.consolidationRequestToken) return null
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '请求失败'
        throw error
      } finally {
        if (requestedNovelId === this.novelId && requestToken === this.settingWorkbench.consolidationRequestToken) {
          this.settingWorkbench.consolidationSubmitting = false
        }
      }
    },

    async fetchSettingReviewBatches() {
      if (!this.novelId) return []
      const requestedNovelId = this.novelId
      const requestToken = this.settingWorkbench.reviewBatchesRequestToken + 1
      this.settingWorkbench.reviewBatchesRequestToken = requestToken
      this.settingWorkbench.error = ''
      try {
        const payload = await api.getSettingReviewBatches(requestedNovelId)
        if (requestedNovelId !== this.novelId || requestToken !== this.settingWorkbench.reviewBatchesRequestToken) {
          return this.settingWorkbench.reviewBatches
        }
        this.settingWorkbench.reviewBatches = payload?.items || []
        return this.settingWorkbench.reviewBatches
      } catch (error) {
        if (requestedNovelId !== this.novelId || requestToken !== this.settingWorkbench.reviewBatchesRequestToken) {
          return this.settingWorkbench.reviewBatches
        }
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '请求失败'
        throw error
      }
    },

    async loadSettingReviewBatch(batchId) {
      if (!this.novelId || !batchId) return null
      const requestedNovelId = this.novelId
      const requestToken = this.settingWorkbench.selectedReviewBatchRequestToken + 1
      this.settingWorkbench.selectedReviewBatchRequestToken = requestToken
      this.settingWorkbench.error = ''
      try {
        const payload = await api.getSettingReviewBatch(requestedNovelId, batchId)
        if (requestedNovelId !== this.novelId || requestToken !== this.settingWorkbench.selectedReviewBatchRequestToken) return null
        this.settingWorkbench.selectedReviewBatch = payload?.batch || null
        this.settingWorkbench.selectedReviewChanges = payload?.changes || []
        return payload
      } catch (error) {
        if (requestedNovelId !== this.novelId || requestToken !== this.settingWorkbench.selectedReviewBatchRequestToken) return null
        this.settingWorkbench.error = error?.response?.data?.detail || error?.message || '请求失败'
        throw error
      }
    },

    async fetchKnowledgeDomains(includeDisabled = true) {
      if (!this.novelId) {
        this.knowledgeDomains = []
        return
      }
      const result = await api.getKnowledgeDomains(this.novelId, includeDisabled).catch(() => ({ items: [] }))
      this.knowledgeDomains = result.items || []
    },

    async confirmKnowledgeDomainScope(domainId, scopeRefs, scopeType = 'volume') {
      if (!this.novelId || !domainId) return null
      const result = await api.confirmKnowledgeDomainScope(this.novelId, domainId, {
        scope_type: scopeType,
        scope_refs: scopeRefs,
      })
      await this.fetchKnowledgeDomains(true)
      return result.item
    },

    async disableKnowledgeDomain(domainId) {
      if (!this.novelId || !domainId) return null
      const result = await api.disableKnowledgeDomain(this.novelId, domainId)
      await this.fetchKnowledgeDomains(true)
      return result.item
    },

    async deleteKnowledgeDomain(domainId) {
      if (!this.novelId || !domainId) return null
      const result = await api.deleteKnowledgeDomain(this.novelId, domainId)
      await this.fetchKnowledgeDomains(true)
      return result
    },

    async saveSynopsis(content) {
      if (!this.novelId) return
      await api.importSynopsis(this.novelId, content)
      await this.loadNovel(this.novelId)
    },

    async refreshBrainstormWorkspace() {
      if (!this.novelId) return
      if (this.novelState.current_phase !== 'brainstorming') {
        this.brainstormWorkspace = createBrainstormWorkspaceState()
        return
      }

      const requestToken = this.brainstormWorkspace.requestToken + 1
      this.brainstormWorkspace.requestToken = requestToken
      this.brainstormWorkspace.state = 'loading'
      this.brainstormWorkspace.error = ''

      try {
        const workspace = await api.getBrainstormWorkspace(this.novelId)
        if (this.brainstormWorkspace.requestToken !== requestToken) return
        const previous = this.brainstormWorkspace.data
        const workspaceChanged = Boolean(
          previous &&
          (previous.workspace_id !== workspace?.workspace_id || previous.novel_id !== workspace?.novel_id)
        )
        if (workspaceChanged) {
          this.brainstormWorkspace.lastRoundSummary = null
        }
        this.brainstormWorkspace.data = workspace
        this.brainstormWorkspace.state = 'ready'
      } catch (error) {
        if (this.brainstormWorkspace.requestToken !== requestToken) return
        this.brainstormWorkspace.state = 'error'
        this.brainstormWorkspace.error = error?.message || '请求失败'
      }
    },

    async refreshOutlineWorkbench(selection = null) {
      if (!this.novelId) return
      const existingSelection = this.outlineWorkbench.selection
      const requestToken = this.outlineWorkbench.requestToken + 1
      this.outlineWorkbench.requestToken = requestToken
      this.outlineWorkbench.state = 'loading'
      this.outlineWorkbench.error = ''

      const requestedSelection = selection || existingSelection || {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
      }

      try {
        const workbench = await api.getOutlineWorkbench(this.novelId, requestedSelection)
        if (this.outlineWorkbench.requestToken !== requestToken) return
        const outlineItems = workbench?.outline_items || []
        const serviceSelection = workbench?.outline_type && workbench?.outline_ref
          ? {
            outline_type: workbench.outline_type,
            outline_ref: workbench.outline_ref,
          }
          : null
        const synopsisItem = outlineItems.find(
          (item) => item?.outline_type === 'synopsis' && item?.outline_ref === 'synopsis'
        )
        const defaultSelection = synopsisItem
          ? {
            outline_type: synopsisItem.outline_type,
            outline_ref: synopsisItem.outline_ref,
          }
          : serviceSelection
        const nextSelection = selection || existingSelection || defaultSelection
        const resolvedSelection = resolveOutlineWorkbenchSelection(outlineItems, nextSelection)
        const resolvedCurrentItem = resolveOutlineWorkbenchSelection(outlineItems, serviceSelection)
        const normalizedItems = buildOutlineWorkbenchItems({
          items: outlineItems,
          currentItem: resolvedCurrentItem,
        })
        const messages = resolvedSelection
          ? await api.getOutlineWorkbenchMessages(this.novelId, resolvedSelection)
          : {
            recent_messages: [],
            conversation_summary: '',
            last_result_snapshot: null,
            session_id: workbench?.session_id || '',
          }
        const workspace = this.novelState.current_phase === 'brainstorming'
          ? await api.getBrainstormWorkspace(this.novelId)
          : null
        if (this.outlineWorkbench.requestToken !== requestToken) return

        this.outlineWorkbench.items = normalizedItems
        this.outlineWorkbench.selection = resolvedSelection
        this.outlineWorkbench.currentItem = resolvedCurrentItem
        this.outlineWorkbench.messages = messages?.recent_messages || []
        this.outlineWorkbench.sessionId = messages?.session_id || workbench?.session_id || ''
        this.outlineWorkbench.conversationSummary = messages?.conversation_summary || ''
        this.outlineWorkbench.lastResultSnapshot = messages?.last_result_snapshot || null
        this.outlineWorkbench.state = 'ready'
        if (workspace) {
          const previous = this.brainstormWorkspace.data
          const workspaceChanged = Boolean(
            previous &&
            (previous.workspace_id !== workspace?.workspace_id || previous.novel_id !== workspace?.novel_id)
          )
          if (workspaceChanged) {
            this.brainstormWorkspace.lastRoundSummary = null
          }
          this.brainstormWorkspace.data = workspace
          this.brainstormWorkspace.state = 'ready'
          this.brainstormWorkspace.error = ''
        } else {
          this.brainstormWorkspace = createBrainstormWorkspaceState()
        }
      } catch (error) {
        if (this.outlineWorkbench.requestToken !== requestToken) return
        this.outlineWorkbench.state = 'error'
        this.outlineWorkbench.error = error?.message || '请求失败'
      }
    },

    async submitOutlineFeedback(payload) {
      if (!this.novelId) return
      if (this.outlineWorkbench.submitting) return
      const selection = this.outlineWorkbench.selection || {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
      }
      this.outlineWorkbench.submitting = true
      this.outlineWorkbench.error = ''
      try {
        const response = await api.submitOutlineFeedback(this.novelId, {
          outline_type: selection.outline_type,
          outline_ref: selection.outline_ref,
          ...payload,
        })
        if (this.novelState.current_phase === 'brainstorming') {
          this.brainstormWorkspace.lastRoundSummary = response?.setting_update_summary || null
        }
        const latestSelection = this.outlineWorkbench.selection
        const refreshSelection = latestSelection || selection
        await this.refreshOutlineWorkbench(refreshSelection)
      } finally {
        this.outlineWorkbench.submitting = false
      }
    },

    async clearOutlineContext() {
      if (!this.novelId) return
      const selection = this.outlineWorkbench.selection || {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
      }
      this.outlineWorkbench.error = ''
      await api.clearOutlineContext(this.novelId, {
        outline_type: selection.outline_type,
        outline_ref: selection.outline_ref,
      })
      this.outlineWorkbench.messages = []
      this.outlineWorkbench.conversationSummary = ''
      this.outlineWorkbench.lastResultSnapshot = null
      await this.refreshOutlineWorkbench(selection)
    },

    async reviewCurrentOutline() {
      if (!this.novelId) return
      const selection = this.outlineWorkbench.selection || {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
      }
      this.outlineWorkbench.reviewing = true
      this.outlineWorkbench.error = ''
      try {
        await api.reviewOutline(this.novelId, {
          outline_type: selection.outline_type,
          outline_ref: selection.outline_ref,
        })
        await this.refreshOutlineWorkbench(selection)
      } finally {
        this.outlineWorkbench.reviewing = false
      }
    },

    async submitBrainstormWorkspace() {
      if (!this.novelId) return
      if (this.brainstormWorkspace.submitting) return

      const refreshSelection = this.outlineWorkbench.selection || {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
      }

      this.brainstormWorkspace.submitting = true
      this.brainstormWorkspace.error = ''
      try {
        const result = await api.submitBrainstormWorkspace(this.novelId)
        await this.refreshState()
        if (this.novelState.current_phase === 'brainstorming') {
          await this.refreshBrainstormWorkspace()
        } else {
          this.brainstormWorkspace = createBrainstormWorkspaceState()
        }
        await this.refreshOutlineWorkbench(refreshSelection)
        return result
      } catch (error) {
        this.brainstormWorkspace.error = error?.message || '请求失败'
        throw error
      } finally {
        this.brainstormWorkspace.submitting = false
      }
    },

    async updateBrainstormSuggestionCard(cardId, action) {
      if (!this.novelId || !cardId || !action) return null
      if (this.brainstormWorkspace.updatingCardId) return null

      this.brainstormWorkspace.updatingCardId = cardId
      this.brainstormWorkspace.error = ''
      try {
        const result = await api.updateBrainstormSuggestionCard(this.novelId, cardId, { action })
        this.brainstormWorkspace.data = result.workspace
        this.brainstormWorkspace.state = 'ready'
        return result
      } catch (error) {
        this.brainstormWorkspace.error = error?.message || '请求失败'
        throw error
      } finally {
        this.brainstormWorkspace.updatingCardId = ''
      }
    },
  },
})
