# Dashboard Status Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将首页仪表盘升级为“全局汇报优先”的状态总览页，覆盖流程、章节、数据、运行状态、推荐动作和轻量风险提醒。

**Architecture:** 保留 `src/views/Dashboard.vue` 作为页面入口，把复杂逻辑拆成纯函数 summary 层、store 补充加载层和 5 个展示组件。第一版只复用现有 API、Pinia store 和 `/logs/stream`，通过前端聚合得到状态卡、最近更新和推荐动作，不新增首页专用后端接口。

**Tech Stack:** Vue 3, Pinia, Vite, Element Plus, vue-echarts, Vitest, Vue Test Utils, jsdom.

---

## File Map

| File | Responsibility |
|---|---|
| `src/novel_dev/web/package.json` | 增加前端测试脚本与测试依赖 |
| `src/novel_dev/web/package-lock.json` | 锁定新增测试依赖 |
| `src/novel_dev/web/vitest.config.js` | Vitest 配置、alias 与 jsdom 环境 |
| `src/novel_dev/web/src/test/setup.js` | 浏览器 API mock（`ResizeObserver`、`matchMedia`、`EventSource`） |
| `src/novel_dev/web/src/test/smoke.test.js` | 前端测试基线 |
| `src/novel_dev/web/src/views/dashboard/dashboardSummary.js` | 纯函数：章节汇总、数据汇总、推荐动作、风险、最近更新、状态卡数据 |
| `src/novel_dev/web/src/views/dashboard/dashboardSummary.test.js` | summary 纯函数测试 |
| `src/novel_dev/web/src/stores/novel.js` | 首页补充数据加载、卡片级状态与轻量刷新入口 |
| `src/novel_dev/web/src/stores/novel.test.js` | store 首页加载逻辑测试 |
| `src/novel_dev/web/src/components/dashboard/DashboardHero.vue` | 顶部总览带 |
| `src/novel_dev/web/src/components/dashboard/DashboardStatusCards.vue` | 4 张摘要卡 |
| `src/novel_dev/web/src/components/dashboard/DashboardVolumeSummary.vue` | 当前卷章节摘要 |
| `src/novel_dev/web/src/components/dashboard/DashboardNextActions.vue` | 推荐动作区 |
| `src/novel_dev/web/src/components/dashboard/DashboardInsights.vue` | 最近更新、风险提醒、快速跳转、轻量日志 |
| `src/novel_dev/web/src/components/dashboard/DashboardStatusCards.test.js` | 摘要卡渲染与降级测试 |
| `src/novel_dev/web/src/views/Dashboard.vue` | 重组首页、串起组件、日志摘要和自动刷新 |
| `src/novel_dev/web/src/style.css` | 增加 dashboard 局部视觉样式 |

---

### Task 1: 建立前端测试基建

**Files:**
- Modify: `src/novel_dev/web/package.json`
- Modify: `src/novel_dev/web/package-lock.json`
- Create: `src/novel_dev/web/vitest.config.js`
- Create: `src/novel_dev/web/src/test/setup.js`
- Create: `src/novel_dev/web/src/test/smoke.test.js`

- [ ] **Step 1: 修改 `package.json`，加入测试脚本和依赖**

将 `src/novel_dev/web/package.json` 改成：

```json
{
  "name": "novel-dev-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run --config vitest.config.js",
    "test:watch": "vitest --config vitest.config.js"
  },
  "dependencies": {
    "vue": "^3.4.21",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.7",
    "element-plus": "^2.5.6",
    "@element-plus/icons-vue": "^2.3.1",
    "tailwindcss": "^3.4.3",
    "postcss": "^8.4.38",
    "autoprefixer": "^10.4.19",
    "echarts": "^5.5.0",
    "vue-echarts": "^6.6.9",
    "@vueuse/core": "^10.9.0",
    "axios": "^1.6.8"
  },
  "devDependencies": {
    "vite": "^5.2.0",
    "@vitejs/plugin-vue": "^5.0.4",
    "vitest": "^2.1.3",
    "jsdom": "^25.0.1",
    "@vue/test-utils": "^2.4.6"
  }
}
```

- [ ] **Step 2: 安装依赖并更新 lockfile**

Run: `cd src/novel_dev/web && npm install`

Expected: `package-lock.json` 更新，并新增 `vitest`、`jsdom`、`@vue/test-utils`

- [ ] **Step 3: 创建 Vitest 配置**

Create `src/novel_dev/web/vitest.config.js`:

```js
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    globals: true,
    css: true,
  },
})
```

- [ ] **Step 4: 创建测试环境初始化文件**

Create `src/novel_dev/web/src/test/setup.js`:

```js
import { vi } from 'vitest'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, 'ResizeObserver', {
  writable: true,
  value: ResizeObserverMock,
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

class EventSourceMock {
  constructor(url) {
    this.url = url
    this.close = vi.fn()
  }
}

Object.defineProperty(window, 'EventSource', {
  writable: true,
  value: EventSourceMock,
})
```

- [ ] **Step 5: 添加 smoke test**

Create `src/novel_dev/web/src/test/smoke.test.js`:

```js
import { describe, expect, it } from 'vitest'

describe('frontend test harness', () => {
  it('boots vitest in jsdom', () => {
    expect(window).toBeDefined()
    expect(window.ResizeObserver).toBeDefined()
    expect(window.EventSource).toBeDefined()
  })
})
```

- [ ] **Step 6: 运行测试基线**

Run: `cd src/novel_dev/web && npm run test -- src/test/smoke.test.js`

Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/web/package.json src/novel_dev/web/package-lock.json src/novel_dev/web/vitest.config.js src/novel_dev/web/src/test/setup.js src/novel_dev/web/src/test/smoke.test.js
git commit -m "test: add frontend vitest harness"
```

---

### Task 2: 落地 dashboard 汇总纯函数

**Files:**
- Create: `src/novel_dev/web/src/views/dashboard/dashboardSummary.js`
- Create: `src/novel_dev/web/src/views/dashboard/dashboardSummary.test.js`

- [ ] **Step 1: 写 summary 测试，锁定首页派生规则**

Create `src/novel_dev/web/src/views/dashboard/dashboardSummary.test.js`:

```js
import { describe, expect, it } from 'vitest'
import {
  buildChapterSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
} from './dashboardSummary.js'

describe('buildChapterSummary', () => {
  it('只统计当前卷章节并高亮当前章', () => {
    const chapters = [
      { chapter_id: 'c1', chapter_number: 1, title: '序章', status: 'archived', word_count: 3200 },
      { chapter_id: 'c2', chapter_number: 2, title: '破局', status: 'drafted', word_count: 2100 },
      { chapter_id: 'c3', chapter_number: 3, title: '偏移', status: 'pending', word_count: 0 },
    ]
    const volumePlan = { chapters: [{ chapter_id: 'c1' }, { chapter_id: 'c2' }, { chapter_id: 'c3' }] }

    const result = buildChapterSummary({ chapters, volumePlan, currentChapterId: 'c2' })

    expect(result.total).toBe(3)
    expect(result.archived).toBe(1)
    expect(result.inProgress).toBe(1)
    expect(result.pending).toBe(1)
    expect(result.currentChapter.title).toBe('破局')
    expect(result.totalWords).toBe(5300)
  })
})

describe('buildDataSummary', () => {
  it('聚合实体、时间线、伏笔和待处理资料数量', () => {
    const result = buildDataSummary({
      entities: [{ id: 'e1' }, { id: 'e2' }],
      timelines: [{ id: 1 }],
      foreshadowings: [{ id: 'f1' }, { id: 'f2' }, { id: 'f3' }],
      pendingDocs: [{ id: 'p1' }],
    })

    expect(result.entityCount).toBe(2)
    expect(result.timelineCount).toBe(1)
    expect(result.foreshadowingCount).toBe(3)
    expect(result.pendingDocCount).toBe(1)
  })
})

describe('buildRecentUpdates', () => {
  it('优先使用 updated_at / created_at / tick 排序并截断到 4 条', () => {
    const result = buildRecentUpdates({
      entities: [{ id: 'e1', name: '林砚', type: 'character', updated_at: '2026-04-21T10:00:00Z' }],
      timelines: [{ id: 1, narrative: '第一场冲突', tick: 20 }],
      foreshadowings: [{ id: 'f1', content: '铜镜异响', 埋下_time_tick: 18 }],
      pendingDocs: [{ id: 'p1', source_filename: '设定A.md', created_at: '2026-04-21T11:00:00Z' }],
    })

    expect(result).toHaveLength(4)
    expect(result[0].label).toContain('设定A.md')
  })
})

describe('buildRecommendedActions', () => {
  it('为卷规划阶段返回主动作和原因', () => {
    const result = buildRecommendedActions({ phase: 'volume_planning', loadingActions: {} })

    expect(result.primary.key).toBe('volume_plan')
    expect(result.primary.reason).toContain('当前已完成脑暴')
    expect(result.secondary).toHaveLength(2)
  })
})

describe('buildRiskItems', () => {
  it('合并卡片错误和最近 error 日志', () => {
    const result = buildRiskItems({
      panels: {
        entities: { state: 'error', error: '实体加载失败' },
        timelines: { state: 'ready', error: '' },
      },
      logs: [{ level: 'error', agent: 'LibrarianAgent', message: '持久化失败' }],
      currentChapter: null,
    })

    expect(result.some((item) => item.title.includes('实体'))).toBe(true)
    expect(result.some((item) => item.title.includes('LibrarianAgent'))).toBe(true)
  })
})
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `cd src/novel_dev/web && npm run test -- src/views/dashboard/dashboardSummary.test.js`

Expected: FAIL，原因是 `dashboardSummary.js` 尚不存在

- [ ] **Step 3: 实现 summary 纯函数**

Create `src/novel_dev/web/src/views/dashboard/dashboardSummary.js`:

```js
const ACTION_META = {
  brainstorm: { label: '开始脑暴', route: '/documents' },
  volume_plan: { label: '生成分卷', route: '/volume-plan' },
  context: { label: '生成上下文', route: '/chapters' },
  draft: { label: '生成草稿', route: '/chapters' },
  advance: { label: '推进阶段', route: '/logs' },
  librarian: { label: '执行归档', route: '/logs' },
  export: { label: '导出小说', route: '/documents' },
}

const PHASE_ACTIONS = {
  brainstorming: {
    primary: { key: 'brainstorm', reason: '当前处于脑暴阶段，应先完成 synopsis 的确认或导入。' },
    secondary: [
      { key: 'export', reason: '如需同步当前资料，可先导出已有内容。' },
      { key: 'brainstorm', reason: '如需继续迭代，可再次触发脑暴流程。' },
    ],
  },
  volume_planning: {
    primary: { key: 'volume_plan', reason: '当前已完成脑暴，最合理的下一步是生成本卷规划。' },
    secondary: [
      { key: 'export', reason: '在规划前导出已有 synopsis 进行复核。' },
      { key: 'brainstorm', reason: '如果大纲仍不稳定，可回到脑暴完善。' },
    ],
  },
  context_preparation: {
    primary: { key: 'context', reason: '卷规划已完成，当前章应先组装上下文。' },
    secondary: [
      { key: 'volume_plan', reason: '如果本卷章节拆分不理想，可回看卷规划。' },
      { key: 'export', reason: '导出上下文前的状态以便外部检查。' },
    ],
  },
  drafting: {
    primary: { key: 'draft', reason: '上下文已经准备完成，下一步应产出章节草稿。' },
    secondary: [
      { key: 'context', reason: '若上下文信息不足，可先重新准备上下文。' },
      { key: 'export', reason: '导出当前状态用于人工审核。' },
    ],
  },
  reviewing: {
    primary: { key: 'advance', reason: '当前处于审稿流转阶段，推进可以触发后续评审动作。' },
    secondary: [
      { key: 'draft', reason: '如果草稿明显不足，可回看草稿产物。' },
      { key: 'export', reason: '导出当前文本给外部审阅。' },
    ],
  },
  editing: {
    primary: { key: 'advance', reason: '当前已经进入编辑润色，继续推进可以触发后续快审。' },
    secondary: [
      { key: 'export', reason: '导出当前稿件进行人工校读。' },
      { key: 'draft', reason: '如需重写，可回到草稿视角查看问题。' },
    ],
  },
  fast_reviewing: {
    primary: { key: 'advance', reason: '快速审查阶段应继续推进，决定是否归档。' },
    secondary: [
      { key: 'export', reason: '导出审查前版本用于复盘。' },
      { key: 'draft', reason: '必要时回溯章节草稿来源。' },
    ],
  },
  librarian: {
    primary: { key: 'librarian', reason: '当前待归档，执行归档可把章节结果写入知识库。' },
    secondary: [
      { key: 'advance', reason: '若归档完成后需继续流转，可再推进。' },
      { key: 'export', reason: '导出已归档内容用于备份。' },
    ],
  },
  completed: {
    primary: { key: 'export', reason: '当前流程已完成，导出是最自然的收尾动作。' },
    secondary: [
      { key: 'volume_plan', reason: '如需继续下一卷，可重新生成卷规划。' },
      { key: 'export', reason: '导出最终结果供外部使用。' },
    ],
  },
}

function sortScore(value) {
  if (!value) return 0
  const time = Date.parse(value)
  return Number.isNaN(time) ? 0 : time
}

export function buildChapterSummary({ chapters, volumePlan, currentChapterId }) {
  const scopedChapters = (volumePlan?.chapters?.length
    ? volumePlan.chapters.map((item) => chapters.find((chapter) => chapter.chapter_id === item.chapter_id)).filter(Boolean)
    : chapters) || []

  const currentChapter = scopedChapters.find((chapter) => chapter.chapter_id === currentChapterId) || null
  const archived = scopedChapters.filter((chapter) => chapter.status === 'archived').length
  const inProgress = scopedChapters.filter((chapter) => ['drafted', 'edited'].includes(chapter.status)).length
  const pending = scopedChapters.filter((chapter) => chapter.status === 'pending').length
  const totalWords = scopedChapters.reduce((sum, chapter) => sum + (chapter.word_count || 0), 0)

  return {
    chapters: scopedChapters,
    total: scopedChapters.length,
    archived,
    inProgress,
    pending,
    totalWords,
    currentChapter,
  }
}

export function buildDataSummary({ entities, timelines, foreshadowings, pendingDocs }) {
  return {
    entityCount: entities.length,
    timelineCount: timelines.length,
    foreshadowingCount: foreshadowings.length,
    pendingDocCount: pendingDocs.length,
  }
}

export function buildRecentUpdates({ entities, timelines, foreshadowings, pendingDocs }) {
  const items = [
    ...entities.map((entity) => ({
      sort: sortScore(entity.updated_at) || entity.current_version || 0,
      label: entity.name,
      detail: `${entity.type} · v${entity.current_version || 1}`,
      route: '/entities',
    })),
    ...timelines.map((timeline) => ({
      sort: timeline.tick || 0,
      label: timeline.narrative,
      detail: `Tick ${timeline.tick}`,
      route: '/timeline',
    })),
    ...foreshadowings.map((item) => ({
      sort: item.埋下_time_tick || 0,
      label: item.content,
      detail: item.回收状态 === 'recovered' ? '已回收' : '待回收',
      route: '/foreshadowings',
    })),
    ...pendingDocs.map((doc) => ({
      sort: sortScore(doc.created_at),
      label: doc.source_filename || doc.filename || '未命名资料',
      detail: doc.status || 'pending',
      route: '/documents',
    })),
  ]

  return items.sort((a, b) => b.sort - a.sort).slice(0, 4)
}

export function buildRecommendedActions({ phase, loadingActions }) {
  const config = PHASE_ACTIONS[phase] || PHASE_ACTIONS.completed
  const decorate = (item) => ({
    ...item,
    ...ACTION_META[item.key],
    loading: Boolean(loadingActions[item.key]),
  })

  return {
    primary: decorate(config.primary),
    secondary: config.secondary.map(decorate),
  }
}

export function buildRiskItems({ panels, logs, currentChapter }) {
  const panelItems = Object.entries(panels)
    .filter(([, panel]) => panel?.state === 'error')
    .map(([key, panel]) => ({
      title: `${key} 模块异常`,
      detail: panel.error,
      route: key === 'entities' ? '/entities' : key === 'timelines' ? '/timeline' : key === 'foreshadowings' ? '/foreshadowings' : '/documents',
    }))

  const logItems = logs
    .filter((log) => log.level === 'error' || log.level === 'warning')
    .slice(-2)
    .reverse()
    .map((log) => ({
      title: `${log.agent} ${log.level === 'error' ? '失败' : '警告'}`,
      detail: log.message,
      route: '/logs',
    }))

  const chapterItem = currentChapter
    ? []
    : [{
        title: '当前章缺失',
        detail: '当前阶段需要章节上下文，但未找到 currentChapter。',
        route: '/chapters',
      }]

  return [...panelItems, ...chapterItem, ...logItems].slice(0, 4)
}

export function buildStatusCards({ phaseLabel, chapterSummary, dataSummary, logs, connected, archiveStats }) {
  const latestLog = logs.at(-1)

  return [
    {
      key: 'flow',
      title: '流程进度',
      value: phaseLabel || '-',
      detail: latestLog ? `最近动作：${latestLog.agent}` : '暂无运行记录',
      route: '/logs',
    },
    {
      key: 'chapter',
      title: '章节进度',
      value: `${chapterSummary.archived}/${chapterSummary.total || 0}`,
      detail: chapterSummary.currentChapter ? `当前章：${chapterSummary.currentChapter.title}` : '暂无当前章',
      route: '/chapters',
    },
    {
      key: 'data',
      title: '数据状态',
      value: `${dataSummary.entityCount} 实体 / ${dataSummary.foreshadowingCount} 伏笔`,
      detail: `${dataSummary.timelineCount} 条时间线，${dataSummary.pendingDocCount} 份待处理资料`,
      route: '/entities',
    },
    {
      key: 'runtime',
      title: '运行状态',
      value: connected ? '轻实时连接中' : '未连接',
      detail: latestLog ? latestLog.message : `已归档 ${archiveStats.archived_chapter_count || 0} 章`,
      route: '/logs',
    },
  ]
}
```

- [ ] **Step 4: 运行 summary 测试**

Run: `cd src/novel_dev/web && npm run test -- src/views/dashboard/dashboardSummary.test.js`

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/src/views/dashboard/dashboardSummary.js src/novel_dev/web/src/views/dashboard/dashboardSummary.test.js
git commit -m "test: lock dashboard summary rules"
```

---

### Task 3: 扩展 store，支持首页补充加载和卡片级降级

**Files:**
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Create: `src/novel_dev/web/src/stores/novel.test.js`

- [ ] **Step 1: 写 store 测试，锁定首页补充加载行为**

Create `src/novel_dev/web/src/stores/novel.test.js`:

```js
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useNovelStore } from './novel.js'

vi.mock('@/api.js', () => ({
  getNovelState: vi.fn(async () => ({ current_phase: 'volume_planning', current_volume_id: 'v1', current_chapter_id: 'c2', checkpoint_data: {} })),
  getArchiveStats: vi.fn(async () => ({ archived_chapter_count: 3, total_word_count: 12000 })),
  getChapters: vi.fn(async () => ({ items: [{ chapter_id: 'c2', title: '破局', status: 'drafted', word_count: 2200 }] })),
  getSynopsis: vi.fn(async () => null),
  getVolumePlan: vi.fn(async () => ({ chapters: [{ chapter_id: 'c2', title: '破局' }] })),
  getEntities: vi.fn(async () => ({ items: [{ id: 'e1', name: '林砚' }] })),
  getEntityRelationships: vi.fn(async () => ({ items: [] })),
  getTimelines: vi.fn(async () => ({ items: [{ id: 1, tick: 10, narrative: '冲突爆发' }] })),
  getForeshadowings: vi.fn(async () => ({ items: [{ id: 'f1', content: '铜镜异响' }] })),
  getPendingDocs: vi.fn(async () => ({ items: [{ id: 'p1', status: 'pending' }] })),
}))

describe('novel store dashboard helpers', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('loadDashboardSupplemental marks panels ready on success', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'

    await store.loadDashboardSupplemental()

    expect(store.dashboardPanels.entities.state).toBe('ready')
    expect(store.dashboardPanels.timelines.state).toBe('ready')
    expect(store.dashboardPanels.foreshadowings.state).toBe('ready')
    expect(store.dashboardPanels.pendingDocs.state).toBe('ready')
  })

  it('refreshDashboard refreshes state and chapter merge', async () => {
    const store = useNovelStore()

    await store.loadNovel('novel-1')
    await store.refreshDashboard()

    expect(store.currentChapter.title).toBe('破局')
    expect(store.dashboardLastUpdated).toBeTruthy()
  })
})
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd src/novel_dev/web && npm run test -- src/stores/novel.test.js`

Expected: FAIL，因为 `dashboardPanels`、`loadDashboardSupplemental`、`refreshDashboard` 尚不存在

- [ ] **Step 3: 修改 store，增加首页加载状态和刷新入口**

在 `src/novel_dev/web/src/stores/novel.js` 中做以下改动。

1. 在 `state` 中加入：

```js
    dashboardPanels: {
      entities: { state: 'idle', error: '' },
      timelines: { state: 'idle', error: '' },
      foreshadowings: { state: 'idle', error: '' },
      pendingDocs: { state: 'idle', error: '' },
    },
    dashboardLastUpdated: '',
```

2. 在 `actions` 中加入私有同步方法：

```js
    syncCurrentChapter() {
      const plan = this.volumePlan?.chapters?.find((chapter) => chapter.chapter_id === this.novelState.current_chapter_id)
      const chapter = this.chapters.find((item) => item.chapter_id === this.novelState.current_chapter_id)
      this.currentChapter = chapter ? { ...chapter, ...plan } : plan || null
    },

    setDashboardPanelState(panel, state, error = '') {
      this.dashboardPanels[panel] = { state, error }
    },
```

3. 在 `loadNovel()` 和 `refreshState()` 末尾把原来的章节合并逻辑替换成：

```js
      this.syncCurrentChapter()
```

4. 在 `actions` 中加入首页补充加载：

```js
    async loadDashboardSupplemental() {
      if (!this.novelId) return

      const loaders = {
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

      await Promise.all(Object.entries(loaders).map(async ([panel, loader]) => {
        this.setDashboardPanelState(panel, 'loading')
        try {
          await loader()
          this.setDashboardPanelState(panel, 'ready')
        } catch (error) {
          this.setDashboardPanelState(panel, 'error', error?.message || '加载失败')
        }
      }))

      this.dashboardLastUpdated = new Date().toISOString()
    },

    async refreshDashboard() {
      if (!this.novelId) return
      await this.refreshState()
      await this.loadDashboardSupplemental()
      this.syncCurrentChapter()
    },
```

- [ ] **Step 4: 运行 store 测试**

Run: `cd src/novel_dev/web && npm run test -- src/stores/novel.test.js`

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/stores/novel.test.js
git commit -m "feat: add dashboard supplemental loading state"
```

---

### Task 4: 创建 dashboard 展示组件和局部样式

**Files:**
- Create: `src/novel_dev/web/src/components/dashboard/DashboardHero.vue`
- Create: `src/novel_dev/web/src/components/dashboard/DashboardStatusCards.vue`
- Create: `src/novel_dev/web/src/components/dashboard/DashboardVolumeSummary.vue`
- Create: `src/novel_dev/web/src/components/dashboard/DashboardNextActions.vue`
- Create: `src/novel_dev/web/src/components/dashboard/DashboardInsights.vue`
- Create: `src/novel_dev/web/src/components/dashboard/DashboardStatusCards.test.js`
- Modify: `src/novel_dev/web/src/style.css`

- [ ] **Step 1: 写摘要卡组件测试**

Create `src/novel_dev/web/src/components/dashboard/DashboardStatusCards.test.js`:

```js
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DashboardStatusCards from './DashboardStatusCards.vue'

describe('DashboardStatusCards', () => {
  it('renders card values and panel error state', () => {
    const wrapper = mount(DashboardStatusCards, {
      props: {
        cards: [
          { key: 'flow', title: '流程进度', value: '卷规划', detail: '最近动作：VolumePlannerAgent', route: '/logs' },
          { key: 'data', title: '数据状态', value: '12 实体 / 4 伏笔', detail: '1 条告警', route: '/entities', panelState: 'error' },
        ],
      },
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })

    expect(wrapper.text()).toContain('流程进度')
    expect(wrapper.text()).toContain('卷规划')
    expect(wrapper.text()).toContain('数据状态')
    expect(wrapper.findAll('.dashboard-status-card.is-error')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd src/novel_dev/web && npm run test -- src/components/dashboard/DashboardStatusCards.test.js`

Expected: FAIL，因为组件文件尚不存在

- [ ] **Step 3: 创建顶部总览组件**

Create `src/novel_dev/web/src/components/dashboard/DashboardHero.vue`:

```vue
<template>
  <section class="dashboard-hero">
    <div>
      <p class="dashboard-kicker">Novel Overview</p>
      <h2 class="dashboard-title">{{ title }}</h2>
      <p class="dashboard-subtitle">当前阶段：{{ phaseLabel }} · 当前定位：{{ volumeChapter }}</p>
    </div>
    <div class="dashboard-hero-metrics">
      <div class="dashboard-metric">
        <span class="dashboard-metric-label">累计字数</span>
        <strong>{{ totalWords.toLocaleString('zh-CN') }}</strong>
      </div>
      <div class="dashboard-metric">
        <span class="dashboard-metric-label">已归档章节</span>
        <strong>{{ archivedCount }}</strong>
      </div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, default: '未选择小说' },
  phaseLabel: { type: String, default: '-' },
  volumeChapter: { type: String, default: '- / -' },
  totalWords: { type: Number, default: 0 },
  archivedCount: { type: Number, default: 0 },
})
</script>
```

- [ ] **Step 4: 创建摘要卡、当前卷、动作区、洞察区组件**

Create `src/novel_dev/web/src/components/dashboard/DashboardStatusCards.vue`:

```vue
<template>
  <section class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
    <RouterLink
      v-for="card in cards"
      :key="card.key"
      :to="card.route"
      class="dashboard-status-card"
      :class="{ 'is-error': card.panelState === 'error' }"
    >
      <p class="dashboard-card-label">{{ card.title }}</p>
      <h3 class="dashboard-card-value">{{ card.value }}</h3>
      <p class="dashboard-card-detail">{{ card.detail }}</p>
    </RouterLink>
  </section>
</template>

<script setup>
defineProps({
  cards: { type: Array, default: () => [] },
})
</script>
```

Create `src/novel_dev/web/src/components/dashboard/DashboardVolumeSummary.vue`:

```vue
<template>
  <section class="dashboard-panel space-y-4">
    <div class="flex items-start justify-between gap-4">
      <div>
        <p class="dashboard-kicker">Current Volume</p>
        <h3 class="text-xl font-semibold text-slate-900">{{ currentChapter?.title || '暂无当前章' }}</h3>
        <p class="text-sm text-slate-500">
          已完成 {{ summary.archived }} / {{ summary.total || 0 }} · 进行中 {{ summary.inProgress }} · 待开始 {{ summary.pending }}
        </p>
      </div>
      <el-tag :type="currentChapter ? 'primary' : 'info'">{{ currentChapter?.status || 'pending' }}</el-tag>
    </div>

    <div class="grid grid-cols-3 gap-3 text-sm">
      <div class="dashboard-mini-stat"><span>当前卷字数</span><strong>{{ summary.totalWords.toLocaleString('zh-CN') }}</strong></div>
      <div class="dashboard-mini-stat"><span>当前章字数</span><strong>{{ currentChapter?.word_count || 0 }}</strong></div>
      <div class="dashboard-mini-stat"><span>目标进度</span><strong>{{ currentChapter?.target_word_count || 3000 }}</strong></div>
    </div>

    <ChapterProgressGantt v-if="summary.chapters.length" :chapters="summary.chapters" />
    <ScoreRadar v-if="currentChapter?.score_breakdown" :scores="currentChapter.score_breakdown" />
  </section>
</template>

<script setup>
import ChapterProgressGantt from '@/components/ChapterProgressGantt.vue'
import ScoreRadar from '@/components/ScoreRadar.vue'

defineProps({
  summary: { type: Object, required: true },
  currentChapter: { type: Object, default: null },
})
</script>
```

Create `src/novel_dev/web/src/components/dashboard/DashboardNextActions.vue`:

```vue
<template>
  <section class="dashboard-panel space-y-4">
    <div>
      <p class="dashboard-kicker">Next Move</p>
      <h3 class="text-xl font-semibold text-slate-900">推荐下一步</h3>
    </div>

    <button class="dashboard-primary-action" type="button" @click="$emit('action', actions.primary.key)">
      <span>{{ actions.primary.label }}</span>
      <small>{{ actions.primary.reason }}</small>
    </button>

    <div class="space-y-2">
      <button
        v-for="item in actions.secondary"
        :key="item.key + item.reason"
        class="dashboard-secondary-action"
        type="button"
        @click="$emit('action', item.key)"
      >
        <span>{{ item.label }}</span>
        <small>{{ item.reason }}</small>
      </button>
    </div>
  </section>
</template>

<script setup>
defineEmits(['action'])
defineProps({
  actions: {
    type: Object,
    default: () => ({ primary: { key: '', label: '', reason: '' }, secondary: [] }),
  },
})
</script>
```

Create `src/novel_dev/web/src/components/dashboard/DashboardInsights.vue`:

```vue
<template>
  <section class="grid grid-cols-1 xl:grid-cols-3 gap-4">
    <div class="dashboard-panel">
      <p class="dashboard-kicker">Recent Updates</p>
      <ul class="space-y-3">
        <li v-for="item in recentUpdates" :key="item.label + item.detail" class="dashboard-list-item">
          <RouterLink :to="item.route" class="font-medium text-slate-800">{{ item.label }}</RouterLink>
          <p class="text-sm text-slate-500">{{ item.detail }}</p>
        </li>
      </ul>
      <p v-if="!recentUpdates.length" class="text-sm text-slate-400">暂无最近更新</p>
    </div>

    <div class="dashboard-panel">
      <p class="dashboard-kicker">Risks</p>
      <ul class="space-y-3">
        <li v-for="item in risks" :key="item.title + item.detail" class="dashboard-list-item">
          <RouterLink :to="item.route" class="font-medium text-amber-700">{{ item.title }}</RouterLink>
          <p class="text-sm text-slate-500">{{ item.detail }}</p>
        </li>
      </ul>
      <p v-if="!risks.length" class="text-sm text-slate-400">当前没有需要优先处理的异常</p>
    </div>

    <div class="dashboard-panel">
      <p class="dashboard-kicker">Quick Links</p>
      <div class="grid grid-cols-2 gap-2 mb-4">
        <RouterLink v-for="item in links" :key="item.to" :to="item.to" class="dashboard-link-tile">{{ item.label }}</RouterLink>
      </div>
      <div class="rounded-2xl bg-slate-950 text-slate-100 p-4">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs uppercase tracking-[0.2em] text-slate-400">Runtime</span>
          <span class="text-xs text-slate-400">{{ connected ? 'connected' : 'offline' }}</span>
        </div>
        <ul class="space-y-2 text-sm">
          <li v-for="item in recentLogs" :key="item.agent + item.message">{{ item.agent }} · {{ item.message }}</li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  recentUpdates: { type: Array, default: () => [] },
  risks: { type: Array, default: () => [] },
  recentLogs: { type: Array, default: () => [] },
  connected: { type: Boolean, default: false },
  links: { type: Array, default: () => [] },
})
</script>
```

- [ ] **Step 5: 增加 dashboard 局部样式**

在 `src/novel_dev/web/src/style.css` 末尾追加：

```css
@layer components {
  .dashboard-hero {
    @apply rounded-[28px] border border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.24),_rgba(255,255,255,0.92)_40%,_rgba(255,255,255,1)_100%)] px-6 py-6 shadow-sm;
    @apply flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between;
  }

  .dashboard-kicker {
    @apply text-[11px] uppercase tracking-[0.28em] text-sky-700;
  }

  .dashboard-title {
    @apply mt-2 text-3xl font-semibold tracking-tight text-slate-900;
  }

  .dashboard-subtitle {
    @apply mt-2 text-sm text-slate-500;
  }

  .dashboard-hero-metrics {
    @apply grid grid-cols-2 gap-3 min-w-[280px];
  }

  .dashboard-metric,
  .dashboard-mini-stat,
  .dashboard-panel,
  .dashboard-status-card {
    @apply rounded-2xl border border-slate-200 bg-white p-4 shadow-sm;
  }

  .dashboard-status-card {
    @apply transition-transform duration-150 hover:-translate-y-0.5 hover:shadow-md;
  }

  .dashboard-status-card.is-error {
    @apply border-amber-300 bg-amber-50;
  }

  .dashboard-card-label {
    @apply text-sm text-slate-500;
  }

  .dashboard-card-value {
    @apply mt-2 text-2xl font-semibold text-slate-900;
  }

  .dashboard-card-detail {
    @apply mt-2 text-sm text-slate-500;
  }

  .dashboard-primary-action,
  .dashboard-secondary-action,
  .dashboard-link-tile {
    @apply w-full rounded-2xl border border-slate-200 p-4 text-left transition-colors;
  }

  .dashboard-primary-action {
    @apply bg-slate-950 text-white hover:bg-slate-900;
  }

  .dashboard-primary-action small,
  .dashboard-secondary-action small {
    @apply mt-2 block text-sm opacity-80;
  }

  .dashboard-secondary-action {
    @apply bg-slate-50 text-slate-900 hover:bg-slate-100;
  }

  .dashboard-link-tile {
    @apply bg-slate-50 font-medium text-slate-800 hover:bg-slate-100;
  }

  .dashboard-list-item {
    @apply rounded-2xl border border-slate-100 bg-slate-50 p-3;
  }
}
```

- [ ] **Step 6: 运行组件测试**

Run: `cd src/novel_dev/web && npm run test -- src/components/dashboard/DashboardStatusCards.test.js`

Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/web/src/components/dashboard/DashboardHero.vue src/novel_dev/web/src/components/dashboard/DashboardStatusCards.vue src/novel_dev/web/src/components/dashboard/DashboardVolumeSummary.vue src/novel_dev/web/src/components/dashboard/DashboardNextActions.vue src/novel_dev/web/src/components/dashboard/DashboardInsights.vue src/novel_dev/web/src/components/dashboard/DashboardStatusCards.test.js src/novel_dev/web/src/style.css
git commit -m "feat: add dashboard overview components"
```

---

### Task 5: 重构 `Dashboard.vue`，串起轻实时首页

**Files:**
- Modify: `src/novel_dev/web/src/views/Dashboard.vue`

- [ ] **Step 1: 用 summary + store + realtime log 重写页面逻辑**

将 `src/novel_dev/web/src/views/Dashboard.vue` 改成：

```vue
<template>
  <div v-if="!store.novelId" class="text-center py-20 text-gray-400">请从侧边栏选择或输入一个小说ID</div>
  <div v-else class="space-y-6">
    <DashboardHero
      :title="store.novelTitle"
      :phase-label="store.currentPhaseLabel"
      :volume-chapter="store.currentVolumeChapter"
      :total-words="store.archiveStats.total_word_count || 0"
      :archived-count="store.archiveStats.archived_chapter_count || 0"
    />

    <DashboardStatusCards :cards="statusCards" />

    <section class="grid grid-cols-1 xl:grid-cols-[1.6fr_1fr] gap-4">
      <DashboardVolumeSummary :summary="chapterSummary" :current-chapter="store.currentChapter" />
      <DashboardNextActions :actions="recommendedActions" @action="store.executeAction" />
    </section>

    <DashboardInsights
      :recent-updates="recentUpdates"
      :risks="riskItems"
      :recent-logs="recentLogs"
      :connected="connected"
      :links="quickLinks"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { useRealtimeLog } from '@/composables/useRealtimeLog.js'
import DashboardHero from '@/components/dashboard/DashboardHero.vue'
import DashboardStatusCards from '@/components/dashboard/DashboardStatusCards.vue'
import DashboardVolumeSummary from '@/components/dashboard/DashboardVolumeSummary.vue'
import DashboardNextActions from '@/components/dashboard/DashboardNextActions.vue'
import DashboardInsights from '@/components/dashboard/DashboardInsights.vue'
import {
  buildChapterSummary,
  buildDataSummary,
  buildRecentUpdates,
  buildRecommendedActions,
  buildRiskItems,
  buildStatusCards,
} from '@/views/dashboard/dashboardSummary.js'

const store = useNovelStore()
const novelIdRef = computed(() => store.novelId)
const { logs, connected } = useRealtimeLog(novelIdRef)

const chapterSummary = computed(() => buildChapterSummary({
  chapters: store.chapters,
  volumePlan: store.volumePlan,
  currentChapterId: store.novelState.current_chapter_id,
}))

const dataSummary = computed(() => buildDataSummary({
  entities: store.entities,
  timelines: store.timelines,
  foreshadowings: store.foreshadowings,
  pendingDocs: store.pendingDocs,
}))

const recentUpdates = computed(() => buildRecentUpdates({
  entities: store.entities,
  timelines: store.timelines,
  foreshadowings: store.foreshadowings,
  pendingDocs: store.pendingDocs,
}))

const recommendedActions = computed(() => buildRecommendedActions({
  phase: store.novelState.current_phase,
  loadingActions: store.loadingActions,
}))

const statusCards = computed(() => buildStatusCards({
  phaseLabel: store.currentPhaseLabel,
  chapterSummary: chapterSummary.value,
  dataSummary: dataSummary.value,
  logs: logs.value,
  connected: connected.value,
  archiveStats: store.archiveStats,
}).map((card) => ({
  ...card,
  panelState: card.key === 'data' && Object.values(store.dashboardPanels).some((panel) => panel.state === 'error') ? 'error' : 'ready',
})))

const riskItems = computed(() => buildRiskItems({
  panels: store.dashboardPanels,
  logs: logs.value,
  currentChapter: store.currentChapter,
}))

const recentLogs = computed(() => logs.value.slice(-3).reverse())

const quickLinks = [
  { label: '章节列表', to: '/chapters' },
  { label: '实体百科', to: '/entities' },
  { label: '时间线', to: '/timeline' },
  { label: '伏笔', to: '/foreshadowings' },
  { label: '资料', to: '/documents' },
  { label: '日志', to: '/logs' },
]

async function loadDashboard() {
  if (!store.novelId) return
  await store.refreshDashboard()
}

let timer = null

onMounted(async () => {
  await loadDashboard()
  timer = window.setInterval(() => {
    store.refreshDashboard().catch(() => {})
  }, 20000)
})

watch(() => store.novelId, async () => {
  await loadDashboard()
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>
```

- [ ] **Step 2: 运行 summary、store、组件测试**

Run:

```bash
cd src/novel_dev/web
npm run test -- src/test/smoke.test.js src/views/dashboard/dashboardSummary.test.js src/stores/novel.test.js src/components/dashboard/DashboardStatusCards.test.js
```

Expected: `9 passed`

- [ ] **Step 3: 运行构建验证**

Run: `cd src/novel_dev/web && npm run build`

Expected: `vite build` 成功，输出 `dist/`

- [ ] **Step 4: 手动验证首页**

Run: `cd src/novel_dev/web && npm run dev`

手动检查：

1. 进入 `/dashboard` 能看到顶部总览、4 张状态卡、当前卷摘要、推荐动作、洞察区
2. 切换小说后，当前章和数据状态同步更新
3. 某个补充请求失败时，仍保留其他模块内容
4. 日志页仍保留完整实时日志，首页只显示最近 3 条摘要

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/src/views/Dashboard.vue
git commit -m "feat: redesign dashboard status overview"
```

---

## Self-Review Checklist

- [ ] Spec coverage: 4 层信息架构、4 张状态卡、当前卷摘要、推荐动作、最近更新、风险提醒、快速跳转、轻实时刷新、卡片级降级都已映射到任务。
- [ ] Placeholder scan: 全文无占位词、延期词和跨任务偷懒引用。
- [ ] Type consistency: `dashboardPanels`、`refreshDashboard`、`buildRecommendedActions`、`buildRiskItems` 在所有任务中名称一致。

---

Plan complete and saved to `docs/superpowers/plans/2026-04-21-dashboard-status-redesign.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
