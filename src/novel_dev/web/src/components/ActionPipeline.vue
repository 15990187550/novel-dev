<template>
  <div class="space-y-3">
    <!-- 脑暴区域 -->
    <div v-if="store.novelState.current_phase === 'brainstorming'" class="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4 border border-blue-200 dark:border-blue-800">
      <div class="flex items-center justify-between mb-3">
        <h4 class="font-medium text-blue-700 dark:text-blue-300">脑暴阶段</h4>
        <el-tag type="info" size="small">导出到 Claude Code</el-tag>
      </div>
      <div class="flex flex-wrap items-center gap-2 mb-3">
        <el-button type="primary" :loading="store.loadingActions['brainstorm']" @click="store.executeAction('brainstorm')">
          AI 脑暴
        </el-button>
        <el-button @click="exportPrompt" :loading="exporting">
          <el-icon class="mr-1"><Document /></el-icon>
          复制 Prompt
        </el-button>
      </div>
      <div v-if="promptExported" class="mt-3">
        <el-input
          v-model="exportedPrompt"
          type="textarea"
          :rows="6"
          readonly
          placeholder="导出的 Prompt 将显示在这里"
        />
        <div class="flex items-center gap-2 mt-2">
          <el-button type="primary" size="small" @click="copyPrompt">
            <el-icon class="mr-1"><CopyDocument /></el-icon>
            复制到剪贴板
          </el-button>
          <span v-if="copied" class="text-green-600 text-sm">已复制!</span>
        </div>
      </div>

      <!-- 导入 Claude Code 生成的结果 -->
      <div class="mt-4 pt-4 border-t border-blue-200 dark:border-blue-700">
        <div class="flex items-center justify-between mb-2">
          <h5 class="text-sm font-medium text-blue-600 dark:text-blue-400">导入 Claude Code 生成的结果</h5>
          <el-tag type="warning" size="small">粘贴 JSON</el-tag>
        </div>
        <el-input
          v-model="importJson"
          type="textarea"
          :rows="6"
          placeholder='粘贴 Claude Code 生成的内容（Markdown + JSON 格式）。
Claude Code 会先输出给人看的 Markdown，再用 JSON 块输出供系统导入。'
        />
        <div class="flex items-center gap-2 mt-2">
          <el-button type="success" size="small" @click="doImport" :loading="importing">
            <el-icon class="mr-1"><Upload /></el-icon>
            导入 Synopsis
          </el-button>
          <span v-if="importSuccess" class="text-green-600 text-sm">导入成功!</span>
          <span v-if="importError" class="text-red-600 text-sm">{{ importError }}</span>
        </div>
      </div>
    </div>

    <!-- 流水线按钮 -->
    <div class="flex flex-wrap items-center gap-2">
      <template v-for="(step, idx) in pipelineSteps" :key="step.key">
        <el-button
          v-if="step.key !== 'brainstorm' || store.novelState.current_phase !== 'brainstorming'"
          :type="stepType(step, idx)"
          :loading="store.loadingActions[step.key]"
          :disabled="!step.enabled"
          size="default"
          @click="store.executeAction(step.key)"
        >
          <el-icon v-if="stepDone(idx)" class="mr-1"><Check /></el-icon>
          {{ step.label }}
        </el-button>
        <el-icon v-if="idx < pipelineSteps.length - 1" class="text-gray-300 dark:text-gray-600"><ArrowRight /></el-icon>
      </template>
      <el-button :loading="store.loadingActions['export']" @click="store.executeAction('export')">导出小说</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { importSynopsis } from '@/api.js'
import { ElMessage } from 'element-plus'

const store = useNovelStore()
const phaseOrder = ['brainstorming', 'volume_planning', 'context_preparation', 'drafting', 'reviewing', 'editing', 'fast_reviewing', 'librarian', 'completed']

const pipelineSteps = computed(() => [
  { key: 'brainstorm', label: '脑暴', enabled: store.canBrainstorm, phase: 'brainstorming' },
  { key: 'volume_plan', label: '分卷', enabled: store.canVolumePlan, phase: 'volume_planning' },
  { key: 'context', label: '上下文', enabled: store.canContext, phase: 'context_preparation' },
  { key: 'draft', label: '草稿', enabled: store.canDraft, phase: 'drafting' },
  { key: 'advance', label: '推进', enabled: store.canAdvance, phase: 'reviewing' },
  { key: 'librarian', label: '归档', enabled: store.canLibrarian, phase: 'librarian' },
])

const currentIdx = computed(() => phaseOrder.indexOf(store.novelState.current_phase))

function stepDone(idx) {
  const pi = phaseOrder.indexOf(pipelineSteps.value[idx].phase)
  return pi < currentIdx.value
}

function stepType(step, idx) {
  const pi = phaseOrder.indexOf(step.phase)
  if (pi === currentIdx.value) return 'primary'
  if (pi < currentIdx.value) return 'success'
  return 'default'
}

// Prompt 导出
const exporting = ref(false)
const promptExported = ref(false)
const exportedPrompt = ref('')
const copied = ref(false)

// Synopsis 导入
const importJson = ref('')
const importing = ref(false)
const importSuccess = ref(false)
const importError = ref('')

async function exportPrompt() {
  if (!store.novelId) return
  exporting.value = true
  try {
    const response = await fetch(`/api/novels/${store.novelId}/brainstorm/prompt`)
    const data = await response.json()
    exportedPrompt.value = data.prompt || ''
    promptExported.value = true
    copied.value = false
  } catch (e) {
    ElMessage.error('导出 Prompt 失败: ' + e.message)
  } finally {
    exporting.value = false
  }
}

async function copyPrompt() {
  try {
    await navigator.clipboard.writeText(exportedPrompt.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch (e) {
    ElMessage.error('复制失败')
  }
}

async function doImport() {
  if (!importJson.value.trim()) {
    importError.value = '请先粘贴内容'
    return
  }
  importing.value = true
  importSuccess.value = false
  importError.value = ''
  try {
    await importSynopsis(store.novelId, importJson.value)
    importSuccess.value = true
    importJson.value = ''
    await store.loadNovel(store.novelId)
    setTimeout(() => { importSuccess.value = false }, 3000)
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '导入失败'
    importError.value = msg
    // 保留用户输入以便修正重试
  } finally {
    importing.value = false
  }
}
</script>