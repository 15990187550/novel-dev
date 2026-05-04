<template>
  <div class="app-shell">
    <div class="app-shell__ambient app-shell__ambient--one"></div>
    <div class="app-shell__ambient app-shell__ambient--two"></div>

    <div class="relative z-10 min-h-screen p-3 sm:p-4 lg:p-5">
      <div class="mx-auto flex h-[calc(100vh-1.5rem)] max-w-[1600px] flex-col gap-4 lg:flex-row">
        <aside class="app-sidebar w-full min-h-0 overflow-auto lg:w-[19rem] lg:shrink-0">
          <div class="app-sidebar__brand">
            <p class="app-sidebar__eyebrow">Story Engine</p>
            <h1 class="app-sidebar__title">Novel Dev</h1>
            <p class="app-sidebar__description">
              把设定、卷纲、正文和知识库统一收敛在一个工作台里。
            </p>
          </div>

          <div class="app-sidebar__selector surface-card surface-card--soft">
            <NovelSelector />
          </div>

          <nav class="app-sidebar__nav">
            <router-link
              v-for="item in menuItems"
              :key="item.path"
              :to="item.path"
              class="app-nav-link"
              :class="{ 'is-active': isMenuActive(item.path) }"
            >
              <span class="app-nav-link__label">{{ item.label }}</span>
              <span class="app-nav-link__detail">{{ item.detail }}</span>
            </router-link>
          </nav>

          <div class="app-sidebar__footer">
            当前界面重点是让信息优先级更清楚，减少“所有模块都一样重”的视觉噪音。
          </div>
        </aside>

        <main class="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          <header class="app-header surface-card">
            <div class="min-w-0 flex-1">
              <p class="page-header__eyebrow">{{ currentMenu.eyebrow }}</p>
              <h2 class="app-header__title">{{ currentMenu.label }}</h2>
              <p class="app-header__description">{{ currentMenu.detail }}</p>
            </div>

            <div class="flex flex-wrap items-center justify-end gap-2">
              <span class="app-chip app-chip--editable">
                {{ novelStore.novelTitle || '未选择小说' }}
                <button
                  v-if="novelStore.novelId"
                  type="button"
                  class="app-chip__edit"
                  title="修改小说名称"
                  @click="renameNovel"
                >
                  修改
                </button>
              </span>
              <span v-if="novelStore.currentPhaseLabel" class="app-chip">
                {{ novelStore.currentPhaseLabel }}
              </span>
              <span
                v-if="novelStore.novelState.current_volume_id"
                class="app-chip"
              >
                {{ novelStore.novelState.current_volume_id }} / {{ novelStore.novelState.current_chapter_id || '未进入章节' }}
              </span>
              <button
                v-if="novelStore.shouldShowStopFlow"
                type="button"
                class="app-stop-flow-button"
                :disabled="novelStore.stoppingFlow"
                @click="novelStore.stopCurrentFlow()"
              >
                {{ novelStore.stoppingFlow ? '停止中...' : novelStore.stopFlowLabel }}
              </button>
              <DarkModeToggle />
            </div>
          </header>

          <div class="surface-card surface-card--main">
            <div class="h-full overflow-auto px-4 py-4 sm:px-6 sm:py-5 lg:px-8">
              <router-view v-slot="{ Component }">
                <div :key="route.fullPath" class="page-shell">
                  <component :is="Component" />
                </div>
              </router-view>
            </div>
          </div>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useNovelStore } from '@/stores/novel.js'
import { useRealtimeLog } from '@/composables/useRealtimeLog.js'
import NovelSelector from '@/components/NovelSelector.vue'
import DarkModeToggle from '@/components/DarkModeToggle.vue'

const route = useRoute()
const novelStore = useNovelStore()
const novelIdRef = computed(() => novelStore.novelId)
const { logs: appLogs } = useRealtimeLog(novelIdRef)

watch(appLogs, (logs) => {
  novelStore.syncFlowActivityFromLogs(logs)
}, { deep: true })

const menuItems = [
  { path: '/dashboard', label: '仪表盘', eyebrow: 'Overview', detail: '总览项目状态、风险、建议动作与实时更新。' },
  { path: '/settings', label: '设定工作台', eyebrow: 'Settings', detail: '从想法生成 AI 设定会话，沉淀待审核设定。' },
  { path: '/documents', label: '设定与文风', eyebrow: 'Knowledge Base', detail: '管理资料导入、审核和已生效的设定与文风档案。' },
  { path: '/volume-plan', label: '大纲规划', eyebrow: 'Outline Workbench', detail: '围绕总纲和卷纲持续迭代，沉淀工作区草稿。' },
  { path: '/chapters', label: '章节列表', eyebrow: 'Chapters', detail: '查看章节状态、推进节奏和当前创作进度。' },
  { path: '/entities', label: '实体百科', eyebrow: 'Entities', detail: '统一管理角色、组织、地点与实体关系。' },
  { path: '/timeline', label: '时间线', eyebrow: 'Timeline', detail: '检查世界事件与章节推进是否保持一致。' },
  { path: '/locations', label: '地点', eyebrow: 'Locations', detail: '按地点维度审查空间设定与出场信息。' },
  { path: '/foreshadowings', label: '伏笔', eyebrow: 'Foreshadowing', detail: '追踪伏笔布置、兑现进度和遗漏风险。' },
  { path: '/config', label: '模型配置', eyebrow: 'Models', detail: '调整模型、驱动与运行时参数。' },
  { path: '/logs', label: '实时日志', eyebrow: 'Observability', detail: '查看系统实时输出与任务执行状态。' },
]

const currentMenu = computed(() => (
  menuItems.find((item) => isMenuActive(item.path)) || menuItems[0]
))

function isMenuActive(path) {
  return path === '/dashboard'
    ? route.path === path
    : route.path === path || route.path.startsWith(`${path}/`)
}

async function renameNovel() {
  if (!novelStore.novelId) return
  try {
    const { value } = await ElMessageBox.prompt('请输入新的小说名称', '修改小说名称', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: novelStore.novelTitle,
      inputValidator: (value) => Boolean(String(value || '').trim()) || '小说名称不能为空',
    })
    const title = String(value || '').trim()
    if (!title || title === novelStore.novelTitle) return
    await novelStore.updateNovelTitle(title)
    ElMessage.success('小说名称已更新')
  } catch {
    // User cancelled.
  }
}
</script>

<style scoped>
.app-chip--editable {
  gap: 0.45rem;
  padding-right: 0.35rem;
}

.app-chip__edit {
  border: 1px solid rgba(15, 23, 42, 0.1);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  padding: 0.12rem 0.45rem;
  font-size: 0.68rem;
  font-weight: 700;
  color: #475569;
  transition: border-color 0.16s ease, color 0.16s ease, background 0.16s ease;
}

.app-chip__edit:hover {
  border-color: rgba(20, 184, 166, 0.45);
  background: rgba(240, 253, 250, 0.9);
  color: #0f766e;
}
</style>
