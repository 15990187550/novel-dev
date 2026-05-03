<template>
  <div class="entity-tree surface-card flex h-full min-h-0 flex-col overflow-hidden p-4">
    <div class="space-y-2 shrink-0">
      <div class="flex items-center justify-between gap-2">
        <h3 class="font-bold">目录</h3>
        <span class="entity-tree__meta text-xs">共 {{ totalCount }} 个实体</span>
      </div>
      <el-input
        class="entity-tree__search"
        :model-value="searchQuery"
        clearable
        placeholder="搜索实体、别名、关系"
        @update:model-value="emit('update:searchQuery', $event)"
        @keyup.enter="emit('search')"
        @clear="emit('reset')"
      >
        <template #append>
          <el-button :loading="loading" @click="emit('search')">搜索</el-button>
        </template>
      </el-input>
      <div class="entity-tree__meta flex flex-wrap gap-2 text-xs">
        <span>树节点 {{ treeNodeCount }}</span>
        <span v-if="searchQuery">搜索中保留当前树结构</span>
      </div>
    </div>

    <div
      v-if="nodes.length"
      v-loading="loading"
      class="entity-tree__scroll min-h-0 flex-1 overflow-auto pr-1"
      data-testid="entity-tree-scroll"
    >
      <el-tree
        :data="nodes"
        :props="treeProps"
        node-key="id"
        :current-node-key="selectedNodeId"
        :default-expanded-keys="defaultExpandedKeys"
        highlight-current
        :expand-on-click-node="false"
        @node-click="handleNodeClick"
      >
        <template #default="{ data }">
          <div class="flex w-full items-start justify-between gap-3 py-1">
            <div class="min-w-0 flex-1 space-y-0.5">
              <div :class="nodeLabelClass(data)">{{ data.label }}</div>
              <div v-if="nodeSubtitle(data)" class="entity-tree__meta truncate text-xs">
                {{ nodeSubtitle(data) }}
              </div>
            </div>
            <div class="flex shrink-0 flex-wrap items-center justify-end gap-1 max-w-[7.5rem]">
              <el-tag v-if="nodeBadge(data)" class="entity-tree__badge" size="small" type="info">{{ nodeBadge(data) }}</el-tag>
              <el-tag v-if="nodeHint(data)" class="entity-tree__badge entity-tree__badge--warning" size="small" type="warning">{{ nodeHint(data) }}</el-tag>
            </div>
          </div>
        </template>
      </el-tree>
    </div>

    <el-empty v-else description="暂无实体树数据" />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  searchQuery: { type: String, default: '' },
  selectedNodeId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  totalCount: { type: Number, default: 0 },
  treeNodeCount: { type: Number, default: 0 },
})

const emit = defineEmits(['update:searchQuery', 'search', 'reset', 'select'])

const treeProps = { label: 'label', children: 'children' }
const defaultExpandedKeys = computed(() =>
  props.nodes
    .filter(node => node.nodeType === 'scope' || node.nodeType === 'category')
    .map(node => node.id)
)

function handleNodeClick(nodeData) {
  emit('select', nodeData)
}

function nodeLabelClass(node) {
  if (node.nodeType === 'entity') return 'truncate text-sm font-medium leading-5'
  return 'truncate text-sm font-semibold leading-5'
}

function nodeBadge(node) {
  if (node.nodeType === 'scope') return `${node.entityCount || 0} 个实体`
  if (node.nodeType === 'category') return `${node.entityCount || 0} 个实体`
  if (node.nodeType === 'group') return `${node.entityCount || (node.children || []).length} 个实体`
  return node.entityId ? '实体' : ''
}

function nodeHint(node) {
  if ((node.nodeType === 'scope' || node.nodeType === 'category' || node.nodeType === 'group') && node.needsReviewCount) {
    return `待确认 ${node.needsReviewCount}`
  }
  if (node.nodeType === 'entity' && node.data?.classification_status === 'manual_override') return '覆盖'
  if (node.nodeType === 'entity' && node.data?.system_needs_review) return '待确认'
  return ''
}

function nodeSubtitle(node) {
  if (node.nodeType === 'scope') return node.scopeType === 'domain' ? '局部规则域' : '全局资料'
  if (node.nodeType === 'category') return `一级分类 · ${(node.children || []).length} 个分组`
  if (node.nodeType === 'group') return '二级分组'
  if (node.nodeType === 'entity') return ''
  return ''
}
</script>

<style scoped>
.entity-tree {
  background: var(--entities-panel-bg);
  border-color: var(--entities-panel-border);
}

.entity-tree__scroll {
  margin-top: 0.75rem;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.entity-tree__meta {
  color: var(--entities-text-muted);
}

.entity-tree__search :deep(.el-input__wrapper) {
  background: var(--entities-panel-bg-soft);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}

.entity-tree__search :deep(.el-input__inner),
.entity-tree__search :deep(.el-input__wrapper input) {
  color: var(--entities-text);
}

.entity-tree__search :deep(.el-input-group__append) {
  background: var(--entities-panel-bg);
  color: var(--entities-text);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}

.entity-tree :deep(.el-tree) {
  --el-tree-node-hover-bg-color: var(--entities-panel-bg-soft);
  --el-tree-text-color: var(--entities-text);
  background: transparent;
  color: var(--entities-text);
}

.entity-tree :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: color-mix(in srgb, var(--entities-accent) 14%, var(--entities-panel-bg-soft));
  box-shadow: inset 0 0 0 1px var(--entities-panel-border-strong);
}

.entity-tree :deep(.el-tree-node__content) {
  min-height: 2.75rem;
  align-items: flex-start;
}

.entity-tree :deep(.el-tree-node__expand-icon) {
  margin-top: 0.45rem;
}

.entity-tree :deep(.el-tag.entity-tree__badge) {
  border-color: var(--entities-chip-border);
  background: var(--entities-chip-bg);
  color: var(--entities-text);
}

.entity-tree :deep(.el-tag.entity-tree__badge--warning) {
  border-color: color-mix(in srgb, var(--entities-warning) 34%, transparent);
  background: var(--entities-warning-soft);
  color: var(--entities-warning);
}
</style>
