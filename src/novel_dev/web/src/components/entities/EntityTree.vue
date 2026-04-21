<template>
  <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 space-y-3">
    <div class="space-y-2">
      <div class="flex items-center justify-between gap-2">
        <h3 class="font-bold">目录</h3>
        <span class="text-xs text-gray-500 dark:text-gray-400">共 {{ totalCount }} 个实体</span>
      </div>
      <el-input
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
      <div class="flex flex-wrap gap-2 text-xs text-gray-500 dark:text-gray-400">
        <span>树节点 {{ treeNodeCount }}</span>
        <span v-if="searchQuery">搜索中保留当前树结构</span>
      </div>
    </div>

    <div v-if="nodes.length" v-loading="loading" class="max-h-[70vh] overflow-auto pr-1">
      <el-tree
        :data="nodes"
        :props="treeProps"
        node-key="id"
        :current-node-key="selectedNodeId"
        highlight-current
        default-expand-all
        :expand-on-click-node="false"
        @node-click="handleNodeClick"
      >
        <template #default="{ data }">
          <div class="flex w-full items-center justify-between gap-2 py-0.5">
            <div class="min-w-0">
              <div class="truncate text-sm font-medium">{{ data.label }}</div>
              <div v-if="nodeSubtitle(data)" class="truncate text-xs text-gray-500 dark:text-gray-400">
                {{ nodeSubtitle(data) }}
              </div>
            </div>
            <div class="flex items-center gap-1 shrink-0">
              <el-tag v-if="nodeBadge(data)" size="small" type="info">{{ nodeBadge(data) }}</el-tag>
              <el-tag v-if="nodeHint(data)" size="small" type="warning">{{ nodeHint(data) }}</el-tag>
            </div>
          </div>
        </template>
      </el-tree>
    </div>

    <el-empty v-else description="暂无实体树数据" />
  </div>
</template>

<script setup>
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

function handleNodeClick(nodeData) {
  emit('select', nodeData)
}

function nodeBadge(node) {
  if (node.nodeType === 'category') return `${node.entityCount || 0} 个实体`
  if (node.nodeType === 'group') return `${node.entityCount || (node.children || []).length} 个实体`
  return node.entityId ? '实体' : ''
}

function nodeHint(node) {
  if ((node.nodeType === 'category' || node.nodeType === 'group') && node.needsReviewCount) {
    return `待确认 ${node.needsReviewCount}`
  }
  if (node.nodeType === 'entity' && node.data?.classification_status === 'manual_override') return '覆盖'
  if (node.nodeType === 'entity' && node.data?.system_needs_review) return '待确认'
  return ''
}

function nodeSubtitle(node) {
  if (node.nodeType === 'category') return `一级分类 · ${(node.children || []).length} 个分组`
  if (node.nodeType === 'group') return node.groupSlug ? `二级分组 · ${node.groupSlug}` : '二级分组'
  if (node.nodeType === 'entity') return node.data?.effective_group_name || node.data?.effective_category || node.data?.type || '实体'
  return ''
}
</script>
