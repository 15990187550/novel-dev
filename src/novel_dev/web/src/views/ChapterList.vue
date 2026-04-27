<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">章节列表</h2>
    <section class="chapter-list-panel continuous-writing-card rounded-xl p-4">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="eyebrow">CONTINUOUS WRITING</div>
          <h3 class="mt-1 text-lg font-bold">持续写作</h3>
          <p class="mt-1 text-sm text-[var(--app-text-muted)]">
            从当前章节开始连续生成多章，后端会按章节流程依次执行上下文、草稿、审核与归档。
          </p>
          <p v-if="!store.canAutoRunChapter" class="mt-2 text-xs text-[var(--app-text-muted)]">
            当前阶段：{{ store.currentPhaseLabel }}，进入章节生成流程后可启动持续写作。
          </p>
        </div>
        <div class="continuous-writing-controls">
          <label class="control-field">
            <span>连续章数</span>
            <el-input-number v-model="autoRunCount" :min="1" :max="200" size="small" />
          </label>
          <label class="control-field">
            <span>卷末停止</span>
            <el-switch v-model="stopAtVolumeEnd" />
          </label>
          <div class="flex flex-wrap gap-2">
            <el-button
              type="primary"
              :loading="store.loadingActions['auto_chapter']"
              :disabled="!store.canAutoRunChapter || hasRunningAutoRun"
              @click="startContinuousWriting"
            >
              开始持续写作
            </el-button>
            <el-button :disabled="!store.autoRunJob?.job_id" @click="refreshAutoRun">
              刷新任务状态
            </el-button>
          </div>
        </div>
      </div>
      <div v-if="store.autoRunJob || store.autoRunLastResult" class="auto-run-status mt-4">
        <span v-if="store.autoRunJob">任务 {{ store.autoRunJob.job_id || '-' }}：{{ jobStatusLabel }}</span>
        <span v-if="store.autoRunLastResult?.completed_chapters?.length">
          已完成 {{ store.autoRunLastResult.completed_chapters.length }} 章
        </span>
        <span v-if="store.autoRunLastResult?.stopped_reason">
          停止原因：{{ store.autoRunLastResult.stopped_reason }}
        </span>
        <span v-if="store.autoRunLastResult?.error" class="text-red-500">
          错误：{{ store.autoRunLastResult.error }}
        </span>
      </div>
    </section>
    <div class="chapter-list-panel rounded-xl p-4">
      <ChapterProgressGantt :chapters="store.chapters" />
    </div>
    <div class="chapter-list-panel overflow-hidden rounded-xl">
      <el-table :data="store.chapters" style="width: 100%" class="chapter-list-table app-themed-table">
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
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '@/stores/novel.js'
import ChapterProgressGantt from '@/components/ChapterProgressGantt.vue'
const store = useNovelStore()

const autoRunCount = ref(5)
const stopAtVolumeEnd = ref(true)
const runningStatuses = ['queued', 'running']
const hasRunningAutoRun = computed(() => runningStatuses.includes(store.autoRunJob?.status))
const jobStatusLabel = computed(() => ({
  queued: '排队中',
  running: '生成中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
}[store.autoRunJob?.status] || store.autoRunJob?.status || '-'))

function statusType(s) { return { pending: 'info', drafted: 'primary', edited: 'success', archived: 'danger' }[s] || 'info' }

async function startContinuousWriting() {
  try {
    await store.executeAction('auto_chapter', {
      max_chapters: autoRunCount.value,
      stop_at_volume_end: stopAtVolumeEnd.value,
    })
    ElMessage.success('持续写作任务已提交')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail?.error || error?.message || '持续写作启动失败')
  }
}

async function refreshAutoRun() {
  try {
    await store.refreshAutoRunJob()
    ElMessage.success('任务状态已刷新')
  } catch (error) {
    ElMessage.error(error?.message || '刷新任务失败')
  }
}
</script>

<style scoped>
.eyebrow {
  color: var(--app-text-muted);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.22em;
}

.chapter-list-panel {
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-soft);
}

.continuous-writing-card {
  position: relative;
  overflow: hidden;
}

.continuous-writing-card::before {
  background:
    radial-gradient(circle at 20% 20%, rgba(28, 122, 124, 0.14), transparent 36%),
    linear-gradient(135deg, rgba(28, 122, 124, 0.08), transparent 42%);
  content: '';
  inset: 0;
  pointer-events: none;
  position: absolute;
}

.continuous-writing-card > * {
  position: relative;
}

.continuous-writing-controls {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.control-field {
  align-items: center;
  color: var(--app-text-soft);
  display: flex;
  font-size: 0.85rem;
  gap: 0.5rem;
}

.auto-run-status {
  align-items: center;
  color: var(--app-text-soft);
  display: flex;
  flex-wrap: wrap;
  font-size: 0.85rem;
  gap: 0.75rem;
}

.chapter-list-table {
  --el-table-border-color: var(--app-border);
  --el-table-border: 1px solid var(--app-border);
  --el-table-header-bg-color: var(--app-surface-soft);
  --el-table-tr-bg-color: transparent;
  --el-table-row-hover-bg-color: var(--app-surface-soft);
  --el-table-bg-color: transparent;
  --el-table-expanded-cell-bg-color: transparent;
  --el-table-header-text-color: var(--app-text-soft);
  --el-table-text-color: var(--app-text);
  --el-fill-color-lighter: var(--app-surface-soft);
  --el-fill-color-blank: transparent;
}

.chapter-list-table :deep(.el-table__inner-wrapper::before),
.chapter-list-table :deep(.el-table::before) {
  display: none;
}

.chapter-list-table :deep(th.el-table__cell) {
  background: var(--app-surface-soft);
  font-weight: 700;
}

.chapter-list-table :deep(td.el-table__cell),
.chapter-list-table :deep(tr) {
  background: transparent;
}

.chapter-list-table :deep(.el-table__empty-block),
.chapter-list-table :deep(.el-table__empty-text) {
  background: transparent;
  color: var(--app-text-muted);
}
</style>
