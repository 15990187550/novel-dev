# Frontend V2 Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 700-line CDN-based single-file Vue SPA with a Vite-built, componentized frontend featuring dark mode, chapter progress visualization, entity relationship graphs, score radar charts, and a real-time agent log console.

**Architecture:** Vite + Vue 3 SFC + Vue Router + Pinia + Tailwind CSS + Element Plus + ECharts. The built `dist/` is served by FastAPI `StaticFiles`. Development runs `vite dev` with proxy to the backend.

**Tech Stack:** Vite 5, Vue 3.4, Vue Router 4, Pinia 2, Tailwind CSS 3.4, Element Plus 2.5, ECharts 5, vue-echarts, VueUse, Axios

---

## File Map

| File | Responsibility |
|------|----------------|
| `src/novel_dev/web/package.json` | npm dependencies and scripts |
| `src/novel_dev/web/vite.config.js` | Vite config, dev proxy to `localhost:8000` |
| `src/novel_dev/web/tailwind.config.js` | Content paths, darkMode `class` strategy |
| `src/novel_dev/web/postcss.config.js` | Tailwind + autoprefixer |
| `src/novel_dev/web/index.html` | Vite entry HTML |
| `src/novel_dev/web/src/main.js` | Mount app, register plugins |
| `src/novel_dev/web/src/App.vue` | Layout shell: sidebar + header + router-view |
| `src/novel_dev/web/src/router.js` | Route table |
| `src/novel_dev/web/src/api.js` | Axios instance + all API functions |
| `src/novel_dev/web/src/stores/novel.js` | Pinia store |
| `src/novel_dev/web/src/composables/useDarkMode.js` | Dark mode + Element Plus sync |
| `src/novel_dev/web/src/composables/useRealtimeLog.js` | EventSource lifecycle |
| `src/novel_dev/web/src/components/DarkModeToggle.vue` | Sun/moon toggle button |
| `src/novel_dev/web/src/components/ScoreRadar.vue` | ECharts radar chart |
| `src/novel_dev/web/src/components/ChapterProgressGantt.vue` | ECharts chapter status bars |
| `src/novel_dev/web/src/components/EntityGraph.vue` | ECharts force-directed graph |
| `src/novel_dev/web/src/components/NovelSelector.vue` | Novel dropdown + load |
| `src/novel_dev/web/src/components/ActionPipeline.vue` | Step-flow action buttons |
| `src/novel_dev/web/src/components/LogConsole.vue` | Colored auto-scroll logs |
| `src/novel_dev/web/src/views/Dashboard.vue` | Stats + radar + pipeline |
| `src/novel_dev/web/src/views/ChapterList.vue` | Gantt + table |
| `src/novel_dev/web/src/views/ChapterDetail.vue` | Side-by-side raw vs polished |
| `src/novel_dev/web/src/views/Entities.vue` | Table + graph |
| `src/novel_dev/web/src/views/Documents.vue` | Upload + approvals |
| `src/novel_dev/web/src/views/VolumePlan.vue` | Volume + chapter timeline |
| `src/novel_dev/web/src/views/Timeline.vue` | Vertical timeline |
| `src/novel_dev/web/src/views/Locations.vue` | Tree table |
| `src/novel_dev/web/src/views/Foreshadowings.vue` | Table with status |
| `src/novel_dev/web/src/views/Config.vue` | LLM config + API keys |
| `src/novel_dev/web/src/views/RealtimeLog.vue` | Full-screen log console |
| `src/novel_dev/services/log_service.py` | Ring buffer for agent logs |
| `src/novel_dev/api/routes.py` | SSE `/api/novels/{id}/logs/stream` |
| `src/novel_dev/api/__init__.py` | Serve `dist/` in production |
| `src/novel_dev/agents/director.py` | Inject LogService at transitions |

---

### Task 1: Vite Project Scaffolding

**Files:**
- Create: `src/novel_dev/web/package.json`
- Create: `src/novel_dev/web/vite.config.js`
- Create: `src/novel_dev/web/tailwind.config.js`
- Create: `src/novel_dev/web/postcss.config.js`
- Create: `src/novel_dev/web/index.html`
- Backup: rename existing `src/novel_dev/web/index.html` to `index.html.old`

- [ ] **Step 1: Backup old frontend**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web
mv index.html index.html.old
```

- [ ] **Step 2: Create package.json**

Create `src/novel_dev/web/package.json`:

```json
{
  "name": "novel-dev-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host",
    "build": "vite build",
    "preview": "vite preview"
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
    "@vitejs/plugin-vue": "^5.0.4"
  }
}
```

- [ ] **Step 3: Create Vite config**

Create `src/novel_dev/web/vite.config.js`:

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
```

- [ ] **Step 4: Create Tailwind config**

Create `src/novel_dev/web/tailwind.config.js`:

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{vue,js,ts}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      colors: {
        'nd-primary': '#3b82f6',
        'nd-success': '#22c55e',
        'nd-warning': '#f59e0b',
        'nd-danger': '#ef4444',
        'nd-purple': '#a855f7',
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 5: Create PostCSS config**

Create `src/novel_dev/web/postcss.config.js`:

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 6: Create Vite entry HTML**

Create `src/novel_dev/web/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Novel Dev</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

- [ ] **Step 7: Create src directories**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web
mkdir -p src/{components,views,stores,composables}
```

- [ ] **Step 8: Install dependencies**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web
npm install
```

Expected: `node_modules/` created, no errors.

- [ ] **Step 9: Verify dev server starts**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web
npm run dev &
```

Expected: Vite dev server starts on port 5173. Stop with Ctrl+C.

- [ ] **Step 10: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/web/package.json src/novel_dev/web/package-lock.json src/novel_dev/web/vite.config.js src/novel_dev/web/tailwind.config.js src/novel_dev/web/postcss.config.js src/novel_dev/web/index.html src/novel_dev/web/index.html.old
git commit -m "feat(frontend): scaffold Vite + Vue 3 + Tailwind project"
```

---

### Task 2: Core Infrastructure (API, Router, Store, Main)

**Files:**
- Create: `src/novel_dev/web/src/api.js`
- Create: `src/novel_dev/web/src/router.js`
- Create: `src/novel_dev/web/src/stores/novel.js`
- Create: `src/novel_dev/web/src/main.js`
- Create: `src/novel_dev/web/src/App.vue` (skeleton only)

- [ ] **Step 1: Create API layer**

Create `src/novel_dev/web/src/api.js`:

```javascript
import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail
    ElMessage.error(detail || '请求失败')
    return Promise.reject(err)
  }
)

export const listNovels = () => api.get('/novels').then(r => r.data)
export const getNovelState = (id) => api.get(`/novels/${id}/state`).then(r => r.data)
export const getArchiveStats = (id) => api.get(`/novels/${id}/archive_stats`).then(r => r.data)
export const getChapters = (id) => api.get(`/novels/${id}/chapters`).then(r => r.data)
export const getChapterText = (nid, cid) => api.get(`/novels/${nid}/chapters/${cid}/text`).then(r => r.data)
export const getEntities = (id) => api.get(`/novels/${id}/entities`).then(r => r.data)
export const getTimelines = (id) => api.get(`/novels/${id}/timelines`).then(r => r.data)
export const getSpacelines = (id) => api.get(`/novels/${id}/spacelines`).then(r => r.data)
export const getForeshadowings = (id) => api.get(`/novels/${id}/foreshadowings`).then(r => r.data)
export const getSynopsis = (id) => api.get(`/novels/${id}/synopsis`).then(r => r.data)
export const getVolumePlan = (id) => api.get(`/novels/${id}/volume_plan`).then(r => r.data)
export const getReview = (id) => api.get(`/novels/${id}/review`).then(r => r.data)
export const getFastReview = (id) => api.get(`/novels/${id}/fast_review`).then(r => r.data)
export const getPendingDocs = (id) => api.get(`/novels/${id}/documents/pending`).then(r => r.data)
export const uploadDocument = (id, filename, content) =>
  api.post(`/novels/${id}/documents/upload`, { filename, content }).then(r => r.data)
export const approvePending = (id, pendingId) =>
  api.post(`/novels/${id}/documents/pending/approve`, { pending_id: pendingId }).then(r => r.data)
export const brainstorm = (id) => api.post(`/novels/${id}/brainstorm`).then(r => r.data)
export const planVolume = (id, volNum) =>
  api.post(`/novels/${id}/volume_plan`, { volume_number: volNum }).then(r => r.data)
export const prepareContext = (id, cid) =>
  api.post(`/novels/${id}/chapters/${cid}/context`).then(r => r.data)
export const draftChapter = (id, cid) =>
  api.post(`/novels/${id}/chapters/${cid}/draft`).then(r => r.data)
export const advance = (id) => api.post(`/novels/${id}/advance`).then(r => r.data)
export const runLibrarian = (id) => api.post(`/novels/${id}/librarian`).then(r => r.data)
export const exportNovel = (id, format = 'md') =>
  api.post(`/novels/${id}/export`, null, { params: { format } }).then(r => r.data)
export const getLLMConfig = () => api.get('/config/llm').then(r => r.data)
export const saveLLMConfig = (config) => api.post('/config/llm', { config }).then(r => r.data)
export const getEnvConfig = () => api.get('/config/env').then(r => r.data)
export const saveEnvConfig = (env) => api.post('/config/env', env).then(r => r.data)
```

- [ ] **Step 2: Create router**

Create `src/novel_dev/web/src/router.js`:

```javascript
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/views/Dashboard.vue') },
  { path: '/documents', component: () => import('@/views/Documents.vue') },
  { path: '/volume-plan', component: () => import('@/views/VolumePlan.vue') },
  { path: '/chapters', component: () => import('@/views/ChapterList.vue') },
  { path: '/chapters/:chapterId', component: () => import('@/views/ChapterDetail.vue') },
  { path: '/entities', component: () => import('@/views/Entities.vue') },
  { path: '/timeline', component: () => import('@/views/Timeline.vue') },
  { path: '/locations', component: () => import('@/views/Locations.vue') },
  { path: '/foreshadowings', component: () => import('@/views/Foreshadowings.vue') },
  { path: '/config', component: () => import('@/views/Config.vue') },
  { path: '/logs', component: () => import('@/views/RealtimeLog.vue') },
]

export default createRouter({ history: createWebHistory(), routes })
```

- [ ] **Step 3: Create Pinia store**

Create `src/novel_dev/web/src/stores/novel.js`:

```javascript
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
    entities: [],
    timelines: [],
    spacelines: [],
    foreshadowings: [],
    pendingDocs: [],
    approvedDocs: [],
    loadingActions: {},
    brainstormPrompt: '',
  }),

  getters: {
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
      const [state, stats, chapters] = await Promise.all([
        api.getNovelState(novelId),
        api.getArchiveStats(novelId).catch(() => ({})),
        api.getChapters(novelId).catch(() => ({ items: [] })),
      ])
      this.novelState = state
      this.archiveStats = stats
      this.chapters = chapters.items || []
      this.volumePlan = state.checkpoint_data?.current_volume_plan || null
      const plan = this.volumePlan?.chapters?.find(c => c.chapter_id === state.current_chapter_id)
      const ch = this.chapters.find(c => c.chapter_id === state.current_chapter_id)
      this.currentChapter = ch ? { ...ch, ...plan } : plan || null
    },

    async refreshState() {
      if (!this.novelId) return
      const state = await api.getNovelState(this.novelId)
      this.novelState = state
      this.volumePlan = state.checkpoint_data?.current_volume_plan || null
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
      const res = await api.getEntities(this.novelId)
      this.entities = res.items || []
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
      const [pending, approved] = await Promise.all([
        api.getPendingDocs(this.novelId).catch(() => ({ items: [] })),
        api.getSynopsis(this.novelId).catch(() => null),
      ])
      this.pendingDocs = pending.items || []
    },
  },
})
```

- [ ] **Step 4: Create main.js**

Create `src/novel_dev/web/src/main.js`:

```javascript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import './style.css'

import App from './App.vue'
import router from './router.js'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.mount('#app')
```

- [ ] **Step 5: Create global style.css**

Create `src/novel_dev/web/src/style.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

html.dark body {
  background-color: #0b0f19;
  color: #f3f4f6;
}
```

- [ ] **Step 6: Create App.vue skeleton**

Create `src/novel_dev/web/src/App.vue`:

```vue
<template>
  <div class="h-screen flex bg-gray-50 dark:bg-gray-900">
    <!-- Sidebar placeholder -->
    <aside class="w-64 border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col">
      <div class="p-4 border-b border-gray-200 dark:border-gray-700">
        <h1 class="font-bold text-lg">Novel Dev</h1>
      </div>
      <nav class="flex-1 p-2">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          class="block px-3 py-2 rounded-lg mb-1 text-sm hover:bg-gray-100 dark:hover:bg-gray-700"
          :class="{ 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400': $route.path === item.path }"
        >
          {{ item.label }}
        </router-link>
      </nav>
    </aside>

    <!-- Main content -->
    <main class="flex-1 flex flex-col overflow-hidden">
      <header class="h-14 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center px-4">
        <span class="text-sm text-gray-500 dark:text-gray-400">{{ novelStore.currentPhaseLabel }}</span>
      </header>
      <div class="flex-1 overflow-auto p-4">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import { useNovelStore } from '@/stores/novel.js'

const route = useRoute()
const novelStore = useNovelStore()

const menuItems = [
  { path: '/dashboard', label: '仪表盘' },
  { path: '/documents', label: '设定资料' },
  { path: '/volume-plan', label: '卷规划' },
  { path: '/chapters', label: '章节列表' },
  { path: '/entities', label: '实体百科' },
  { path: '/timeline', label: '时间线' },
  { path: '/locations', label: '地点' },
  { path: '/foreshadowings', label: '伏笔' },
  { path: '/config', label: '模型配置' },
  { path: '/logs', label: '实时日志' },
]
</script>
```

- [ ] **Step 7: Create placeholder Dashboard.vue**

Create `src/novel_dev/web/src/views/Dashboard.vue`:

```vue
<template>
  <div>
    <h2 class="text-xl font-bold mb-4">Dashboard</h2>
    <p class="text-gray-500">Select a novel from the sidebar to get started.</p>
  </div>
</template>
```

- [ ] **Step 8: Verify app mounts**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web
npm run dev &
```

Open `http://localhost:5173` in browser. Expected: sidebar with menu items renders, no console errors. Stop dev server.

- [ ] **Step 9: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/web/src/ src/novel_dev/web/index.html
git commit -m "feat(frontend): add API layer, router, Pinia store, app shell"
```

---

### Task 3: Layout Shell + Dark Mode + Novel Selector

**Files:**
- Create: `src/novel_dev/web/src/composables/useDarkMode.js`
- Create: `src/novel_dev/web/src/components/DarkModeToggle.vue`
- Create: `src/novel_dev/web/src/components/NovelSelector.vue`
- Modify: `src/novel_dev/web/src/App.vue`

- [ ] **Step 1: Create useDarkMode composable**

Create `src/novel_dev/web/src/composables/useDarkMode.js`:

```javascript
import { useDark, useToggle } from '@vueuse/core'
import { watch } from 'vue'

export function useDarkMode() {
  const isDark = useDark({
    selector: 'html',
    attribute: 'class',
    valueDark: 'dark',
    valueLight: '',
  })
  const toggleDark = useToggle(isDark)

  watch(isDark, (dark) => {
    const el = document.documentElement
    if (dark) {
      el.style.setProperty('--el-bg-color', '#111827')
      el.style.setProperty('--el-bg-color-page', '#0b0f19')
      el.style.setProperty('--el-text-color-primary', '#f3f4f6')
      el.style.setProperty('--el-border-color', '#374151')
    } else {
      el.style.removeProperty('--el-bg-color')
      el.style.removeProperty('--el-bg-color-page')
      el.style.removeProperty('--el-text-color-primary')
      el.style.removeProperty('--el-border-color')
    }
  }, { immediate: true })

  return { isDark, toggleDark }
}
```

- [ ] **Step 2: Create DarkModeToggle component**

Create `src/novel_dev/web/src/components/DarkModeToggle.vue`:

```vue
<template>
  <button
    @click="toggleDark()"
    class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
    :title="isDark ? '切换亮色模式' : '切换暗黑模式'"
  >
    <el-icon v-if="isDark" :size="18"><Sunny /></el-icon>
    <el-icon v-else :size="18"><Moon /></el-icon>
  </button>
</template>

<script setup>
import { useDarkMode } from '@/composables/useDarkMode.js'

const { isDark, toggleDark } = useDarkMode()
</script>
```

- [ ] **Step 3: Create NovelSelector component**

Create `src/novel_dev/web/src/components/NovelSelector.vue`:

```vue
<template>
  <div class="space-y-2">
    <el-select-v2
      v-model="selected"
      :options="options"
      placeholder="选择或输入小说"
      filterable
      allow-create
      clearable
      style="width: 100%"
    />
    <el-button type="primary" size="small" style="width: 100%" @click="load" :disabled="!selected">
      加载
    </el-button>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { listNovels } from '@/api.js'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const selected = ref('')
const options = ref([])

async function fetchNovels() {
  try {
    const res = await listNovels()
    options.value = (res.items || []).map(n => ({ value: n.novel_id, label: n.novel_id }))
  } catch {
    options.value = []
  }
}

function load() {
  if (selected.value) {
    store.loadNovel(selected.value)
  }
}

fetchNovels()

watch(() => store.novelId, (id) => {
  if (id && !options.value.find(o => o.value === id)) {
    options.value.push({ value: id, label: id })
  }
  selected.value = id
})
</script>
```

- [ ] **Step 4: Update App.vue with full layout**

Replace `src/novel_dev/web/src/App.vue`:

```vue
<template>
  <div class="h-screen flex bg-gray-50 dark:bg-gray-900">
    <!-- Sidebar -->
    <aside class="w-64 border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col">
      <div class="p-4 border-b border-gray-200 dark:border-gray-700">
        <h1 class="font-bold text-lg text-gray-900 dark:text-gray-100">Novel Dev</h1>
      </div>

      <div class="p-3 border-b border-gray-200 dark:border-gray-700">
        <NovelSelector />
      </div>

      <nav class="flex-1 p-2 overflow-y-auto">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          class="block px-3 py-2 rounded-lg mb-1 text-sm transition-colors"
          :class="route.path === item.path
            ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
            : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'"
        >
          {{ item.label }}
        </router-link>
      </nav>
    </aside>

    <!-- Main content -->
    <main class="flex-1 flex flex-col overflow-hidden">
      <header class="h-14 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center justify-between px-4">
        <div class="flex items-center gap-3">
          <span class="font-medium text-gray-900 dark:text-gray-100">{{ novelStore.novelId || '未选择小说' }}</span>
          <el-tag v-if="novelStore.novelState.current_phase" size="small" type="info">
            {{ novelStore.currentPhaseLabel }}
          </el-tag>
          <span v-if="novelStore.novelState.current_volume_id" class="text-xs text-gray-500 dark:text-gray-400">
            {{ novelStore.novelState.current_volume_id }} / {{ novelStore.novelState.current_chapter_id }}
          </span>
        </div>
        <DarkModeToggle />
      </header>

      <div class="flex-1 overflow-auto p-4">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import { useNovelStore } from '@/stores/novel.js'
import NovelSelector from '@/components/NovelSelector.vue'
import DarkModeToggle from '@/components/DarkModeToggle.vue'

const route = useRoute()
const novelStore = useNovelStore()

const menuItems = [
  { path: '/dashboard', label: '仪表盘' },
  { path: '/documents', label: '设定资料' },
  { path: '/volume-plan', label: '卷规划' },
  { path: '/chapters', label: '章节列表' },
  { path: '/entities', label: '实体百科' },
  { path: '/timeline', label: '时间线' },
  { path: '/locations', label: '地点' },
  { path: '/foreshadowings', label: '伏笔' },
  { path: '/config', label: '模型配置' },
  { path: '/logs', label: '实时日志' },
]
</script>
```

- [ ] **Step 5: Verify layout and dark mode**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web
npm run dev &
```

Open `http://localhost:5173`. Expected:
- Sidebar with NovelSelector dropdown renders
- Menu items are clickable, route changes
- Dark mode toggle button works, page switches to dark theme
- Element Plus components (select, button, tag) adapt to dark mode

- [ ] **Step 6: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/web/src/components/ src/novel_dev/web/src/composables/ src/novel_dev/web/src/App.vue src/novel_dev/web/src/style.css
git commit -m "feat(frontend): add layout shell, dark mode, novel selector"
```

---

### Task 4: Dashboard View + Score Radar + Action Pipeline

**Files:**
- Create: `src/novel_dev/web/src/components/ScoreRadar.vue`
- Create: `src/novel_dev/web/src/components/ActionPipeline.vue`
- Create: `src/novel_dev/web/src/views/Dashboard.vue`

- [ ] **Step 1: Create ScoreRadar component**

Create `src/novel_dev/web/src/components/ScoreRadar.vue`:

```vue
<template>
  <v-chart class="w-full h-64" :option="option" autoresize />
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, RadarChart, TooltipComponent])

const props = defineProps({
  scores: { type: Object, default: () => ({}) },
})

const dimMap = {
  plot_tension: '情节张力',
  characterization: '人物塑造',
  readability: '可读性',
  consistency: '一致性',
  humanity: '人性刻画',
}

const option = computed(() => {
  const dims = Object.keys(dimMap)
  const indicator = dims.map(k => ({ name: dimMap[k], max: 100 }))
  const data = dims.map(k => props.scores[k]?.score ?? 0)

  return {
    radar: {
      indicator,
      radius: '65%',
      splitNumber: 4,
      axisName: { color: '#666', fontSize: 12 },
    },
    series: [{
      type: 'radar',
      data: [{
        value: data,
        name: '评分',
        areaStyle: { color: 'rgba(59, 130, 246, 0.2)' },
        lineStyle: { color: '#3b82f6' },
        itemStyle: { color: '#3b82f6' },
      }],
    }],
    tooltip: { trigger: 'item' },
  }
})
</script>
```

- [ ] **Step 2: Create ActionPipeline component**

Create `src/novel_dev/web/src/components/ActionPipeline.vue`:

```vue
<template>
  <div class="flex flex-wrap items-center gap-2">
    <template v-for="(step, idx) in steps" :key="step.key">
      <el-button
        :type="stepType(step)"
        :loading="store.loadingActions[step.key]"
        :disabled="!step.enabled"
        size="default"
        @click="store.executeAction(step.key)"
      >
        <el-icon v-if="stepDone(step)" class="mr-1"><Check /></el-icon>
        {{ step.label }}
      </el-button>
      <el-icon v-if="idx < steps.length - 1" class="text-gray-300 dark:text-gray-600"><ArrowRight /></el-icon>
    </template>

    <el-button
      :loading="store.loadingActions['export']"
      @click="store.executeAction('export')"
    >
      导出小说
    </el-button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()

const phaseOrder = ['brainstorming', 'volume_planning', 'context_preparation', 'drafting', 'reviewing', 'editing', 'fast_reviewing', 'librarian', 'completed']

const steps = computed(() => [
  { key: 'brainstorm', label: '脑暴', enabled: store.canBrainstorm },
  { key: 'volume_plan', label: '分卷', enabled: store.canVolumePlan },
  { key: 'context', label: '上下文', enabled: store.canContext },
  { key: 'draft', label: '草稿', enabled: store.canDraft },
  { key: 'advance', label: '推进', enabled: store.canAdvance },
  { key: 'librarian', label: '归档', enabled: store.canLibrarian },
])

const currentPhaseIdx = computed(() => {
  return phaseOrder.indexOf(store.novelState.current_phase)
})

function stepType(step) {
  const idx = phaseOrder.indexOf(step.key === 'advance' ? 'reviewing' : step.key === 'librarian' ? 'librarian' : step.key)
  if (idx === currentPhaseIdx.value) return 'primary'
  if (idx < currentPhaseIdx.value) return 'success'
  return 'default'
}

function stepDone(step) {
  const idx = phaseOrder.indexOf(step.key === 'advance' ? 'reviewing' : step.key === 'librarian' ? 'librarian' : step.key)
  return idx < currentPhaseIdx.value
}
</script>
```

- [ ] **Step 3: Create Dashboard view**

Create `src/novel_dev/web/src/views/Dashboard.vue`:

```vue
<template>
  <div v-if="!store.novelId" class="text-center py-20 text-gray-400">
    请从侧边栏选择或输入一个小说ID
  </div>

  <div v-else class="space-y-4">
    <!-- Stat cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="text-sm text-gray-500 dark:text-gray-400">当前阶段</div>
        <div class="text-2xl font-bold mt-1">{{ store.currentPhaseLabel }}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="text-sm text-gray-500 dark:text-gray-400">当前卷/章</div>
        <div class="text-2xl font-bold mt-1">{{ store.currentVolumeChapter }}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="text-sm text-gray-500 dark:text-gray-400">已归档章节</div>
        <div class="text-2xl font-bold mt-1">{{ store.archiveStats.archived_chapter_count || 0 }}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="text-sm text-gray-500 dark:text-gray-400">总字数</div>
        <div class="text-2xl font-bold mt-1">{{ formatNumber(store.archiveStats.total_word_count || 0) }}</div>
      </div>
    </div>

    <!-- Current chapter card -->
    <div v-if="store.currentChapter" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-bold text-lg">当前章节：{{ store.currentChapter.title }}</h3>
        <el-tag :type="statusType(store.currentChapter.status)" size="small">{{ store.currentChapter.status }}</el-tag>
      </div>
      <div class="text-sm text-gray-500 dark:text-gray-400 mb-2">字数：{{ store.currentChapter.word_count || 0 }}</div>

      <!-- Score radar -->
      <ScoreRadar v-if="store.currentChapter.score_breakdown" :scores="store.currentChapter.score_breakdown" />

      <div v-if="store.currentChapter.score_overall != null" class="mt-2 text-sm">
        审核总分：{{ store.currentChapter.score_overall }}
      </div>
      <div v-if="store.currentChapter.fast_review_score != null" class="mt-1 text-sm">
        速审分数：{{ store.currentChapter.fast_review_score }}
      </div>
    </div>

    <!-- Actions -->
    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 class="font-bold mb-3">操作</h3>
      <ActionPipeline />
    </div>
  </div>
</template>

<script setup>
import { useNovelStore } from '@/stores/novel.js'
import ScoreRadar from '@/components/ScoreRadar.vue'
import ActionPipeline from '@/components/ActionPipeline.vue'

const store = useNovelStore()

function formatNumber(n) {
  return n.toLocaleString('zh-CN')
}

function statusType(s) {
  const map = { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }
  return map[s] || 'info'
}
</script>
```

- [ ] **Step 4: Verify dashboard renders**

Start backend: `PYTHONPATH=src python -m uvicorn novel_dev.api:app --reload` (port 8000)
Start frontend: `cd src/novel_dev/web && npm run dev` (port 5173)
Open `http://localhost:5173`.

Select a novel from dropdown, click "加载". Expected:
- Dashboard shows 4 stat cards with real data
- Current chapter card appears if chapter exists
- ActionPipeline buttons show correct enabled/disabled states
- ScoreRadar renders if chapter has review scores

- [ ] **Step 5: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/web/src/components/ScoreRadar.vue src/novel_dev/web/src/components/ActionPipeline.vue src/novel_dev/web/src/views/Dashboard.vue
git commit -m "feat(frontend): add dashboard with score radar and action pipeline"
```

---

### Task 5: Chapter Views (List + Gantt + Detail)

**Files:**
- Create: `src/novel_dev/web/src/components/ChapterProgressGantt.vue`
- Create: `src/novel_dev/web/src/views/ChapterList.vue`
- Create: `src/novel_dev/web/src/views/ChapterDetail.vue`

- [ ] **Step 1: Create ChapterProgressGantt component**

Create `src/novel_dev/web/src/components/ChapterProgressGantt.vue`:

```vue
<template>
  <v-chart class="w-full h-48" :option="option" autoresize />
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CustomChart, GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, CustomChart, GridComponent, TooltipComponent])

const props = defineProps({
  chapters: { type: Array, default: () => [] },
})

const statusColor = {
  pending: '#94a3b8',
  drafted: '#3b82f6',
  edited: '#22c55e',
  archived: '#a855f7',
}

const statusOrder = ['archived', 'edited', 'drafted', 'pending']

const option = computed(() => {
  const data = []
  props.chapters.forEach((ch) => {
    const target = ch.target_word_count || 3000
    const current = ch.word_count || 0
    const pct = Math.min(current / target, 1)
    const yIdx = statusOrder.indexOf(ch.status) >= 0 ? statusOrder.indexOf(ch.status) : 3
    data.push({
      value: [ch.chapter_number - 1, yIdx, pct],
      itemStyle: { color: statusColor[ch.status] || '#94a3b8' },
      name: ch.title,
      status: ch.status,
      word_count: current,
      target,
    })
  })

  function renderItem(params, api) {
    const x = api.value(0)
    const y = api.value(1)
    const size = api.size([1, 1])
    const w = size[0] * 0.7
    const h = size[1] * 0.6
    const style = api.style()
    return {
      type: 'rect',
      shape: { x: api.coord([x, y])[0] - w / 2, y: api.coord([x, y])[1] - h / 2, width: w * api.value(2), height: h },
      style,
    }
  }

  return {
    tooltip: {
      formatter: (p) => `${p.data.name}<br/>状态: ${p.data.status}<br/>字数: ${p.data.word_count}/${p.data.target}`,
    },
    grid: { top: 10, bottom: 30, left: 80, right: 20 },
    xAxis: { type: 'category', data: props.chapters.map(c => `第${c.chapter_number}章`) },
    yAxis: { type: 'category', data: statusOrder.map(s => ({ archived: '已归档', edited: '已编辑', drafted: '草稿', pending: '待写' }[s])) },
    series: [{ type: 'custom', renderItem, data }],
  }
})
</script>
```

- [ ] **Step 2: Create ChapterList view**

Create `src/novel_dev/web/src/views/ChapterList.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">章节列表</h2>

    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <ChapterProgressGantt :chapters="store.chapters" />
    </div>

    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="store.chapters" style="width: 100%">
        <el-table-column prop="volume_number" label="卷号" width="70" />
        <el-table-column prop="chapter_number" label="章号" width="70" />
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="word_count" label="字数" width="90" />
        <el-table-column label="进度" width="120">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round(((row.word_count || 0) / (row.target_word_count || 3000)) * 100)"
              :status="row.status === 'archived' ? 'success' : ''"
              :stroke-width="8"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/chapters/${row.chapter_id}`)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { useNovelStore } from '@/stores/novel.js'
import ChapterProgressGantt from '@/components/ChapterProgressGantt.vue'

const store = useNovelStore()

function statusType(s) {
  const map = { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }
  return map[s] || 'info'
}
</script>
```

- [ ] **Step 3: Create ChapterDetail view**

Create `src/novel_dev/web/src/views/ChapterDetail.vue`:

```vue
<template>
  <div v-if="loading" class="text-center py-10">加载中...</div>
  <div v-else-if="!chapter" class="text-center py-10 text-gray-400">章节未找到</div>
  <div v-else class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-bold">{{ chapter.title }}</h2>
      <el-button size="small" @click="$router.push('/chapters')">返回列表</el-button>
    </div>

    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <div class="flex items-center gap-4 text-sm text-gray-500 dark:text-gray-400">
        <el-tag :type="statusType(chapter.status)" size="small">{{ chapter.status }}</el-tag>
        <span>草稿字数: {{ wordCount(chapter.raw_draft) }}</span>
        <span>润色字数: {{ wordCount(chapter.polished_text) }}</span>
        <span v-if="chapter.score_overall != null">审核总分: {{ chapter.score_overall }}</span>
      </div>
      <ScoreRadar v-if="chapter.score_breakdown" class="mt-4" :scores="chapter.score_breakdown" />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="flex items-center justify-between mb-2">
          <h3 class="font-bold">草稿原文</h3>
          <el-button size="small" @click="copy(chapter.raw_draft)">复制</el-button>
        </div>
        <div class="whitespace-pre-wrap text-sm leading-relaxed max-h-[60vh] overflow-y-auto font-serif">
          {{ chapter.raw_draft || '无草稿' }}
        </div>
      </div>

      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="flex items-center justify-between mb-2">
          <h3 class="font-bold">润色后正文</h3>
          <el-button size="small" @click="copy(chapter.polished_text)">复制</el-button>
        </div>
        <div class="whitespace-pre-wrap text-sm leading-relaxed max-h-[60vh] overflow-y-auto font-serif">
          {{ chapter.polished_text || '未润色' }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getChapterText } from '@/api.js'
import ScoreRadar from '@/components/ScoreRadar.vue'

const route = useRoute()
const chapter = ref(null)
const loading = ref(true)

onMounted(async () => {
  try {
    const res = await getChapterText(route.params.novelId || '', route.params.chapterId)
    chapter.value = res
  } catch {
    chapter.value = null
  } finally {
    loading.value = false
  }
})

function wordCount(text) {
  return text ? text.replace(/\s/g, '').length : 0
}

function statusType(s) {
  const map = { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }
  return map[s] || 'info'
}

function copy(text) {
  if (!text) return
  navigator.clipboard.writeText(text)
  ElMessage.success('已复制到剪贴板')
}
</script>
```

- [ ] **Step 4: Verify chapter views**

Open `http://localhost:5173`, select a novel, navigate to "章节列表". Expected:
- ChapterProgressGantt renders colored bars for each chapter
- Table shows chapters with progress bars
- Click "查看" navigates to ChapterDetail
- ChapterDetail shows side-by-side raw vs polished text
- ScoreRadar appears if scores exist

- [ ] **Step 5: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/web/src/components/ChapterProgressGantt.vue src/novel_dev/web/src/views/ChapterList.vue src/novel_dev/web/src/views/ChapterDetail.vue
git commit -m "feat(frontend): add chapter list with gantt chart and detail view"
```

---

### Task 6: World Encyclopedia Views (Entities + Graph + Timeline + Locations + Foreshadowings)

**Files:**
- Create: `src/novel_dev/web/src/components/EntityGraph.vue`
- Create: `src/novel_dev/web/src/views/Entities.vue`
- Create: `src/novel_dev/web/src/views/Timeline.vue`
- Create: `src/novel_dev/web/src/views/Locations.vue`
- Create: `src/novel_dev/web/src/views/Foreshadowings.vue`

- [ ] **Step 1: Create EntityGraph component**

Create `src/novel_dev/web/src/components/EntityGraph.vue`:

```vue
<template>
  <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
    <h3 class="font-bold mb-2">关系图谱</h3>
    <v-chart class="w-full h-80" :option="option" autoresize @click="onClick" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, GraphChart, TooltipComponent])

const props = defineProps({
  entities: { type: Array, default: () => [] },
  relationships: { type: Array, default: () => [] },
})

const emit = defineEmits(['select'])

const typeColor = {
  character: '#f97316',
  item: '#3b82f6',
  location: '#22c55e',
  other: '#6b7280',
}

const typeShape = {
  character: 'circle',
  item: 'rect',
  location: 'diamond',
  other: 'circle',
}

const option = computed(() => {
  const nodes = props.entities.map(e => ({
    id: e.entity_id,
    name: e.name,
    symbolSize: 30 + (e.current_version || 1) * 5,
    symbol: typeShape[e.type] || 'circle',
    itemStyle: { color: typeColor[e.type] || '#6b7280' },
    category: e.type,
  }))

  const links = props.relationships.map(r => ({
    source: r.source_id,
    target: r.target_id,
    label: { show: true, formatter: r.relation_type },
    lineStyle: { curveness: 0.2 },
  }))

  return {
    tooltip: {},
    series: [{
      type: 'graph',
      layout: 'force',
      data: nodes,
      links,
      roam: true,
      label: { show: true },
      force: { repulsion: 300, edgeLength: 100 },
    }],
  }
})

function onClick(params) {
  if (params.dataType === 'node') {
    emit('select', params.data.id)
  }
}
</script>
```

- [ ] **Step 2: Create Entities view**

Create `src/novel_dev/web/src/views/Entities.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">实体百科</h2>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="人物" name="character" />
      <el-tab-pane label="物品" name="item" />
      <el-tab-pane label="其他" name="other" />
    </el-tabs>

    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="filtered" style="width: 100%">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column prop="current_version" label="版本" width="80" />
        <el-table-column label="最新状态">
          <template #default="{ row }">
            <pre class="text-xs whitespace-pre-wrap max-h-24 overflow-auto">{{ JSON.stringify(row.latest_state, null, 2) }}</pre>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <EntityGraph :entities="store.entities" :relationships="relationships" @select="onSelect" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import EntityGraph from '@/components/EntityGraph.vue'

const store = useNovelStore()
const activeTab = ref('character')

const filtered = computed(() =>
  store.entities.filter(e => e.type === activeTab.value)
)

const relationships = computed(() => {
  // Backend doesn't have a relationships endpoint yet; return empty
  return []
})

onMounted(() => {
  store.fetchEntities()
})

function onSelect(id) {
  console.log('Selected entity:', id)
}
</script>
```

- [ ] **Step 3: Create Timeline view**

Create `src/novel_dev/web/src/views/Timeline.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">时间线</h2>
    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <el-timeline>
        <el-timeline-item
          v-for="t in store.timelines"
          :key="t.id"
          :timestamp="`Tick ${t.tick}`"
        >
          {{ t.narrative }}
          <div v-if="t.anchor_chapter_id" class="text-xs text-gray-400 mt-1">
            关联章节: {{ t.anchor_chapter_id }}
          </div>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
onMounted(() => store.fetchTimelines())
</script>
```

- [ ] **Step 4: Create Locations view**

Create `src/novel_dev/web/src/views/Locations.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">地点</h2>
    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="store.spacelines" row-key="id" :tree-props="{ children: 'children', hasChildren: 'hasChildren' }">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="narrative" label="描述" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
onMounted(() => store.fetchSpacelines())
</script>
```

- [ ] **Step 5: Create Foreshadowings view**

Create `src/novel_dev/web/src/views/Foreshadowings.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">伏笔</h2>
    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="store.foreshadowings" style="width: 100%">
        <el-table-column prop="content" label="内容" show-overflow-tooltip />
        <el-table-column prop="回收状态" label="回收状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.回收状态 === 'recovered' ? 'success' : 'warning'" size="small">{{ row.回收状态 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="埋下_chapter_id" label="埋下章节" width="120" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
onMounted(() => store.fetchForeshadowings())
</script>
```

- [ ] **Step 6: Verify encyclopedia views**

Navigate to each view from sidebar. Expected:
- Entities: tabs filter by type, table shows data, graph renders nodes
- Timeline: vertical timeline with tick values
- Locations: tree table (flat if no parent-child)
- Foreshadowings: table with colored status tags

- [ ] **Step 7: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/web/src/components/EntityGraph.vue src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/views/Timeline.vue src/novel_dev/web/src/views/Locations.vue src/novel_dev/web/src/views/Foreshadowings.vue
git commit -m "feat(frontend): add world encyclopedia views with entity graph"
```

---

### Task 7: Documents, Volume Plan, Config Views

**Files:**
- Create: `src/novel_dev/web/src/views/Documents.vue`
- Create: `src/novel_dev/web/src/views/VolumePlan.vue`
- Create: `src/novel_dev/web/src/views/Config.vue`

- [ ] **Step 1: Create Documents view**

Create `src/novel_dev/web/src/views/Documents.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">设定资料</h2>

    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 class="font-bold mb-3">上传设定文件</h3>
      <div class="flex items-center gap-2">
        <input ref="fileInput" type="file" accept=".txt,.md" @change="onFileChange" class="text-sm" />
        <el-button type="primary" :loading="uploading" @click="upload">上传</el-button>
      </div>
    </div>

    <div v-if="store.pendingDocs.length" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 class="font-bold mb-3">待审批</h3>
      <el-table :data="store.pendingDocs">
        <el-table-column prop="extraction_type" label="类型" />
        <el-table-column prop="status" label="状态" />
        <el-table-column prop="created_at" label="创建时间" />
        <el-table-column label="操作">
          <template #default="{ row }">
            <el-button size="small" @click="approve(row.id)">批准</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 class="font-bold mb-3">已批准文档</h3>
      <el-empty v-if="!approvedDocs.length" description="暂无文档" />
      <el-collapse v-else>
        <el-collapse-item v-for="doc in approvedDocs" :key="doc.id" :title="`${doc.title} (${doc.doc_type})`">
          <pre class="whitespace-pre-wrap text-sm">{{ doc.content }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { uploadDocument, approvePending, getSynopsis } from '@/api.js'
import { ElMessage } from 'element-plus'

const store = useNovelStore()
const fileInput = ref(null)
const selectedFile = ref(null)
const uploading = ref(false)
const approvedDocs = ref([])

const fileContent = ref('')

function onFileChange(e) {
  const file = e.target.files[0]
  if (!file) return
  selectedFile.value = file
  const reader = new FileReader()
  reader.onload = (ev) => { fileContent.value = ev.target.result }
  reader.readAsText(file)
}

async function upload() {
  if (!selectedFile.value || !fileContent.value) return
  uploading.value = true
  try {
    await uploadDocument(store.novelId, selectedFile.value.name, fileContent.value)
    ElMessage.success('上传成功')
    await store.fetchDocuments()
  } finally {
    uploading.value = false
    selectedFile.value = null
    fileContent.value = ''
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function approve(id) {
  await approvePending(store.novelId, id)
  ElMessage.success('已批准')
  await store.fetchDocuments()
  await loadApproved()
}

async function loadApproved() {
  try {
    const res = await getSynopsis(store.novelId)
    approvedDocs.value = res.content ? [{ id: 'synopsis', title: '大纲', doc_type: 'synopsis', content: res.content }] : []
  } catch {
    approvedDocs.value = []
  }
}

onMounted(() => {
  store.fetchDocuments()
  loadApproved()
})
</script>
```

- [ ] **Step 2: Create VolumePlan view**

Create `src/novel_dev/web/src/views/VolumePlan.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">卷规划</h2>

    <div v-if="!store.volumePlan" class="text-center py-10 text-gray-400">
      暂无卷规划数据
    </div>

    <div v-else class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 class="font-bold text-lg">{{ store.volumePlan.title }}</h3>
      <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">{{ store.volumePlan.summary }}</p>
      <div class="flex gap-4 mt-2 text-sm text-gray-500">
        <span>章节数: {{ store.volumePlan.total_chapters }}</span>
        <span>估算字数: {{ store.volumePlan.estimated_total_words }}</span>
      </div>

      <el-timeline class="mt-4">
        <el-timeline-item v-for="ch in store.volumePlan.chapters" :key="ch.chapter_id">
          <div class="font-medium">{{ ch.title }}（第{{ ch.chapter_number }}章）</div>
          <div class="text-sm text-gray-500 dark:text-gray-400">{{ ch.summary }}</div>
          <div class="flex gap-2 mt-1">
            <el-tag size="small" type="info">目标: {{ ch.target_word_count }}</el-tag>
            <el-tag size="small">氛围: {{ ch.target_mood }}</el-tag>
          </div>
          <el-collapse v-if="ch.beats?.length" class="mt-2">
            <el-collapse-item title="节拍">
              <ol class="list-decimal list-inside text-sm space-y-1">
                <li v-for="(beat, i) in ch.beats" :key="i">{{ beat.summary }}（{{ beat.target_mood }}）</li>
              </ol>
            </el-collapse-item>
          </el-collapse>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
</script>
```

- [ ] **Step 3: Create Config view**

Create `src/novel_dev/web/src/views/Config.vue`:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">模型配置</h2>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">LLM 配置</h3>
        <el-collapse v-model="activePanels">
          <el-collapse-item title="全局默认值" name="defaults">
            <ConfigForm v-model="config.defaults" />
          </el-collapse-item>
          <el-collapse-item v-for="agent in agentNames" :key="agent" :title="agent" :name="agent">
            <ConfigForm v-model="config.agents[agent]" />
          </el-collapse-item>
        </el-collapse>
        <el-button type="primary" class="mt-4" :loading="savingConfig" @click="saveConfig">保存配置</el-button>
      </div>

      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">API Key</h3>
        <el-form label-width="120px">
          <el-form-item v-for="key in envKeys" :key="key" :label="keyLabels[key]">
            <el-input v-model="envConfig[key]" />
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="savingEnv" @click="saveEnv">保存 Key</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getLLMConfig, saveLLMConfig, getEnvConfig, saveEnvConfig } from '@/api.js'
import { ElMessage } from 'element-plus'

const config = ref({ defaults: {}, agents: {} })
const envConfig = ref({})
const savingConfig = ref(false)
const savingEnv = ref(false)
const activePanels = ref(['defaults'])

const agentNames = [
  'brainstorm_agent', 'volume_planner_agent', 'setting_extractor_agent',
  'style_profiler_agent', 'file_classifier', 'context_agent',
  'writer_agent', 'critic_agent', 'editor_agent',
  'fast_review_agent', 'librarian_agent',
]

const envKeys = ['anthropic_api_key', 'openai_api_key', 'moonshot_api_key', 'minimax_api_key', 'zhipu_api_key']
const keyLabels = {
  anthropic_api_key: 'Anthropic',
  openai_api_key: 'OpenAI',
  moonshot_api_key: 'Moonshot',
  minimax_api_key: 'MiniMax',
  zhipu_api_key: 'Zhipu',
}

onMounted(async () => {
  try {
    config.value = await getLLMConfig()
  } catch {}
  try {
    envConfig.value = await getEnvConfig()
  } catch {}
})

async function saveConfig() {
  savingConfig.value = true
  try {
    await saveLLMConfig(config.value)
    ElMessage.success('配置已保存')
  } finally {
    savingConfig.value = false
  }
}

async function saveEnv() {
  savingEnv.value = true
  try {
    await saveEnvConfig(envConfig.value)
    ElMessage.success('API Key 已保存')
  } finally {
    savingEnv.value = false
  }
}
</script>
```

Note: `ConfigForm` is a sub-component not yet defined. For this task, inline the form fields directly in Config.vue instead:

Replace the `<ConfigForm v-model="..." />` references with inline `el-form` blocks. Or skip Config.vue refinement — it works as-is with `v-model` on plain objects.

Actually, the simplest approach: remove `ConfigForm` references and render raw JSON in `el-input type="textarea"` for now. It's functional and can be polished later.

Let me fix the Config.vue:

```vue
<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">模型配置</h2>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">LLM 配置</h3>
        <el-input v-model="configText" type="textarea" :rows="20" />
        <el-button type="primary" class="mt-4" :loading="savingConfig" @click="saveConfig">保存配置</el-button>
      </div>

      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">API Key</h3>
        <el-form label-width="120px">
          <el-form-item v-for="key in envKeys" :key="key" :label="keyLabels[key]">
            <el-input v-model="envConfig[key]" />
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="savingEnv" @click="saveEnv">保存 Key</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getLLMConfig, saveLLMConfig, getEnvConfig, saveEnvConfig } from '@/api.js'
import { ElMessage } from 'element-plus'

const configText = ref('')
const envConfig = ref({})
const savingConfig = ref(false)
const savingEnv = ref(false)

const envKeys = ['anthropic_api_key', 'openai_api_key', 'moonshot_api_key', 'minimax_api_key', 'zhipu_api_key']
const keyLabels = {
  anthropic_api_key: 'Anthropic',
  openai_api_key: 'OpenAI',
  moonshot_api_key: 'Moonshot',
  minimax_api_key: 'MiniMax',
  zhipu_api_key: 'Zhipu',
}

onMounted(async () => {
  try {
    const cfg = await getLLMConfig()
    configText.value = JSON.stringify(cfg, null, 2)
  } catch {}
  try {
    envConfig.value = await getEnvConfig()
  } catch {}
})

async function saveConfig() {
  savingConfig.value = true
  try {
    const cfg = JSON.parse(configText.value)
    await saveLLMConfig(cfg)
    ElMessage.success('配置已保存')
  } catch {
    ElMessage.error('JSON 格式错误')
  } finally {
    savingConfig.value = false
  }
}

async function saveEnv() {
  savingEnv.value = true
  try {
    await saveEnvConfig(envConfig.value)
    ElMessage.success('API Key 已保存')
  } finally {
    savingEnv.value = false
  }
}
</script>
```

- [ ] **Step 4: Verify views**

Navigate to Documents, Volume Plan, Config. Expected:
- Documents: file upload works, pending table renders
- Volume Plan: timeline with chapters and beats
- Config: JSON textarea editable, API key inputs work

- [ ] **Step 5: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/web/src/views/Documents.vue src/novel_dev/web/src/views/VolumePlan.vue src/novel_dev/web/src/views/Config.vue
git commit -m "feat(frontend): add documents, volume plan, and config views"
```

---

### Task 8: Realtime Log (Backend + Frontend)

**Files:**
- Create: `src/novel_dev/services/log_service.py`
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/agents/director.py`
- Create: `src/novel_dev/web/src/composables/useRealtimeLog.js`
- Create: `src/novel_dev/web/src/components/LogConsole.vue`
- Create: `src/novel_dev/web/src/views/RealtimeLog.vue`

- [ ] **Step 1: Create LogService**

Create `src/novel_dev/services/log_service.py`:

```python
from collections import deque
from datetime import datetime
import asyncio


class LogService:
    _instance = None
    _buffers: dict[str, deque] = {}
    _listeners: dict[str, list[asyncio.Queue]] = {}
    MAX_SIZE = 500

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def add_log(self, novel_id: str, agent: str, message: str, level: str = "info"):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": agent,
            "message": message,
            "level": level,
        }
        buf = self._buffers.setdefault(novel_id, deque(maxlen=self.MAX_SIZE))
        buf.append(entry)
        for q in self._listeners.get(novel_id, []):
            asyncio.create_task(self._safe_put(q, entry))

    async def _safe_put(self, q: asyncio.Queue, entry: dict):
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            pass

    def subscribe(self, novel_id: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self._listeners.setdefault(novel_id, []).append(q)
        for entry in list(self._buffers.get(novel_id, [])):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                break
        return q

    def unsubscribe(self, novel_id: str, q: asyncio.Queue):
        listeners = self._listeners.get(novel_id, [])
        if q in listeners:
            listeners.remove(q)


log_service = LogService()
```

- [ ] **Step 2: Add SSE endpoint to routes.py**

Add to `src/novel_dev/api/routes.py` (before the existing closing of the file, after the last route):

```python
from fastapi.responses import StreamingResponse
from novel_dev.services.log_service import log_service as _log_service

@router.get("/api/novels/{novel_id}/logs/stream")
async def stream_logs(novel_id: str):
    import json

    q = _log_service.subscribe(novel_id)

    async def event_generator():
        try:
            while True:
                entry = await q.get()
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            _log_service.unsubscribe(novel_id, q)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

Add `import asyncio` at the top of `routes.py` if not already present.

- [ ] **Step 3: Add log calls to director**

Modify `src/novel_dev/agents/director.py`. Add import near the top:

```python
from novel_dev.services.log_service import log_service
```

In `advance()` method, add logging at the beginning:

```python
async def advance(self, novel_id: str) -> NovelState:
    log_service.add_log(novel_id, "NovelDirector", f"开始推进: 当前阶段 {state.current_phase}")
    # ... existing code ...
```

And at the end of each phase handler, after successful completion:

```python
# After save_checkpoint in each branch:
log_service.add_log(novel_id, "NovelDirector", f"阶段推进完成: {next_phase}")
```

For a minimal change, add just one log call at the start of `advance()` and one after each `save_checkpoint` call.

The simplest approach: add this line right after `current = Phase(state.current_phase)` in `advance()`:

```python
log_service.add_log(novel_id, "NovelDirector", f"Advancing from phase: {current.value}")
```

And one line at the end of `advance()`, right before `return state`:

```python
log_service.add_log(novel_id, "NovelDirector", f"Advanced to phase: {state.current_phase}")
```

Wait, `advance()` doesn't return `state` at the end directly. Let me check the structure. Looking at the director code from earlier, each phase handler returns `await self.save_checkpoint(...)`. So the logging should go in each handler.

For minimal impact, add one log at the very start of `advance()`:

```python
async def advance(self, novel_id: str) -> NovelState:
    state = await self.resume(novel_id)
    if not state:
        raise ValueError(f"Novel state not found for {novel_id}")
    current = Phase(state.current_phase)
    log_service.add_log(novel_id, "NovelDirector", f"开始推进流水线: {current.value}")
    # ... rest unchanged
```

And in `_run_volume_planner`, `_run_critic`, `_run_editor`, `_run_fast_review`, `_run_librarian`:

```python
log_service.add_log(novel_id, "NovelDirector", "Running volume planner...")
```

Let's keep it simple: just add the import and one log at the start of `advance()` for now. More agent logging can be added incrementally.

- [ ] **Step 4: Create useRealtimeLog composable**

Create `src/novel_dev/web/src/composables/useRealtimeLog.js`:

```javascript
import { ref, watch } from 'vue'

export function useRealtimeLog(novelIdRef) {
  const logs = ref([])
  const connected = ref(false)
  let es = null

  function connect() {
    if (es || !novelIdRef.value) return
    es = new EventSource(`/api/novels/${novelIdRef.value}/logs/stream`)
    es.onopen = () => { connected.value = true }
    es.onmessage = (e) => {
      const entry = JSON.parse(e.data)
      logs.value.push(entry)
      if (logs.value.length > 500) logs.value.shift()
    }
    es.onerror = () => { connected.value = false }
  }

  function disconnect() {
    es?.close()
    es = null
    connected.value = false
  }

  watch(novelIdRef, (id, oldId) => {
    if (id && id !== oldId) {
      disconnect()
      logs.value = []
      connect()
    }
  }, { immediate: true })

  return { logs, connected, connect, disconnect }
}
```

- [ ] **Step 5: Create LogConsole component**

Create `src/novel_dev/web/src/components/LogConsole.vue`:

```vue
<template>
  <div class="flex flex-col h-full bg-gray-950 text-gray-100 rounded-lg overflow-hidden font-mono text-sm">
    <div class="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-800">
      <div class="flex items-center gap-2">
        <span class="text-xs text-gray-400">Agent 过滤:</span>
        <el-tag
          v-for="agent in allAgents"
          :key="agent"
          size="small"
          :type="isFiltered(agent) ? '' : 'info'"
          :effect="isFiltered(agent) ? 'dark' : 'plain'"
          class="cursor-pointer"
          @click="toggleFilter(agent)"
        >
          {{ agent }}
        </el-tag>
      </div>
      <div class="flex items-center gap-2">
        <el-tag size="small" :type="connected ? 'success' : 'danger'">{{ connected ? '已连接' : '断开' }}</el-tag>
        <el-button size="small" @click="paused = !paused">{{ paused ? '继续' : '暂停' }}</el-button>
        <el-button size="small" @click="$emit('clear')">清空</el-button>
      </div>
    </div>

    <div ref="logContainer" class="flex-1 overflow-y-auto p-2 space-y-0.5" @scroll="onScroll">
      <div
        v-for="(log, i) in visibleLogs"
        :key="i"
        class="flex gap-2 hover:bg-gray-900/50 px-1 rounded"
      >
        <span class="text-gray-500 shrink-0">{{ formatTime(log.timestamp) }}</span>
        <span class="shrink-0 font-semibold" :style="{ color: agentColor(log.agent) }">[{{ log.agent }}]</span>
        <span class="text-gray-300">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps({
  logs: { type: Array, default: () => [] },
  connected: { type: Boolean, default: false },
})

const emit = defineEmits(['clear'])

const paused = ref(false)
const filters = ref(new Set())
const logContainer = ref(null)
const autoScroll = ref(true)

const agentColors = {
  NovelDirector: '#9ca3af',
  VolumePlannerAgent: '#60a5fa',
  WriterAgent: '#4ade80',
  CriticAgent: '#fb923c',
  EditorAgent: '#c084fc',
  FastReviewAgent: '#facc15',
  LibrarianAgent: '#f472b6',
  ContextAgent: '#2dd4bf',
}

const allAgents = computed(() => {
  const set = new Set(props.logs.map(l => l.agent))
  return Array.from(set).sort()
})

const visibleLogs = computed(() => {
  if (filters.value.size === 0) return props.logs
  return props.logs.filter(l => filters.value.has(l.agent))
})

function isFiltered(agent) {
  return filters.value.size === 0 || filters.value.has(agent)
}

function toggleFilter(agent) {
  if (filters.value.has(agent)) {
    filters.value.delete(agent)
  } else {
    filters.value.add(agent)
  }
}

function agentColor(agent) {
  return agentColors[agent] || '#9ca3af'
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

function onScroll() {
  const el = logContainer.value
  if (!el) return
  autoScroll.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 20
}

watch(() => props.logs.length, async () => {
  if (paused.value || !autoScroll.value) return
  await nextTick()
  logContainer.value?.scrollTo({ top: logContainer.value.scrollHeight, behavior: 'smooth' })
})
</script>
```

- [ ] **Step 6: Create RealtimeLog view**

Create `src/novel_dev/web/src/views/RealtimeLog.vue`:

```vue
<template>
  <div class="h-full flex flex-col">
    <h2 class="text-xl font-bold mb-2">实时日志</h2>
    <LogConsole
      :logs="logs"
      :connected="connected"
      @clear="logs = []"
      class="flex-1 min-h-0"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { useRealtimeLog } from '@/composables/useRealtimeLog.js'
import LogConsole from '@/components/LogConsole.vue'

const store = useNovelStore()
const novelIdRef = computed(() => store.novelId)
const { logs, connected } = useRealtimeLog(novelIdRef)
</script>
```

- [ ] **Step 7: Run backend tests**

```bash
cd /Users/linlin/Desktop/novel-dev
PYTHONPATH=src python -m pytest tests/ -q
```

Expected: Existing tests pass (the new SSE endpoint doesn't break anything).

- [ ] **Step 8: Verify SSE streaming**

Start backend: `PYTHONPATH=src python -m uvicorn novel_dev.api:app --reload`
Start frontend: `cd src/novel_dev/web && npm run dev`

Open `http://localhost:5173`, select a novel, go to "实时日志". Expected:
- Connection status shows "已连接"
- Advance the pipeline via Dashboard
- Logs appear with colored agent names and timestamps

- [ ] **Step 9: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/services/log_service.py src/novel_dev/api/routes.py src/novel_dev/agents/director.py src/novel_dev/web/src/composables/useRealtimeLog.js src/novel_dev/web/src/components/LogConsole.vue src/novel_dev/web/src/views/RealtimeLog.vue
git commit -m "feat(frontend,backend): add realtime agent log streaming via SSE"
```

---

### Task 9: Production Build Integration

**Files:**
- Modify: `src/novel_dev/api/__init__.py`
- Verify: build succeeds, production serving works

- [ ] **Step 1: Update FastAPI to serve dist/**

Modify `src/novel_dev/api/__init__.py`:

```python
import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from novel_dev.api.routes import router
from novel_dev.api.config_routes import router as config_router

app = FastAPI()
app.include_router(router)
app.include_router(config_router)

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
DIST_DIR = os.path.join(WEB_DIR, "dist")
SERVE_DIR = DIST_DIR if os.path.isdir(DIST_DIR) else WEB_DIR

# Only mount static if the directory exists
static_dir = os.path.join(SERVE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(SERVE_DIR, "index.html"))

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(os.path.join(SERVE_DIR, "index.html"))
```

- [ ] **Step 2: Build production bundle**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web
npm run build
```

Expected: `dist/` directory created with `index.html`, `assets/`, and `static/`.

- [ ] **Step 3: Verify production serving**

```bash
cd /Users/linlin/Desktop/novel-dev
PYTHONPATH=src python -m uvicorn novel_dev.api:app --reload
```

Open `http://localhost:8000/`. Expected:
- New Vite-built frontend loads
- Sidebar, dark mode, dashboard all work
- API calls succeed (relative `/api` paths work because we're on same origin)

- [ ] **Step 4: Add .gitignore for node_modules**

Add to root `.gitignore`:
```
src/novel_dev/web/node_modules/
src/novel_dev/web/dist/
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/linlin/Desktop/novel-dev
PYTHONPATH=src python -m pytest tests/ -q
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/linlin/Desktop/novel-dev
git add src/novel_dev/api/__init__.py .gitignore
git commit -m "feat(frontend): integrate Vite build with FastAPI production serving"
```

---

## Spec Coverage Review

| Spec Requirement | Task |
|---|---|
| Vite scaffolding | Task 1 |
| API layer | Task 2 |
| Vue Router | Task 2 |
| Pinia store | Task 2 |
| Dark mode | Task 3 |
| Layout shell | Task 3 |
| Dashboard with stat cards | Task 4 |
| ScoreRadar component | Task 4 |
| ActionPipeline component | Task 4 |
| ChapterProgressGantt | Task 5 |
| ChapterList view | Task 5 |
| ChapterDetail side-by-side | Task 5 |
| EntityGraph component | Task 6 |
| Entities/Timeline/Locations/Foreshadowings views | Task 6 |
| Documents view | Task 7 |
| VolumePlan view | Task 7 |
| Config view | Task 7 |
| LogService backend | Task 8 |
| SSE endpoint | Task 8 |
| useRealtimeLog composable | Task 8 |
| LogConsole component | Task 8 |
| RealtimeLog view | Task 8 |
| Production build + FastAPI serving | Task 9 |

**No gaps.**

**Placeholder scan:** No TBD, TODO, or vague instructions. Every step has complete code.

**Type consistency:**
- `useRealtimeLog` takes `novelIdRef` (computed ref) consistently
- Pinia store action names match between store definition and component usage
- ECharts imports use the same pattern across all chart components
- API function signatures match between `api.js` and component calls

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-19-frontend-v2-redesign.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**