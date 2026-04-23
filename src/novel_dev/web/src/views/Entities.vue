<template>
  <div class="entities-page entities-theme space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-xl font-bold">实体百科</h2>
        <p class="entities-page__meta mt-1 text-sm">
          左侧目录用于切换分类、分组和实体，右侧用于查看列表或详情。
        </p>
      </div>
      <div class="entities-page__meta text-sm" v-if="store.novelId">
        <span class="mr-4">实体数：{{ store.entities.length }}</span>
        <span>关系数：{{ store.entityRelationships.length }}</span>
      </div>
    </div>

    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />

    <template v-else>
      <div class="grid gap-4 lg:grid-cols-[320px,minmax(0,1fr)] items-start">
        <EntityTree
          :nodes="store.entityTree"
          :search-query="store.entitySearchQuery"
          :selected-node-id="store.selectedEntityNode?.id || ''"
          :loading="entityLoading"
          :total-count="store.entities.length"
          :tree-node-count="entityTreeNodeCount"
          @update:search-query="store.entitySearchQuery = $event"
          @search="runEntitySearch"
          @reset="resetEntityWorkspace"
          @select="handleNodeSelect"
        />

        <div class="space-y-4 min-w-0">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="entities-page__meta text-sm">
              {{ workspaceStatusText }}
            </div>
            <el-radio-group v-model="workspaceView" size="small">
              <el-radio-button label="workspace">工作区</el-radio-button>
              <el-radio-button label="graph">关系图谱</el-radio-button>
            </el-radio-group>
          </div>

          <template v-if="workspaceView === 'workspace'">
            <div
              v-if="!selectedNode"
              class="entities-page__workspace-empty surface-card p-8"
            >
              <el-empty description="请先从左侧目录选择一个分类、分组或实体" />
            </div>

            <EntityGroupTable
              v-else-if="workspaceMode === 'group'"
              :title="workspaceTitle"
              :items="workspaceItems"
              :selected-node-label="store.selectedEntityNode?.label || ''"
              :group-count="workspaceGroupCount"
              :total-count="workspaceTotalCount"
              :show-empty-state="!workspaceItems.length"
              @select-entity="selectEntity"
              @save-classification="saveClassification"
              @clear-override="clearOverride"
            />

            <EntityDetailPanel
              v-else
              :entity="store.selectedEntityDetail"
              :relationships="store.entityRelationships"
              :title="workspaceTitle"
              @save-entity="saveEntity"
              @delete-entity="deleteEntity"
              @save-classification="saveClassification"
              @clear-override="clearOverride"
              @reclassify="reclassifyEntity"
              @select-entity="selectEntityById"
            />
          </template>

          <div v-else class="entities-page__graph-card surface-card p-4 space-y-3">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 class="font-bold">关系图谱</h3>
                <p class="entities-page__meta text-sm">辅助查看实体关系，可全屏放大。</p>
              </div>
            </div>
            <EntityGraph
              :entities="graphEntities"
              :relationships="graphRelationships"
              height="28rem"
              show-fullscreen-action
              @fullscreen="graphFullscreenVisible = true"
            />
          </div>
        </div>
      </div>

      <el-dialog
        v-model="graphFullscreenVisible"
        title="关系图谱"
        fullscreen
        :close-on-click-modal="false"
        append-to-body
      >
        <EntityGraph
          v-if="graphFullscreenVisible"
          :entities="graphEntities"
          :relationships="graphRelationships"
          height="calc(100vh - 10rem)"
        />
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useNovelStore } from '@/stores/novel.js'
import EntityGraph from '@/components/EntityGraph.vue'
import EntityTree from '@/components/entities/EntityTree.vue'
import EntityGroupTable from '@/components/entities/EntityGroupTable.vue'
import EntityDetailPanel from '@/components/entities/EntityDetailPanel.vue'

const store = useNovelStore()
const graphFullscreenVisible = ref(false)
const entityLoading = ref(false)
const workspaceView = ref('workspace')

function countTreeNodes(nodes = []) {
  return nodes.reduce((total, node) => total + 1 + countTreeNodes(node.children || []), 0)
}

function collectEntities(node) {
  if (!node) return []
  if (node.nodeType === 'entity') return [node.data].filter(Boolean)
  return (node.children || []).flatMap(child => collectEntities(child))
}

const entityTreeNodeCount = computed(() => countTreeNodes(store.entityTree))
const selectedNode = computed(() => store.selectedEntityNode)
const workspaceMode = computed(() =>
  selectedNode.value?.nodeType === 'entity' ? 'detail' : 'group'
)
const workspaceTitle = computed(() => selectedNode.value?.label || '实体工作区')
const workspaceStatusText = computed(() => {
  if (!selectedNode.value) return '当前未选择目录节点'
  return workspaceMode.value === 'detail' ? '当前为实体详情视图' : '当前为分组整理视图'
})
const workspaceItems = computed(() => {
  const node = selectedNode.value
  if (!node) return []
  if (node.nodeType === 'entity') return []
  return collectEntities(node)
})
const workspaceGroupCount = computed(() => {
  const node = selectedNode.value
  if (!node || node.nodeType === 'entity') return 0
  if (node.nodeType === 'group') return 1
  return (node.children || []).filter(child => child.nodeType === 'group').length
})
const workspaceTotalCount = computed(() => workspaceItems.value.length)
const graphScope = computed(() => {
  const node = selectedNode.value
  const allEntities = store.entities || []
  const allRelationships = store.entityRelationships || []

  if (!node) {
    return {
      entities: allEntities,
      relationships: allRelationships,
    }
  }

  if (node.nodeType === 'entity') {
    const relatedRelationships = allRelationships.filter(
      rel => rel.source_id === node.entityId || rel.target_id === node.entityId
    )
    const entityIds = new Set([node.entityId])
    for (const rel of relatedRelationships) {
      if (rel.source_id) entityIds.add(rel.source_id)
      if (rel.target_id) entityIds.add(rel.target_id)
    }
    return {
      entities: allEntities.filter(entity => entityIds.has(entity.entity_id)),
      relationships: relatedRelationships,
    }
  }

  const scopedEntities = collectEntities(node)
  const entityIds = new Set(scopedEntities.map(entity => entity.entity_id))
  const relatedRelationships = allRelationships.filter(
    rel => entityIds.has(rel.source_id) || entityIds.has(rel.target_id)
  )
  const graphEntityIds = new Set(entityIds)
  for (const rel of relatedRelationships) {
    if (rel.source_id) graphEntityIds.add(rel.source_id)
    if (rel.target_id) graphEntityIds.add(rel.target_id)
  }
  return {
    entities: allEntities.filter(entity => graphEntityIds.has(entity.entity_id)),
    relationships: relatedRelationships,
  }
})
const graphEntities = computed(() => graphScope.value.entities)
const graphRelationships = computed(() => graphScope.value.relationships)

function setSelectedNode(nodeData) {
  store.selectedEntityNode = nodeData || null
  store.selectedEntityDetail = nodeData?.nodeType === 'entity' ? nodeData.data || null : null
}

function handleNodeSelect(nodeData) {
  setSelectedNode(nodeData)
}

function selectEntity(entity) {
  if (!entity) return
  workspaceView.value = 'workspace'
  const match = findNodeByEntityId(store.entityTree, entity.entity_id)
  if (match) {
    setSelectedNode(match)
    return
  }
  store.selectedEntityNode = { id: `entity:${entity.entity_id}`, label: entity.name || '未命名实体', nodeType: 'entity', entityId: entity.entity_id, data: entity }
  store.selectedEntityDetail = entity
}

function selectEntityById(entityId) {
  if (!entityId) return
  const match = findNodeByEntityId(store.entityTree, entityId)
  if (match) {
    workspaceView.value = 'workspace'
    setSelectedNode(match)
  }
}

function findNodeByEntityId(nodes = [], entityId) {
  for (const node of nodes) {
    if (node.entityId === entityId) return node
    const match = findNodeByEntityId(node.children || [], entityId)
    if (match) return match
  }
  return null
}

async function runEntitySearch() {
  const query = (store.entitySearchQuery || '').trim()
  if (!query) {
    resetEntityWorkspace()
    return
  }
  entityLoading.value = true
  try {
    await store.searchEntities(query)
  } finally {
    entityLoading.value = false
  }
}

async function resetEntityWorkspace() {
  entityLoading.value = true
  try {
    store.clearEntityWorkspaceState()
    await store.fetchEntities()
  } finally {
    entityLoading.value = false
  }
}

async function saveClassification(entity, payload) {
  if (!entity?.entity_id) return
  const entityIds = entity.merged_entity_ids?.length ? entity.merged_entity_ids : [entity.entity_id]
  entityLoading.value = true
  try {
    await store.saveEntityClassification(entityIds, payload)
  } finally {
    entityLoading.value = false
  }
}

async function clearOverride(entity) {
  if (!entity?.entity_id) return
  await saveClassification(entity, { clear_manual_override: true })
}

async function reclassifyEntity(entity) {
  if (!entity?.entity_id) return
  await saveClassification(entity, { reclassify: true })
}

async function saveEntity(entity, payload) {
  if (!entity?.entity_id) return
  entityLoading.value = true
  try {
    await store.updateEntity(entity.entity_id, payload)
  } finally {
    entityLoading.value = false
  }
}

async function deleteEntity(entity) {
  if (!entity?.entity_id) return
  await ElMessageBox.confirm(
    `将硬删除实体“${entity.name || entity.entity_id}”，其版本记录和关系记录也会一并删除，且不可恢复。是否继续？`,
    '确认删除实体',
    {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    }
  )
  entityLoading.value = true
  try {
    await store.deleteEntity(entity.entity_id)
  } finally {
    entityLoading.value = false
  }
}

async function fetchIfReady() {
  if (!store.novelId) return
  entityLoading.value = true
  try {
    await store.fetchEntities()
  } finally {
    entityLoading.value = false
  }
}

watch(
  () => store.entityTree,
  (nodes) => {
    if (!nodes.length) {
      store.selectedEntityNode = null
      store.selectedEntityDetail = null
      return
    }

    const currentId = store.selectedEntityNode?.id
    if (!currentId) return
    const node = findNodeById(nodes, currentId)
    if (node) {
      setSelectedNode(node)
      return
    }
    store.selectedEntityNode = null
    store.selectedEntityDetail = null
  },
  { immediate: true }
)

function findNodeById(nodes = [], nodeId) {
  for (const node of nodes) {
    if (node.id === nodeId) return node
    const match = findNodeById(node.children || [], nodeId)
    if (match) return match
  }
  return null
}

onMounted(fetchIfReady)
watch(() => store.novelId, fetchIfReady)
</script>

<style scoped>
.entities-page__meta {
  color: var(--entities-text-muted);
}

.entities-page__workspace-empty,
.entities-page__graph-card {
  border-color: var(--entities-panel-border);
  background: var(--entities-panel-bg);
  color: var(--entities-text);
}
</style>
