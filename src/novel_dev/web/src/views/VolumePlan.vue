<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-bold">总纲与卷规划</h2>
      <el-button v-if="store.synopsisData" size="small" @click="openEditor">调整大纲</el-button>
    </div>

    <div v-if="!store.novelId" class="text-center py-10 text-gray-400">请先选择小说</div>

    <template v-else>
      <div v-if="store.synopsisData" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700 space-y-4">
        <div>
          <div class="text-sm text-gray-500 dark:text-gray-400">完整大纲</div>
          <h3 class="font-bold text-2xl mt-1">{{ store.synopsisData.title }}</h3>
          <p class="text-gray-600 dark:text-gray-300 mt-2 whitespace-pre-wrap">{{ store.synopsisData.logline }}</p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          <div class="rounded-lg bg-gray-50 dark:bg-gray-900 p-3">
            <div class="text-gray-500 dark:text-gray-400 mb-1">核心冲突</div>
            <div class="whitespace-pre-wrap">{{ store.synopsisData.core_conflict }}</div>
          </div>
          <div class="rounded-lg bg-gray-50 dark:bg-gray-900 p-3">
            <div class="text-gray-500 dark:text-gray-400 mb-1">预估卷数</div>
            <div>{{ store.synopsisData.estimated_volumes }}</div>
          </div>
          <div class="rounded-lg bg-gray-50 dark:bg-gray-900 p-3">
            <div class="text-gray-500 dark:text-gray-400 mb-1">预估总章数</div>
            <div>{{ store.synopsisData.estimated_total_chapters }}</div>
          </div>
        </div>

        <div v-if="store.synopsisData.themes?.length">
          <div class="font-semibold mb-2">主题</div>
          <div class="flex flex-wrap gap-2">
            <el-tag v-for="theme in store.synopsisData.themes" :key="theme">{{ theme }}</el-tag>
          </div>
        </div>

        <div v-if="store.synopsisData.character_arcs?.length">
          <div class="font-semibold mb-2">人物弧光</div>
          <div class="grid grid-cols-1 xl:grid-cols-2 gap-3">
            <div v-for="arc in store.synopsisData.character_arcs" :key="arc.name" class="rounded-lg border border-gray-200 dark:border-gray-700 p-3">
              <div class="font-medium">{{ arc.name }}</div>
              <p class="text-sm text-gray-600 dark:text-gray-300 mt-1 whitespace-pre-wrap">{{ arc.arc_summary }}</p>
              <ul class="list-disc pl-5 text-sm text-gray-600 dark:text-gray-300 mt-2 space-y-1">
                <li v-for="point in arc.key_turning_points" :key="point">{{ point }}</li>
              </ul>
            </div>
          </div>
        </div>

        <div v-if="store.synopsisData.milestones?.length">
          <div class="font-semibold mb-2">剧情里程碑</div>
          <el-timeline>
            <el-timeline-item v-for="ms in store.synopsisData.milestones" :key="`${ms.act}-${ms.summary}`">
              <div class="font-medium">{{ ms.act }}</div>
              <div class="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{{ ms.summary }}</div>
              <div v-if="ms.climax_event" class="text-sm mt-1 text-blue-600 dark:text-blue-400">高潮：{{ ms.climax_event }}</div>
            </el-timeline-item>
          </el-timeline>
        </div>

        <el-collapse>
          <el-collapse-item title="原始大纲文本" name="content">
            <pre class="text-sm whitespace-pre-wrap overflow-auto max-h-96 bg-gray-50 dark:bg-gray-900 rounded-lg p-3">{{ store.synopsisContent }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div v-else class="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-200 dark:border-gray-700 text-gray-400">
        暂无完整大纲数据
      </div>

      <div v-if="store.volumePlan" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold text-lg">{{ store.volumePlan.title }}</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400 mt-1 whitespace-pre-wrap">{{ store.volumePlan.summary }}</p>
        <div class="flex gap-4 mt-2 text-sm text-gray-500">
          <span>章节数: {{ store.volumePlan.total_chapters }}</span>
          <span>估算字数: {{ store.volumePlan.estimated_total_words }}</span>
        </div>
        <el-timeline class="mt-4">
          <el-timeline-item v-for="ch in store.volumePlan.chapters" :key="ch.chapter_id">
            <div class="font-medium">{{ ch.title }}（第{{ ch.chapter_number }}章）</div>
            <div class="text-sm text-gray-500 dark:text-gray-400 whitespace-pre-wrap">{{ ch.summary }}</div>
            <div class="flex flex-wrap gap-2 mt-2">
              <el-tag size="small" type="info">目标: {{ ch.target_word_count }}</el-tag>
              <el-tag size="small">{{ ch.target_mood }}</el-tag>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
      <div v-else class="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-200 dark:border-gray-700 text-gray-400">
        暂无卷规划数据
      </div>
    </template>

    <el-dialog v-model="editorVisible" title="调整大纲" width="960px" :close-on-click-modal="false">
      <div class="space-y-3">
        <div class="text-sm text-gray-500">编辑 `SynopsisData` JSON，保存后会覆盖当前大纲并刷新页面。</div>
        <el-input v-model="draftSynopsis" type="textarea" :rows="24" />
      </div>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveSynopsis">保存大纲</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const editorVisible = ref(false)
const saving = ref(false)
const draftSynopsis = ref('')

watch(
  () => store.synopsisData,
  (value) => {
    draftSynopsis.value = value ? JSON.stringify(value, null, 2) : ''
  },
  { immediate: true }
)

function openEditor() {
  draftSynopsis.value = store.synopsisData ? JSON.stringify(store.synopsisData, null, 2) : ''
  editorVisible.value = true
}

async function saveSynopsis() {
  try {
    JSON.parse(draftSynopsis.value)
  } catch (error) {
    ElMessage.error(`JSON 格式不合法: ${error.message}`)
    return
  }

  saving.value = true
  try {
    await store.saveSynopsis(draftSynopsis.value)
    editorVisible.value = false
    ElMessage.success('大纲已更新')
  } finally {
    saving.value = false
  }
}
</script>
