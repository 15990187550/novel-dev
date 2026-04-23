<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">地点</h2>
    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />
    <div v-else class="locations-table-panel overflow-hidden rounded-xl">
      <el-table :data="store.spacelines" row-key="id" :tree-props="{ children: 'children' }" class="locations-table">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="narrative" label="描述" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
const store = useNovelStore()

function fetchIfReady() {
  if (store.novelId) store.fetchSpacelines()
}

onMounted(fetchIfReady)
watch(() => store.novelId, fetchIfReady)
</script>

<style scoped>
.locations-table-panel {
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-soft);
}

.locations-table {
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

.locations-table :deep(.el-table__inner-wrapper::before),
.locations-table :deep(.el-table::before) {
  display: none;
}

.locations-table :deep(th.el-table__cell) {
  background: var(--app-surface-soft);
  font-weight: 700;
}

.locations-table :deep(td.el-table__cell),
.locations-table :deep(tr) {
  background: transparent;
}

.locations-table :deep(.el-table__empty-block),
.locations-table :deep(.el-table__empty-text) {
  background: transparent;
  color: var(--app-text-muted);
}
</style>
