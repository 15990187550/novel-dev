<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">伏笔</h2>
    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />
    <div v-else class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="store.foreshadowings" style="width: 100%">
        <el-table-column prop="content" label="内容" show-overflow-tooltip />
        <el-table-column prop="回收状态" label="回收状态" width="100">
          <template #default="{ row }"><el-tag :type="row.回收状态 === 'recovered' ? 'success' : 'warning'" size="small">{{ row.回收状态 }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="埋下_chapter_id" label="埋下章节" width="120" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
const store = useNovelStore()

function fetchIfReady() {
  if (store.novelId) store.fetchForeshadowings()
}

onMounted(fetchIfReady)
watch(() => store.novelId, fetchIfReady)
</script>
