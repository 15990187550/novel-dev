<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">设定资料</h2>
    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />
    <template v-else>
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">上传设定文件</h3>
        <div class="flex items-center gap-2">
          <input ref="fileInput" type="file" accept=".txt,.md" multiple @change="onFileChange" class="text-sm" />
          <el-button type="primary" :loading="uploading" @click="upload">上传</el-button>
        </div>
        <div v-if="selectedFiles.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400">
          已选择 {{ selectedFiles.length }} 个文件
        </div>
        <div v-if="uploadSummary" class="mt-3 space-y-2 text-sm">
          <div class="text-gray-700 dark:text-gray-300">
            本次导入完成：成功 {{ uploadSummary.succeeded }}，失败 {{ uploadSummary.failed }}，共 {{ uploadSummary.total }} 个文件
          </div>
          <div v-if="uploadSummary.failed" class="text-red-600 dark:text-red-400 space-y-1">
            <div
              v-for="item in uploadSummary.items.filter(item => item.error)"
              :key="item.filename"
              class="whitespace-pre-wrap"
            >
              {{ item.filename }}：{{ item.error }}
            </div>
          </div>
        </div>
      </div>
      <div v-if="store.pendingDocs.length" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">设定提取记录</h3>
        <el-table :data="store.pendingDocs">
          <el-table-column prop="source_filename" label="来源文件" min-width="180" />
          <el-table-column prop="extraction_type" label="类型" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="变更摘要" min-width="220">
            <template #default="{ row }">{{ row.diff_result?.summary || '-' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" />
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <div class="flex gap-2">
                <el-button size="small" @click="showDetail(row)">查看详情</el-button>
                <el-button v-if="row.status !== 'approved'" size="small" type="primary" @click="approve(row.id)">批准</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <el-dialog v-model="detailVisible" title="设定提取详情" width="1080px">
        <div v-if="selectedDoc" class="space-y-4">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div><span class="font-bold">类型：</span>{{ selectedDoc.extraction_type }}</div>
            <div><span class="font-bold">状态：</span>{{ selectedDoc.status }}</div>
            <div><span class="font-bold">创建时间：</span>{{ selectedDoc.created_at }}</div>
          </div>

          <div v-if="selectedDoc.diff_result" class="space-y-3">
            <div class="flex items-center justify-between">
              <div class="font-bold">增量变更</div>
              <span class="text-sm text-gray-500">{{ selectedDoc.diff_result.summary }}</span>
            </div>

            <div v-if="diffGroups.create.length">
              <div class="font-semibold mb-2 text-green-700 dark:text-green-300">新增实体</div>
              <div class="space-y-2">
                <div v-for="entity in diffGroups.create" :key="entityKey(entity)" class="rounded-lg border border-green-200 dark:border-green-800 p-3 bg-green-50/60 dark:bg-green-950/20">
                  <div class="font-semibold mb-2">{{ entity.entity_name }} <span class="text-xs text-gray-500">{{ entity.entity_type }}</span></div>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
                    <div v-for="change in visibleChanges(entity)" :key="change.field" class="flex gap-2">
                      <span class="font-medium min-w-20">{{ change.label || change.field }}：</span>
                      <span class="whitespace-pre-wrap">{{ formatValue(change.new_value) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="diffGroups.update.length">
              <div class="font-semibold mb-2 text-blue-700 dark:text-blue-300">自动补充/更新</div>
              <div class="space-y-2">
                <div v-for="entity in diffGroups.update" :key="entityKey(entity)" class="rounded-lg border border-blue-200 dark:border-blue-800 p-3 bg-blue-50/60 dark:bg-blue-950/20">
                  <div class="font-semibold mb-2">{{ entity.entity_name }} <span class="text-xs text-gray-500">{{ entity.entity_type }}</span></div>
                  <el-table :data="visibleChanges(entity)" size="small" border>
                    <el-table-column prop="label" label="字段" width="120">
                      <template #default="{ row }">{{ row.label || row.field }}</template>
                    </el-table-column>
                    <el-table-column label="旧值">
                      <template #default="{ row }"><span class="whitespace-pre-wrap">{{ formatValue(row.old_value) || '-' }}</span></template>
                    </el-table-column>
                    <el-table-column label="新值">
                      <template #default="{ row }"><span class="whitespace-pre-wrap">{{ formatValue(row.new_value) }}</span></template>
                    </el-table-column>
                  </el-table>
                </div>
              </div>
            </div>

            <div v-if="diffGroups.conflict.length">
              <div class="font-semibold mb-2 text-red-700 dark:text-red-300">冲突字段</div>
              <div class="space-y-2">
                <div v-for="entity in diffGroups.conflict" :key="entityKey(entity)" class="rounded-lg border border-red-200 dark:border-red-800 p-3 bg-red-50/60 dark:bg-red-950/20">
                  <div class="font-semibold mb-2">{{ entity.entity_name }} <span class="text-xs text-gray-500">{{ entity.entity_type }}</span></div>
                  <el-table :data="visibleChanges(entity)" size="small" border>
                    <el-table-column prop="label" label="字段" width="120">
                      <template #default="{ row }">{{ row.label || row.field }}</template>
                    </el-table-column>
                    <el-table-column label="旧值">
                      <template #default="{ row }"><span class="whitespace-pre-wrap">{{ formatValue(row.old_value) || '-' }}</span></template>
                    </el-table-column>
                    <el-table-column label="新值">
                      <template #default="{ row }"><span class="whitespace-pre-wrap">{{ formatValue(row.new_value) }}</span></template>
                    </el-table-column>
                    <el-table-column label="处理方式" width="180">
                      <template #default="{ row }">
                        <el-select v-model="conflictSelections[conflictKey(entity, row)]" size="small">
                          <el-option label="保留旧值" value="keep_old" />
                          <el-option label="使用新值" value="use_new" />
                          <el-option label="跳过" value="skip" />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column prop="reason" label="原因" width="180" />
                  </el-table>
                </div>
              </div>
            </div>

            <el-empty v-if="!selectedDoc.diff_result.entity_diffs?.length" description="无实体变更" />
          </div>

            <div v-if="resolutionRows.length">
              <div class="font-semibold mb-2 text-purple-700 dark:text-purple-300">处理结果</div>
              <el-table :data="resolutionRows" size="small" border>
                <el-table-column prop="entity_name" label="实体" width="140" />
                <el-table-column prop="field" label="字段" width="120">
                  <template #default="{ row }">{{ fieldLabel(row.field) }}</template>
                </el-table-column>
                <el-table-column prop="action" label="动作" width="140">
                  <template #default="{ row }">
                    <el-tag :type="row.applied ? 'success' : 'info'" size="small">{{ resolutionActionLabel(row.action) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="applied" label="是否写入" width="100">
                  <template #default="{ row }">{{ row.applied ? '已写入' : '未写入' }}</template>
                </el-table-column>
              </el-table>
            </div>

          <el-collapse>
            <el-collapse-item title="原始提取结果" name="raw">
              <pre class="bg-gray-50 dark:bg-gray-900 rounded-lg p-3 text-xs overflow-auto max-h-80 whitespace-pre-wrap">{{ formatJson(selectedDoc.raw_result) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="拟写入实体" name="entities">
              <pre class="bg-gray-50 dark:bg-gray-900 rounded-lg p-3 text-xs overflow-auto max-h-80 whitespace-pre-wrap">{{ formatJson(selectedDoc.proposed_entities) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { uploadDocumentsBatch, approvePending } from '@/api.js'
import { ElMessage } from 'element-plus'

const store = useNovelStore()
const fileInput = ref(null)
const selectedFiles = ref([])
const uploading = ref(false)
const detailVisible = ref(false)
const selectedDoc = ref(null)
const conflictSelections = reactive({})
const uploadSummary = ref(null)

const diffGroups = computed(() => {
  const groups = { create: [], update: [], conflict: [] }
  for (const entity of selectedDoc.value?.diff_result?.entity_diffs || []) {
    if (entity.operation === 'create') groups.create.push(entity)
    else if (entity.operation === 'conflict') groups.conflict.push(entity)
    else if (entity.operation === 'update') groups.update.push(entity)
  }
  return groups
})

const resolutionRows = computed(() => selectedDoc.value?.resolution_result?.field_resolutions || [])

const fieldLabels = {
  identity: '身份',
  personality: '性格',
  goal: '目标',
  appearance: '外貌',
  background: '背景',
  ability: '能力',
  realm: '境界',
  relationships: '关系',
  resources: '资源',
  secrets: '秘密',
  conflict: '冲突',
  arc: '人物弧光',
  notes: '备注',
  description: '描述',
  significance: '重要性',
}

function fieldLabel(field) {
  return fieldLabels[field] || field
}

function resolutionActionLabel(action) {
  const labels = {
    created: '新增实体',
    auto_apply: '自动写入',
    use_new: '采用新值',
    merge: '合并写入',
    keep_old: '保留旧值',
    skip: '跳过',
  }
  return labels[action] || action
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (ev) => resolve({ filename: file.name, content: ev.target.result || '' })
    reader.onerror = () => reject(new Error(`读取文件失败: ${file.name}`))
    reader.readAsText(file)
  })
}

async function onFileChange(e) {
  const files = Array.from(e.target.files || [])
  if (!files.length) {
    selectedFiles.value = []
    return
  }
  selectedFiles.value = await Promise.all(files.map(readFile))
}

function conflictKey(entity, change) {
  return `${entity.entity_type}:${entity.entity_name}:${change.field}`
}

function initializeConflictSelections(doc) {
  Object.keys(conflictSelections).forEach(key => delete conflictSelections[key])
  for (const entity of doc?.diff_result?.entity_diffs || []) {
    if (entity.operation !== 'conflict') continue
    for (const change of entity.field_changes || []) {
      conflictSelections[conflictKey(entity, change)] = 'keep_old'
    }
  }
}

function showDetail(doc) {
  selectedDoc.value = doc
  initializeConflictSelections(doc)
  detailVisible.value = true
}

function formatJson(value) {
  if (value == null) return '-'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function formatValue(value) {
  if (value == null || value === '') return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function visibleChanges(entity) {
  return (entity.field_changes || []).filter(change => formatValue(change.new_value))
}

function entityKey(entity) {
  return `${entity.entity_type}:${entity.entity_name}:${entity.operation}`
}

function buildFieldResolutions() {
  const resolutions = []
  for (const entity of selectedDoc.value?.diff_result?.entity_diffs || []) {
    if (entity.operation !== 'conflict') continue
    for (const change of entity.field_changes || []) {
      const action = conflictSelections[conflictKey(entity, change)]
      if (!action || action === 'keep_old') continue
      resolutions.push({
        entity_type: entity.entity_type,
        entity_name: entity.entity_name,
        field: change.field,
        action,
      })
    }
  }
  return resolutions
}

async function upload() {
  if (!selectedFiles.value.length) return
  uploading.value = true
  try {
    uploadSummary.value = await uploadDocumentsBatch(store.novelId, selectedFiles.value, 3)
    ElMessage.success(`上传完成：成功 ${uploadSummary.value.succeeded} 个`)
    await store.fetchDocuments()
  } finally {
    uploading.value = false
    selectedFiles.value = []
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function approve(id) {
  const fieldResolutions = selectedDoc.value?.id === id ? buildFieldResolutions() : []
  await approvePending(store.novelId, id, fieldResolutions)
  ElMessage.success('已批准')
  detailVisible.value = false
  await store.fetchDocuments()
}

function fetchIfReady() {
  if (store.novelId) store.fetchDocuments()
}

onMounted(fetchIfReady)
watch(() => store.novelId, fetchIfReady)
</script>
