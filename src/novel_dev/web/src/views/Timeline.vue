<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">时间线</h2>
    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />
    <div v-else class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <el-timeline>
        <el-timeline-item v-for="t in store.timelines" :key="t.id" :timestamp="`Tick ${t.tick}`">
          {{ t.narrative }}
          <div v-if="t.anchor_chapter_id" class="text-xs text-gray-400 mt-1">关联: {{ t.anchor_chapter_id }}</div>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
const store = useNovelStore()

function fetchIfReady() {
  if (store.novelId) store.fetchTimelines()
}

onMounted(fetchIfReady)
watch(() => store.novelId, fetchIfReady)
</script>
