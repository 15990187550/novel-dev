<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">卷规划</h2>
    <div v-if="!store.volumePlan" class="text-center py-10 text-gray-400">暂无卷规划数据</div>
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
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { useNovelStore } from '@/stores/novel.js'
const store = useNovelStore()
</script>
