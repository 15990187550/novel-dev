<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-xl font-bold">实体百科</h2>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          左侧目录用于切换分类、分组和实体，右侧用于查看列表或详情。
        </p>
      </div>
      <div class="text-sm text-gray-500 dark:text-gray-400" v-if="store.novelId">
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
            <div class="text-sm text-gray-500 dark:text-gray-400">
              {{ workspaceMode === 'detail' ? '当前为实体详情视图' : '当前为分组整理视图' }}
            </div>
            <el-radio-group v-model="workspaceView" size="small">
              <el-radio-button label="workspace">工作区</el-radio-button>
              <el-radio-button label="graph">关系图谱</el-radio-button>
            </el-radio-group>
          </div>

          <template v-if="workspaceView === 'workspace'">
            <EntityGroupTable
              v-if="workspaceMode === 'group'"
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
              @save-classification="saveClassification"
              @clear-override="clearOverride"
              @reclassify="reclassifyEntity"
              @select-entity="selectEntityById"
            />
          </template>

          <div v-else class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 space-y-3">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 class="font-bold">关系图谱</h3>
                <p class="text-sm text-gray-500 dark:text-gray-400">辅助查看实体关系，可全屏放大。</p>
              </div>
            </div>
            <EntityGraph
              :entities="store.entities"
              :relationships="store.entityRelationships"
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
          :entities="store.entities"
          :relationships="store.entityRelationships"
          height="calc(100vh - 10rem)"
        />
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
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

function firstSelectableNode(nodes = []) {
  for (const node of nodes) {
    if (node.nodeType === 'entity' || node.nodeType === 'group' || node.nodeType === 'category') {
      return node
    }
    const match = firstSelectableNode(node.children || [])
    if (match) return match
  }
  return null
}

const entityTreeNodeCount = computed(() => countTreeNodes(store.entityTree))
const selectedNode = computed(() => store.selectedEntityNode)
const workspaceMode = computed(() => selectedNode.value?.nodeType === 'entity' ? 'detail' : 'group')
const workspaceTitle = computed(() => selectedNode.value?.label || '实体工作区')
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

function setSelectedNode(nodeData) {
  store.selectedEntityNode = nodeData || null
  store.selectedEntityDetail = nodeData?.nodeType === 'entity' ? nodeData.data || null : null
}

function handleNodeSelect(nodeData) {
  workspaceView.value = 'workspace'
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
    const node = currentId ? findNodeById(nodes, currentId) : firstSelectableNode(nodes)
    if (node) setSelectedNode(node)
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
