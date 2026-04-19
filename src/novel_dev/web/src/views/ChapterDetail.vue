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
        <span>草稿: {{ wc(chapter.raw_draft) }}字</span>
        <span>润色: {{ wc(chapter.polished_text) }}字</span>
      </div>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="flex items-center justify-between mb-2"><h3 class="font-bold">草稿原文</h3><el-button size="small" @click="copy(chapter.raw_draft)">复制</el-button></div>
        <div class="whitespace-pre-wrap text-sm leading-relaxed max-h-[60vh] overflow-y-auto">{{ chapter.raw_draft || '无草稿' }}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div class="flex items-center justify-between mb-2"><h3 class="font-bold">润色后正文</h3><el-button size="small" @click="copy(chapter.polished_text)">复制</el-button></div>
        <div class="whitespace-pre-wrap text-sm leading-relaxed max-h-[60vh] overflow-y-auto">{{ chapter.polished_text || '未润色' }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getChapterText } from '@/api.js'
import { useNovelStore } from '@/stores/novel.js'

const route = useRoute()
const store = useNovelStore()
const chapter = ref(null)
const loading = ref(true)

onMounted(async () => {
  try { chapter.value = await getChapterText(store.novelId, route.params.chapterId) } catch { chapter.value = null }
  finally { loading.value = false }
})

function wc(t) { return t ? t.replace(/\s/g, '').length : 0 }
function statusType(s) { return { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }[s] || 'info' }
function copy(t) { if (t) { navigator.clipboard.writeText(t); ElMessage.success('已复制') } }
</script>
