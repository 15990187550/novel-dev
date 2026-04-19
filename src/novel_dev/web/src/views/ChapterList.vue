<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">章节列表</h2>
    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <ChapterProgressGantt :chapters="store.chapters" />
    </div>
    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="store.chapters" style="width: 100%">
        <el-table-column prop="chapter_number" label="章号" width="70" />
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="word_count" label="字数" width="90" />
        <el-table-column label="进度" width="120">
          <template #default="{ row }">
            <el-progress :percentage="Math.min(Math.round(((row.word_count||0)/(row.target_word_count||3000))*100),100)" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }"><el-button size="small" @click="$router.push(`/chapters/${row.chapter_id}`)">查看</el-button></template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { useNovelStore } from '@/stores/novel.js'
import ChapterProgressGantt from '@/components/ChapterProgressGantt.vue'
const store = useNovelStore()
function statusType(s) { return { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }[s] || 'info' }
</script>
