<template>
  <div v-if="!store.novelId" class="text-center py-20 text-gray-400">请从侧边栏选择或输入一个小说ID</div>
  <div v-else-if="loading" class="text-center py-10">加载中...</div>
  <div v-else-if="!chapter" class="text-center py-10 text-gray-400">章节未找到</div>
  <div v-else class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-bold">{{ chapter.title }}</h2>
      <el-button size="small" @click="$router.push('/chapters')">返回列表</el-button>
    </div>
    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <div class="flex items-center gap-4 text-sm text-gray-500 dark:text-gray-400">
        <el-tag :type="statusType(chapter.status)" size="small">{{ chapter.status }}</el-tag>
        <el-tag :type="qualityType(quality?.quality_status)" size="small">{{ qualityLabel(quality?.quality_status) }}</el-tag>
        <span>草稿: {{ wc(chapter.raw_draft) }}字</span>
        <span>润色: {{ wc(chapter.polished_text) }}字</span>
        <span>最终分: {{ quality?.final_review_score ?? '-' }}</span>
      </div>
      <div v-if="qualityItems.length" class="mt-3 space-y-1 text-sm text-gray-600 dark:text-gray-300">
        <div v-for="item in qualityItems" :key="`${item.code}-${item.message}`">
          {{ item.message }}
        </div>
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
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getChapterQuality, getChapterText } from '@/api.js'
import { useNovelStore } from '@/stores/novel.js'

const route = useRoute()
const store = useNovelStore()
const chapter = ref(null)
const quality = ref(null)
const loading = ref(true)
const qualityItems = computed(() => [
  ...((quality.value?.quality_reasons?.blocking_items) || []),
  ...((quality.value?.quality_reasons?.warning_items) || []),
])

async function fetchIfReady() {
  if (!store.novelId) return
  loading.value = true
  try {
    const [text, qualityResult] = await Promise.all([
      getChapterText(store.novelId, route.params.chapterId),
      getChapterQuality(store.novelId, route.params.chapterId),
    ])
    chapter.value = text
    quality.value = qualityResult
  } catch {
    chapter.value = null
    quality.value = null
  }
  finally { loading.value = false }
}

onMounted(fetchIfReady)
watch(() => store.novelId, fetchIfReady)

function wc(t) { return t ? t.replace(/\s/g, '').length : 0 }
function statusType(s) { return { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }[s] || 'info' }
function qualityType(s) { return { pass: 'success', warn: 'warning', block: 'danger', unchecked: 'info' }[s] || 'info' }
function qualityLabel(s) {
  return {
    pass: '通过',
    warn: '告警',
    block: '阻断',
    unchecked: '未检查',
  }[s] || '未检查'
}
function copy(t) { if (t) { navigator.clipboard.writeText(t); ElMessage.success('已复制') } }
</script>
