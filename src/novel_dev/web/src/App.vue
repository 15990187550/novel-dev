<template>
  <div class="h-screen flex bg-gray-50 dark:bg-gray-900">
    <aside class="w-64 border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col">
      <div class="p-4 border-b border-gray-200 dark:border-gray-700">
        <h1 class="font-bold text-lg text-gray-900 dark:text-gray-100">Novel Dev</h1>
      </div>
      <nav class="flex-1 p-2">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          class="block px-3 py-2 rounded-lg mb-1 text-sm hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
        >
          {{ item.label }}
        </router-link>
      </nav>
    </aside>
    <main class="flex-1 flex flex-col overflow-hidden">
      <header class="h-14 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center px-4">
        <span class="text-sm text-gray-500">{{ novelStore.currentPhaseLabel }}</span>
      </header>
      <div class="flex-1 overflow-auto p-4">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { useNovelStore } from '@/stores/novel.js'

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
