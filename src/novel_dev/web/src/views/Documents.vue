<template>
  <div class="space-y-6">
    <section class="page-header">
      <div>
        <div class="page-header__eyebrow">Knowledge Base</div>
        <h1 class="page-header__title">设定与文风</h1>
        <p class="page-header__description">
          把导入、审核、已生效资料和文风版本收敛到同一个面板里，避免上下文分散。
        </p>
      </div>
      <div class="page-header__meta-grid">
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">待审核</span>
          <span class="page-header__meta-value">{{ store.pendingDocs.length }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">已生效资料</span>
          <span class="page-header__meta-value">{{ libraryItems.length }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">文风版本</span>
          <span class="page-header__meta-value">{{ styleProfiles.length }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">当前版本</span>
          <span class="page-header__meta-value">{{ activeStyleVersionText }}</span>
        </div>
      </div>
    </section>

    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />
    <template v-else>
      <div class="surface-card p-5">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h3 class="font-bold">导入设定 / 文风样本</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              支持批量上传 `.txt` / `.md`。系统会自动识别是“设定文档”还是“文风样本”。
            </p>
          </div>
          <div class="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-300">
            每个文件尽量只放一种内容，识别和审核会更稳定
          </div>
        </div>

        <div class="mt-4 grid gap-3 md:grid-cols-3 text-sm">
          <div class="rounded-xl border border-gray-200 dark:border-gray-700 p-3">
            <div class="font-semibold">支持文件</div>
            <div class="mt-2 text-gray-600 dark:text-gray-300">`.txt`、`.md`，可一次上传多个文件。</div>
          </div>
          <div class="rounded-xl border border-gray-200 dark:border-gray-700 p-3">
            <div class="font-semibold">设定文档会提取</div>
            <div class="mt-2 text-gray-600 dark:text-gray-300">世界观、修炼体系、势力格局、剧情梗概，以及人物/物品实体。</div>
          </div>
          <div class="rounded-xl border border-gray-200 dark:border-gray-700 p-3">
            <div class="font-semibold">文风样本会提取</div>
            <div class="mt-2 text-gray-600 dark:text-gray-300">文笔文风、叙事视角、节奏、写作规则、风格边界。</div>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-2">
          <input ref="fileInput" type="file" accept=".txt,.md,text/plain,text/markdown" multiple @change="onFileChange" class="text-sm" />
          <el-button type="primary" :loading="uploading" @click="upload">上传</el-button>
        </div>

        <div v-if="selectedFiles.length" class="mt-3 rounded-xl bg-gray-50 dark:bg-gray-900/60 p-3 text-sm text-gray-600 dark:text-gray-300">
          <div class="font-medium text-gray-900 dark:text-gray-100">待导入文件</div>
          <div class="mt-2 flex flex-wrap gap-2">
            <span
              v-for="file in selectedFiles"
              :key="file.filename"
              class="rounded-full border border-gray-200 dark:border-gray-700 px-3 py-1"
            >
              {{ file.filename }}
            </span>
          </div>
        </div>

        <div v-if="uploadSummary" class="mt-3 space-y-2 text-sm">
          <div class="text-gray-700 dark:text-gray-300">
            本次导入任务已提交：已创建 {{ uploadSummary.accepted ?? uploadSummary.succeeded ?? 0 }} 条记录，失败 {{ uploadSummary.failed }}，共 {{ uploadSummary.total }} 个文件
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

      <div class="surface-card p-5">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h3 class="font-bold">当前资料库</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              已批准的设定和文风会沉淀在这里，供后续脑暴、卷纲和正文生成使用。
            </p>
          </div>
          <div class="text-sm text-gray-500 dark:text-gray-400">
            已生效 {{ libraryItems.length }} 份
          </div>
        </div>

        <div v-if="libraryLoading" class="mt-4 text-sm text-gray-500 dark:text-gray-400">加载资料库中...</div>
        <el-empty v-else-if="!hasLibraryContent" description="批准导入后，会在这里看到世界观、体系设定、剧情梗概和文风档案" />

        <div v-else class="mt-4 space-y-6">
          <section v-for="group in libraryGroups" :key="group.docType" class="space-y-3">
            <div class="flex items-center justify-between">
              <div class="font-semibold text-gray-900 dark:text-gray-100">{{ group.label }}</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">{{ group.items.length }} 份</div>
            </div>
            <div class="space-y-3">
              <details
                v-for="item in group.items"
                :key="item.id"
                class="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-900/50 p-3"
                open
              >
                <summary class="cursor-pointer list-none">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="font-medium text-gray-900 dark:text-gray-100">{{ item.title || group.label }}</div>
                    <div class="text-xs text-gray-500 dark:text-gray-400">{{ formatTimestamp(item.updated_at) }}</div>
                  </div>
                </summary>
                <pre class="mt-3 whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-200">{{ item.content }}</pre>
              </details>
            </div>
          </section>

          <section v-if="styleProfiles.length" class="space-y-3">
            <div class="flex items-center justify-between">
              <div class="font-semibold text-gray-900 dark:text-gray-100">文风档案</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">
                当前生效版本：{{ activeStyleVersionText }}
              </div>
            </div>
            <div class="space-y-3">
              <div
                v-for="profile in styleProfiles"
                :key="profile.id"
                class="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-900/50 p-4"
              >
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="flex items-center gap-2">
                    <div class="font-medium text-gray-900 dark:text-gray-100">版本 v{{ profile.version }}</div>
                    <el-tag v-if="profile.is_active" size="small" type="success">当前生效</el-tag>
                    <el-tag v-else size="small" type="info">历史版本</el-tag>
                  </div>
                  <div class="flex items-center gap-2">
                    <div class="text-xs text-gray-500 dark:text-gray-400">{{ formatTimestamp(profile.updated_at) }}</div>
                    <el-button
                      v-if="!profile.is_active"
                      size="small"
                      :loading="rollingBackVersion === profile.version"
                      @click="activateStyleVersion(profile.version)"
                    >
                      {{ rollingBackVersion === profile.version ? '切换中...' : '设为当前版本' }}
                    </el-button>
                  </div>
                </div>

                <div class="mt-3 rounded-xl bg-white dark:bg-gray-800 p-3 border border-gray-200 dark:border-gray-700">
                  <div class="text-xs uppercase tracking-wide text-gray-400">Style Guide</div>
                  <div class="mt-2 whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-200">{{ profile.content }}</div>
                </div>

                <div v-if="styleSummaryItems(profile).length" class="mt-3 grid gap-3 md:grid-cols-3 text-sm">
                  <div
                    v-for="item in styleSummaryItems(profile)"
                    :key="item.label"
                    class="rounded-xl border border-gray-200 dark:border-gray-700 p-3"
                  >
                    <div class="text-xs text-gray-400">{{ item.label }}</div>
                    <div class="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-200">{{ item.value }}</div>
                  </div>
                </div>

                <details class="mt-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3">
                  <summary class="cursor-pointer list-none font-medium text-sm text-gray-700 dark:text-gray-200">
                    查看完整风格配置
                  </summary>
                  <pre class="mt-3 whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-300">{{ formatJson(profile.style_config || {}) }}</pre>
                </details>
              </div>
            </div>
          </section>
        </div>
      </div>

      <div v-if="store.pendingDocs.length" class="surface-card p-5">
        <h3 class="font-bold mb-3">导入审核记录</h3>
        <el-table :data="store.pendingDocs">
          <el-table-column prop="source_filename" label="来源文件" min-width="180" />
          <el-table-column label="类型">
            <template #default="{ row }">{{ extractionTypeLabel(row.extraction_type, row.status) }}</template>
          </el-table-column>
          <el-table-column label="状态">
            <template #default="{ row }">{{ statusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column label="变更摘要" min-width="220">
            <template #default="{ row }">{{ row.diff_result?.summary || row.error_message || '-' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" />
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <div class="flex gap-2">
                <el-button size="small" @click="showDetail(row)">查看详情</el-button>
                <el-button
                  v-if="row.status === 'pending'"
                  size="small"
                  type="primary"
                  :loading="approvingPendingId === row.id"
                  :disabled="(!!approvingPendingId && approvingPendingId !== row.id) || !!rejectingPendingId"
                  @click="approve(row.id)"
                >
                  {{ approvingPendingId === row.id ? '批准中...' : '批准' }}
                </el-button>
                <el-button
                  v-if="row.status === 'pending'"
                  size="small"
                  type="danger"
                  plain
                  :loading="rejectingPendingId === row.id"
                  :disabled="(!!rejectingPendingId && rejectingPendingId !== row.id) || !!approvingPendingId"
                  @click="reject(row.id)"
                >
                  {{ rejectingPendingId === row.id ? '拒绝中...' : '拒绝' }}
                </el-button>
                <el-button
                  v-if="row.status === 'failed'"
                  size="small"
                  type="danger"
                  plain
                  :loading="deletingPendingId === row.id"
                  :disabled="(!!deletingPendingId && deletingPendingId !== row.id) || !!approvingPendingId || !!rejectingPendingId"
                  @click="removeFailedRecord(row.id)"
                >
                  {{ deletingPendingId === row.id ? '删除中...' : '删除' }}
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <el-dialog
        v-model="detailVisible"
        title="导入详情"
        width="1080px"
        top="4vh"
        append-to-body
      >
        <div v-if="selectedDoc" class="max-h-[78vh] space-y-4 overflow-y-auto pr-2">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div><span class="font-bold">类型：</span>{{ extractionTypeLabel(selectedDoc.extraction_type, selectedDoc.status) }}</div>
            <div><span class="font-bold">状态：</span>{{ statusLabel(selectedDoc.status) }}</div>
            <div><span class="font-bold">创建时间：</span>{{ selectedDoc.created_at }}</div>
          </div>

          <el-alert
            v-if="selectedDoc.error_message"
            :title="selectedDoc.error_message"
            type="error"
            :closable="false"
            show-icon
          />

          <el-alert
            v-if="mergeResolvingCount"
            :title="`自动合并中：${mergeResolvingCount} 个冲突字段正在处理`"
            type="warning"
            :closable="false"
            show-icon
          />

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
              <div class="font-semibold mb-2 text-blue-700 dark:text-blue-300">自动补充</div>
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
                        <el-tag v-if="row.auto_applicable" type="success" size="small">默认采用新值</el-tag>
                        <el-tag
                          v-else-if="isMergeResolving(entity, row)"
                          type="warning"
                          size="small"
                        >
                          自动合并中
                        </el-tag>
                        <el-select
                          v-else
                          v-model="conflictSelections[conflictKey(entity, row)]"
                          size="small"
                          :disabled="isApprovingSelectedDoc"
                        >
                          <el-option label="保留旧值" value="keep_old" />
                          <el-option label="使用新值" value="use_new" />
                          <el-option label="自动合并" value="merge" />
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
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import {
  uploadDocumentsBatch,
  approvePending,
  deletePendingDoc,
  rejectPending,
  getDocumentLibrary,
  rollbackStyleProfile,
} from '@/api.js'
import { ElMessage } from 'element-plus'

const DOCUMENT_POLL_INTERVAL_MS = 2000
const LIBRARY_GROUPS = [
  { docType: 'worldview', label: '世界观' },
  { docType: 'setting', label: '体系设定' },
  { docType: 'synopsis', label: '剧情梗概' },
  { docType: 'concept', label: '概念设定' },
]

const store = useNovelStore()
const fileInput = ref(null)
const selectedFiles = ref([])
const uploading = ref(false)
const detailVisible = ref(false)
const selectedDoc = ref(null)
const conflictSelections = reactive({})
const conflictSelectionMemory = reactive({})
const resolvingMergeKeys = reactive({})
const uploadSummary = ref(null)
const documentPollTimer = ref(null)
const libraryItems = ref([])
const libraryLoading = ref(false)
const rollingBackVersion = ref(null)
const approvingPendingId = computed({
  get: () => store.pendingDocActions.approvingPendingId,
  set: (value) => {
    store.pendingDocActions.approvingPendingId = value
  },
})
const rejectingPendingId = computed({
  get: () => store.pendingDocActions.rejectingPendingId,
  set: (value) => {
    store.pendingDocActions.rejectingPendingId = value
  },
})
const deletingPendingId = computed({
  get: () => store.pendingDocActions.deletingPendingId,
  set: (value) => {
    store.pendingDocActions.deletingPendingId = value
  },
})

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
const hasProcessingDocs = computed(() => (store.pendingDocs || []).some((doc) => doc.status === 'processing'))
const isApprovingSelectedDoc = computed(() => !!selectedDoc.value?.id && approvingPendingId.value === selectedDoc.value.id)
const mergeResolvingCount = computed(() => Object.keys(resolvingMergeKeys).length)
const hasLibraryContent = computed(() => libraryItems.value.length > 0)
const styleProfiles = computed(() => libraryItems.value.filter((item) => item.doc_type === 'style_profile'))
const activeStyleVersionText = computed(() => {
  const active = styleProfiles.value.find((item) => item.is_active)
  return active ? `v${active.version}` : '未设置'
})
const libraryGroups = computed(() =>
  LIBRARY_GROUPS
    .map((group) => ({
      ...group,
      items: libraryItems.value.filter((item) => item.doc_type === group.docType),
    }))
    .filter((group) => group.items.length)
)

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

function extractionTypeLabel(type, status = '') {
  if (status === 'processing' && (!type || type === 'processing')) return '处理中'
  const labels = {
    setting: '设定',
    style_profile: '风格样本',
    processing: '处理中',
  }
  return labels[type] || type || '-'
}

function statusLabel(status) {
  const labels = {
    processing: '导入中',
    pending: '待审核',
    failed: '失败',
    approved: '已批准',
  }
  return labels[status] || status || '-'
}

function resolutionActionLabel(action) {
  const labels = {
    created: '新增实体',
    auto_apply: '自动写入',
    use_new: '采用新值',
    merge: '自动合并',
    keep_old: '保留旧值',
    skip: '跳过',
  }
  return labels[action] || action
}

function formatTimestamp(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
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

function toList(value) {
  if (!Array.isArray(value)) return []
  return value.map((item) => formatValue(item)).filter(Boolean)
}

function styleSummaryItems(profile) {
  const config = profile?.style_config || {}
  const items = []
  if (config.perspective) items.push({ label: '叙事视角', value: config.perspective })
  if (config.pacing) items.push({ label: '节奏', value: config.pacing })
  if (config.tone) items.push({ label: '整体气质', value: config.tone })
  const writingRules = toList(config.writing_rules)
  if (writingRules.length) items.push({ label: '写作规则', value: writingRules.join('\n') })
  const boundaries = toList(config.style_boundary)
  if (boundaries.length) items.push({ label: '风格边界', value: boundaries.join('\n') })
  const vocabulary = toList(config.vocabulary_preferences)
  if (vocabulary.length) items.push({ label: '偏好词汇', value: vocabulary.join(' / ') })
  return items
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

function isMergeResolving(entity, change) {
  return !!resolvingMergeKeys[conflictKey(entity, change)]
}

function initializeConflictSelections(doc) {
  Object.keys(conflictSelections).forEach(key => delete conflictSelections[key])
  for (const entity of doc?.diff_result?.entity_diffs || []) {
    if (entity.operation !== 'conflict') continue
    for (const change of entity.field_changes || []) {
      if (change.auto_applicable) continue
      const key = conflictKey(entity, change)
      conflictSelections[key] = conflictSelectionMemory[`${doc?.id}:${key}`] || 'merge'
    }
  }
}

function showDetail(doc) {
  selectedDoc.value = doc
  initializeConflictSelections(doc)
  detailVisible.value = true
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
      if (change.auto_applicable) continue
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

function rememberConflictSelections(doc) {
  if (!doc?.id) return
  for (const [key, value] of Object.entries(conflictSelections)) {
    conflictSelectionMemory[`${doc.id}:${key}`] = value
  }
}

function clearResolvingMergeKeys() {
  Object.keys(resolvingMergeKeys).forEach(key => delete resolvingMergeKeys[key])
}

function markResolvingMergeKeys(fieldResolutions) {
  clearResolvingMergeKeys()
  for (const resolution of fieldResolutions) {
    if (resolution.action !== 'merge') continue
    resolvingMergeKeys[`${resolution.entity_type}:${resolution.entity_name}:${resolution.field}`] = true
  }
}

function syncSelectedDocFromStore(id) {
  if (!id) return
  const latest = (store.pendingDocs || []).find((doc) => doc.id === id)
  if (latest) {
    selectedDoc.value = latest
    initializeConflictSelections(latest)
    return
  }
  detailVisible.value = false
  selectedDoc.value = null
}

async function fetchLibrary() {
  if (!store.novelId) {
    libraryItems.value = []
    return
  }
  libraryLoading.value = true
  try {
    const library = await getDocumentLibrary(store.novelId)
    libraryItems.value = library.items || []
  } catch {
    libraryItems.value = []
  } finally {
    libraryLoading.value = false
  }
}

async function upload() {
  if (!selectedFiles.value.length) return
  uploading.value = true
  try {
    uploadSummary.value = await uploadDocumentsBatch(store.novelId, selectedFiles.value, 3)
    const accepted = uploadSummary.value.accepted ?? uploadSummary.value.succeeded ?? 0
    ElMessage.success(`导入任务已提交：${accepted} 个`)
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
  } finally {
    uploading.value = false
    selectedFiles.value = []
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function approve(id) {
  if (approvingPendingId.value) return
  approvingPendingId.value = id
  rememberConflictSelections(selectedDoc.value)
  const fieldResolutions = selectedDoc.value?.id === id ? buildFieldResolutions() : []
  const hasMergeResolution = fieldResolutions.some((resolution) => resolution.action === 'merge')
  if (selectedDoc.value?.id === id) {
    markResolvingMergeKeys(fieldResolutions)
  }
  try {
    await approvePending(store.novelId, id, fieldResolutions)
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
    syncSelectedDocFromStore(id)
    ElMessage.success(hasMergeResolution ? '自动合并完成' : '已批准')
  } finally {
    clearResolvingMergeKeys()
    approvingPendingId.value = ''
  }
}

async function reject(id) {
  if (rejectingPendingId.value) return
  rejectingPendingId.value = id
  try {
    await rejectPending(store.novelId, id)
    ElMessage.success('已拒绝并丢弃该记录')
    clearResolvingMergeKeys()
    if (selectedDoc.value?.id === id) {
      detailVisible.value = false
      selectedDoc.value = null
    }
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
  } finally {
    rejectingPendingId.value = ''
  }
}

async function removeFailedRecord(id) {
  if (deletingPendingId.value) return
  deletingPendingId.value = id
  try {
    await deletePendingDoc(store.novelId, id)
    ElMessage.success('已删除失败记录')
    clearResolvingMergeKeys()
    if (selectedDoc.value?.id === id) {
      detailVisible.value = false
      selectedDoc.value = null
    }
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
  } finally {
    deletingPendingId.value = ''
  }
}

async function activateStyleVersion(version) {
  if (!store.novelId || rollingBackVersion.value) return
  rollingBackVersion.value = version
  try {
    await rollbackStyleProfile(store.novelId, version)
    await fetchLibrary()
    ElMessage.success(`已切换到文风版本 v${version}`)
  } finally {
    rollingBackVersion.value = null
  }
}

function fetchIfReady() {
  if (!store.novelId) {
    libraryItems.value = []
    return
  }
  store.fetchDocuments()
  fetchLibrary()
}

function stopDocumentPolling() {
  if (documentPollTimer.value) {
    window.clearInterval(documentPollTimer.value)
    documentPollTimer.value = null
  }
}

function startDocumentPolling() {
  if (documentPollTimer.value || !store.novelId) return
  documentPollTimer.value = window.setInterval(() => {
    store.fetchDocuments()
  }, DOCUMENT_POLL_INTERVAL_MS)
}

onMounted(fetchIfReady)
onBeforeUnmount(stopDocumentPolling)
watch(() => store.novelId, () => {
  stopDocumentPolling()
  uploadSummary.value = null
  fetchIfReady()
})
watch(hasProcessingDocs, (processing) => {
  if (processing) {
    startDocumentPolling()
    return
  }
  stopDocumentPolling()
}, { immediate: true })

watch(conflictSelections, () => {
  rememberConflictSelections(selectedDoc.value)
}, { deep: true })
</script>
