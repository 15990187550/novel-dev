<template>
  <div v-if="!store.novelId" class="text-center py-20 text-gray-400">请从侧边栏选择或输入一个小说ID</div>
  <div v-else class="space-y-4">
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
        <div class="text-2xl font-bold mt-1">{{ (store.archiveStats.total_word_count || 0).toLocaleString('zh-CN') }}</div>
      </div>
    </div>
    <div v-if="store.currentChapter" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-bold text-lg">当前章节：{{ store.currentChapter.title }}</h3>
        <el-tag :type="statusType(store.currentChapter.status)" size="small">{{ store.currentChapter.status }}</el-tag>
      </div>
      <div class="text-sm text-gray-500 dark:text-gray-400 mb-2">字数：{{ store.currentChapter.word_count || 0 }}</div>
      <ScoreRadar v-if="store.currentChapter.score_breakdown" :scores="store.currentChapter.score_breakdown" />
    </div>
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
function statusType(s) { return { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }[s] || 'info' }
</script>
