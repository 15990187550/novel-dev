# Novel Dev Frontend V2 Redesign Design

> **Goal:** Replace the 700-line CDN-based single-file Vue SPA with a Vite-built, componentized frontend featuring dark mode, chapter progress visualization, entity relationship graphs, score radar charts, and a real-time agent log console.

> **Architecture:** Vite + Vue 3 SFC + Vue Router + Pinia + Tailwind CSS + Element Plus + ECharts. The built `dist/` is served by FastAPI `StaticFiles`. Only one new backend endpoint (`/api/novels/{id}/logs/stream`) is required.

> **Tech Stack:** Vite 5, Vue 3.4, Vue Router 4, Pinia 2, Tailwind CSS 3.4, Element Plus 2.5, ECharts 5, vue-echarts, VueUse, Axios

---

## 1. File Structure

### New files (Vite project under `src/novel_dev/web/`)

| File | Responsibility |
|------|----------------|
| `web/package.json` | npm dependencies and scripts |
| `web/vite.config.js` | Vite config, dev proxy to `localhost:8000`, SPA fallback |
| `web/tailwind.config.js` | Content paths, darkMode `class` strategy, custom colors |
| `web/postcss.config.js` | Tailwind + autoprefixer |
| `web/index.html` | Vite entry HTML |
| `web/src/main.js` | Mount app, register Element Plus, Pinia, Vue Router |
| `web/src/App.vue` | Layout shell: sidebar + header + router-view + dark mode toggle |
| `web/src/router.js` | Route table |
| `web/src/api.js` | Axios instance with baseURL, interceptors, per-API functions |
| `web/src/stores/novel.js` | Pinia store: current novel, state, cached data, actions |
| `web/src/composables/useDarkMode.js` | VueUse `useDark` wrapper + Element Plus CSS var sync |
| `web/src/composables/useRealtimeLog.js` | EventSource lifecycle: connect, disconnect, filter, buffer |
| `web/src/components/DarkModeToggle.vue` | Sun/moon icon button |
| `web/src/components/ScoreRadar.vue` | ECharts radar chart for 5-dimension review scores |
| `web/src/components/ChapterProgressGantt.vue` | ECharts custom series: chapter status/timeline bar chart |
| `web/src/components/EntityGraph.vue` | ECharts graph (force-directed) for entity relationships |
| `web/src/components/NovelSelector.vue` | Select-or-create novel dropdown + load button |
| `web/src/components/ActionPipeline.vue` | Step-flow action buttons with enabled/loading states |
| `web/src/components/LogConsole.vue` | Auto-scrolling colored log lines with agent filter |
| `web/src/views/Dashboard.vue` | Stats cards + current chapter + radar + pipeline buttons |
| `web/src/views/Documents.vue` | Upload + pending approvals + approved docs + synopsis preview |
| `web/src/views/VolumePlan.vue` | Volume card + chapter timeline with beats |
| `web/src/views/ChapterList.vue` | Gantt chart + chapter table with mini progress bars |
| `web/src/views/ChapterDetail.vue` | Side-by-side raw vs polished, score radar, word stats |
| `web/src/views/Entities.vue` | Tabs + table + entity relationship graph |
| `web/src/views/Timeline.vue` | Vertical timeline |
| `web/src/views/Locations.vue` | Tree table for spaceline |
| `web/src/views/Foreshadowings.vue` | Table with status tags |
| `web/src/views/Config.vue` | LLM config form (YAML editor) + API key form |
| `web/src/views/RealtimeLog.vue` | Full-screen log console view |

### Modified backend files

| File | Change |
|------|--------|
| `src/novel_dev/api/__init__.py` | In production, serve `web/dist/` instead of `web/` via `StaticFiles` |
| `src/novel_dev/api/routes.py` | Add `GET /api/novels/{novel_id}/logs/stream` SSE endpoint |
| `src/novel_dev/services/log_service.py` | New: in-memory per-novel ring buffer for agent logs |
| `src/novel_dev/agents/director.py` | Inject `LogService.add_log()` at phase transition points |

---

## 2. Dependencies (`package.json`)

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

---

## 3. Build & Dev Configuration

### `vite.config.js`

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

### `tailwind.config.js`

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

### `postcss.config.js`

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

---

## 4. Pinia Store (`stores/novel.js`)

State:
```javascript
{
  novelId: '',           // current selected novel
  novelState: {},        // /api/novels/{id}/state response
  archiveStats: {},      // /api/novels/{id}/archive_stats
  currentChapter: null,  // merged from state + chapter data
  chapters: [],          // /api/novels/{id}/chapters
  volumePlan: null,      // parsed VolumePlan
  entities: [],
  timelines: [],
  spacelines: [],
  foreshadowings: [],
  pendingDocs: [],
  approvedDocs: [],
  loadingActions: {},    // { brainstorm: false, volume_plan: false, ... }
  brainstormPrompt: '',
}
```

Actions:
```javascript
loadNovel(novelId)           // fetch state + archive_stats + chapters
refreshState()               // re-fetch state only
executeAction(actionType)    // call API, set loading, then refreshState
fetchEntities()              // GET /api/novels/{id}/entities
fetchTimelines()             // GET /api/novels/{id}/timelines
fetchSpacelines()            // GET /api/novels/{id}/spacelines
fetchForeshadowings()        // GET /api/novels/{id}/foreshadowings
fetchDocuments()             // GET pending + approved docs
uploadDocument(file)         // POST upload
approveDocument(pendingId)   // POST approve
```

Getters:
```javascript
currentPhaseLabel: translate phase to Chinese
currentVolumeChapter: "第X卷 · 第Y章" or "-"
canBrainstorm, canVolumePlan, ...: phase-gated booleans
```

---

## 5. Vue Router (`router.js`)

```javascript
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
```

Sidebar active state derived from `$route.path`.

---

## 6. API Layer (`api.js`)

Axios instance:
```javascript
const api = axios.create({ baseURL: '/api', timeout: 30000 })
```

Interceptors:
- Request: none needed (no auth tokens)
- Response error: `ElMessage.error(error.response?.data?.detail || '请求失败')`

Exported functions (one per endpoint):
```javascript
listNovels()                     // GET /novels
getNovelState(novelId)           // GET /novels/{id}/state
getArchiveStats(novelId)         // GET /novels/{id}/archive_stats
getChapters(novelId)             // GET /novels/{id}/chapters
getChapterText(novelId, cid)     // GET /novels/{id}/chapters/{cid}/text
getEntities(novelId)             // GET /novels/{id}/entities
getTimelines(novelId)            // GET /novels/{id}/timelines
getSpacelines(novelId)           // GET /novels/{id}/spacelines
getForeshadowings(novelId)       // GET /novels/{id}/foreshadowings
getSynopsis(novelId)             // GET /novels/{id}/synopsis
getVolumePlan(novelId)           // GET /novels/{id}/volume_plan
getReview(novelId)               // GET /novels/{id}/review
getFastReview(novelId)           // GET /novels/{id}/fast_review
getPendingDocs(novelId)          // GET /novels/{id}/documents/pending
uploadDocument(novelId, filename, content)  // POST /novels/{id}/documents/upload
approvePending(novelId, pendingId)          // POST /novels/{id}/documents/pending/approve
brainstorm(novelId)              // POST /novels/{id}/brainstorm
planVolume(novelId, volNum)      // POST /novels/{id}/volume_plan
prepareContext(novelId, cid)     // POST /novels/{id}/chapters/{cid}/context
draftChapter(novelId, cid)       // POST /novels/{id}/chapters/{cid}/draft
advance(novelId)                 // POST /novels/{id}/advance
runLibrarian(novelId)            // POST /novels/{id}/librarian
exportNovel(novelId, format)     // POST /novels/{id}/export
getLLMConfig()                   // GET /config/llm
saveLLMConfig(config)            // POST /config/llm
getEnvConfig()                   // GET /config/env
saveEnvConfig(env)               // POST /config/env
// SSE: handled separately in useRealtimeLog.js, not via axios
```

---

## 7. FastAPI Static Files (Production)

`src/novel_dev/api/__init__.py` changes:

```python
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from novel_dev.api.routes import router
from novel_dev.api.config_routes import router as config_router

app = FastAPI()
app.include_router(router)
app.include_router(config_router)

# Determine web root: prefer built dist/ if exists, else source web/ for dev
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
DIST_DIR = os.path.join(WEB_DIR, "dist")
SERVE_DIR = DIST_DIR if os.path.isdir(DIST_DIR) else WEB_DIR

app.mount("/static", StaticFiles(directory=os.path.join(SERVE_DIR, "static")), name="static")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(SERVE_DIR, "index.html"))

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(os.path.join(SERVE_DIR, "index.html"))
```

Development workflow:
1. Terminal 1: `PYTHONPATH=src python -m uvicorn novel_dev.api:app --reload` (port 8000)
2. Terminal 2: `cd src/novel_dev/web && npm run dev` (port 5173, proxies `/api` to 8000)
3. Open `http://localhost:5173`

Production workflow:
1. `cd src/novel_dev/web && npm install && npm run build`
2. `PYTHONPATH=src python -m uvicorn novel_dev.api:app` (serves `dist/`)

---

## 8. Dark Mode Integration

### Strategy: Tailwind `class` + Element Plus CSS vars

`tailwind.config.js`: `darkMode: 'class'`

`useDarkMode.js`:
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

  // Sync Element Plus CSS variables
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

All views/components use Tailwind classes:
- Light: `bg-gray-50 text-gray-900`
- Dark: `dark:bg-gray-900 dark:text-gray-100`
- Cards: `bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700`

No global dark stylesheet needed — everything is utility-class driven.

---

## 9. Key Components Design

### 9.1 ScoreRadar.vue

ECharts radar chart for CriticAgent's 5 dimensions.

Props: `scores` — `{ plot_tension: 85, characterization: 90, readability: 88, consistency: 82, humanity: 91 }`

Config:
- 5 axes: 情节张力, 人物塑造, 可读性, 一致性, 人性刻画
- Max value 100
- Area fill with semi-transparent color
- Score < 70 triggers red tint on that axis

### 9.2 ChapterProgressGantt.vue

ECharts custom series showing all chapters as horizontal bars.

X axis: chapter number (1..N)
Y axis: chapter status categories (pending, drafted, edited, archived)

Each bar:
- Start: chapter number
- Length: proportional to word count / target word count
- Color: status-dependent (pending=#94a3b8, drafted=#3b82f6, edited=#22c55e, archived=#a855f7)
- Tooltip: title, status, word count, target

### 9.3 EntityGraph.vue

ECharts graph series (force-directed).

Nodes:
- `character`: orange circle, size by version count
- `item`: blue square
- `location`: green diamond
- `other`: gray circle

Edges:
- From `entity_relationships` table
- Label shows `relation_type`
- Curved lines, arrowheads

Interactions:
- Click node → emit `select-entity` event
- Drag to reposition
- Mouse wheel zoom
- Double-click center on node

### 9.4 LogConsole.vue

Props: `logs` array, `filters` array of agent names

Layout:
- Full height flex column
- Log lines: monospace font, timestamp left, colored `[AgentName]` prefix, message
- Colors: VolumePlanner=blue, Writer=green, Critic=orange, Editor=purple, FastReview=yellow, Librarian=pink, Director=gray
- Auto-scroll to bottom (unless user scrolled up)
- Toolbar: agent filter chips, pause/resume, clear, copy-all

---

## 10. View Specifications

### 10.1 Dashboard.vue

Top row: 4 stat cards in a grid (`grid-cols-1 md:grid-cols-2 lg:grid-cols-4`)
- Card 1: "当前阶段" — large text with phase color badge
- Card 2: "当前卷/章" — volume/chapter display
- Card 3: "已归档章节" — number with archive icon
- Card 4: "总字数" — formatted (e.g. 125,000)

Middle: Current chapter card (if exists)
- Title, status pill, word count
- **ScoreRadar** (if reviewed)
- Word count progress bar
- "查看详情" link to ChapterDetail

Bottom: ActionPipeline component
- Horizontal step flow: 脑暴 → 分卷 → 上下文 → 草稿 → 推进 → 归档
- Steps before current: checkmark + green
- Current step: primary button + pulse animation
- Future steps: gray disabled
- Export button always available on the far right

### 10.2 ChapterList.vue

Top: ChapterProgressGantt (full width)

Below: Chapter table
- Columns: 卷号, 章号, 标题, 状态(pill), 字数, 进度条, 操作
- Progress bar: mini horizontal bar, (current/target)*100%
- Actions: "查看详情" → router push to ChapterDetail

Filters above table:
- Volume dropdown
- Status multi-select

### 10.3 ChapterDetail.vue (NEW)

Two-column layout (50/50 on desktop, stacked on mobile):

Left: 草稿原文
- Read-only, plain text rendering
- Word count badge
- "复制" button

Right: 润色后正文
- Read-only
- Word count badge
- "复制" button

Center divider with icons: ↔

Top section (above columns):
- Chapter title, status pill
- ScoreRadar (if scored)
- Word stats: 草稿字数 / 润色字数 / 增长率

No diff highlighting for V1 — just side-by-side display. Diff can be added later if needed.

### 10.4 Config.vue

Keep existing two-column layout but styled with Tailwind:

Left: LLM Config
- Use `el-collapse` inside Tailwind card
- Each agent panel: provider, model, base_url, timeout, retries, temperature
- Fallback as nested collapse
- "保存配置" primary button

Right: API Keys
- Plain text inputs (not password) as existing behavior
- "保存 Key" primary button

No functional changes — only visual restyling.

### 10.5 RealtimeLog.vue

Full page (not drawer):
- Dark background always (`bg-gray-950`), independent of global dark mode
- LogConsole component fills the page
- Connection status indicator in top-right
- Novel selector in top-left (which novel's logs to stream)

---

## 11. SSE Log Streaming (Backend)

### `services/log_service.py`

```python
from collections import deque
from typing import Optional
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
        # Notify listeners
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
        # Replay existing buffer
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

### `routes.py` addition

```python
@router.get("/api/novels/{novel_id}/logs/stream")
async def stream_logs(novel_id: str):
    from fastapi.responses import StreamingResponse
    import json

    q = log_service.subscribe(novel_id)

    async def event_generator():
        try:
            while True:
                entry = await q.get()
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            log_service.unsubscribe(novel_id, q)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

### Agent instrumentation

In `NovelDirector.advance()` and each agent's main method, add:
```python
from novel_dev.services.log_service import log_service

log_service.add_log(novel_id, "NovelDirector", f"Transitioning from {current} to {next_phase}")
```

And in each agent (e.g., `VolumePlannerAgent.plan()`):
```python
log_service.add_log(novel_id, "VolumePlannerAgent", "开始生成分卷规划...")
# ... after generation ...
log_service.add_log(novel_id, "VolumePlannerAgent", f"分卷规划生成完成: {plan.title}, {plan.total_chapters}章")
```

### Frontend consumption (`useRealtimeLog.js`)

```javascript
import { ref, onMounted, onUnmounted } from 'vue'

export function useRealtimeLog(novelId) {
  const logs = ref([])
  const connected = ref(false)
  let es = null

  const connect = () => {
    if (es) return
    es = new EventSource(`/api/novels/${novelId.value}/logs/stream`)
    es.onopen = () => { connected.value = true }
    es.onmessage = (e) => {
      const entry = JSON.parse(e.data)
      logs.value.push(entry)
      if (logs.value.length > 500) logs.value.shift()
    }
    es.onerror = () => { connected.value = false }
  }

  const disconnect = () => {
    es?.close()
    es = null
    connected.value = false
  }

  onMounted(connect)
  onUnmounted(disconnect)

  return { logs, connected, connect, disconnect }
}
```

---

## 12. Spec Self-Review

**Placeholder scan:** No TBD, TODO, or incomplete sections. All code is concrete.

**Internal consistency:**
- Pinia store state names match API response structures ✓
- Router paths match sidebar menu items ✓
- Component names match view imports ✓
- Dark mode strategy (`class`) used consistently in Tailwind config and useDarkMode ✓

**Scope check:** This is focused on frontend rebuild + one SSE endpoint. It does NOT include:
- Backend business logic changes (agents, repositories)
- Database schema changes (all already exist)
- New API CRUD for entities/timelines (read-only as existing)

**Ambiguity check:**
- Diff highlighting: explicitly "no diff for V1, side-by-side only"
- Element Plus + Tailwind: explicit CSS var sync strategy
- Development vs production serving: explicit `dist/` detection
- Log buffer size: explicit 500 entries per novel

---

## 13. Testing Strategy

### Frontend (manual)
1. `npm install && npm run dev` — verify dev server starts, proxy works
2. Select novel → verify dashboard renders with data
3. Toggle dark mode → verify all views switch, Element Plus components adapt
4. Advance pipeline → verify ActionPipeline step highlighting updates
5. Reviewed chapter → verify ScoreRadar renders 5 axes
6. Entity view → verify graph loads nodes/edges, click/drag/zoom works
7. Chapter list → verify Gantt chart shows colored bars
8. RealtimeLog → verify SSE connects, logs appear with colored prefixes

### Backend
1. `GET /api/novels/{id}/logs/stream` — verify SSE headers, replay existing buffer
2. LogService — verify ring buffer eviction at 500 entries, multiple subscribers receive same events
3. Agent instrumentation — verify `add_log` calls exist in director and key agents
