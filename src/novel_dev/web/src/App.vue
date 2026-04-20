<template>
  <div class="h-screen flex bg-gray-50 dark:bg-gray-900">
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
    <main class="flex-1 flex flex-col overflow-hidden">
      <header class="h-14 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center justify-between px-4">
        <div class="flex items-center gap-3">
          <span class="font-medium text-gray-900 dark:text-gray-100">{{ novelStore.novelTitle }}</span>
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
