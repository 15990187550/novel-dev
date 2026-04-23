<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">章节列表</h2>
    <div class="chapter-list-panel rounded-xl p-4">
      <ChapterProgressGantt :chapters="store.chapters" />
    </div>
    <div class="chapter-list-panel overflow-hidden rounded-xl">
      <el-table :data="store.chapters" style="width: 100%" class="chapter-list-table">
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

<style scoped>
.chapter-list-panel {
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-soft);
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
