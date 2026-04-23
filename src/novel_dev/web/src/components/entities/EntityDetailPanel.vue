<template>
  <div class="entity-detail-panel surface-card p-4 space-y-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 class="font-bold">{{ title }}</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          {{ entity ? '实体详情与分类信息' : '请选择一个实体查看详情' }}
        </p>
      </div>
      <div v-if="entity" class="flex flex-wrap gap-2">
        <el-tag :type="statusTagType(entity.classification_status)" size="small">{{ statusLabel(entity.classification_status) }}</el-tag>
        <el-tag v-if="entity.system_needs_review" type="warning" size="small">系统待确认</el-tag>
      </div>
    </div>

    <el-empty v-if="!entity" description="暂无实体详情" />

    <template v-else>
      <div class="flex flex-wrap justify-end gap-2">
        <el-button type="primary" plain @click="openEditDialog">编辑实体</el-button>
        <el-button type="danger" plain @click="emit('delete-entity', entity)">删除实体</el-button>
      </div>

      <div class="entity-detail-panel__section entity-detail-panel__override rounded-lg border p-3 space-y-3">
        <div class="font-semibold">人工覆盖</div>
        <div class="grid gap-3 lg:grid-cols-2">
          <el-select class="entity-detail-panel__select" v-model="manualCategory" placeholder="选择一级分类" clearable @change="handleCategoryChange">
            <el-option v-for="option in CATEGORY_OPTIONS" :key="option" :label="option" :value="option" />
          </el-select>
          <el-select
            class="entity-detail-panel__select"
            v-model="manualGroupName"
            placeholder="选择或输入二级分组"
            clearable
            filterable
            allow-create
            default-first-option
          >
            <el-option v-for="option in groupOptions" :key="option" :label="option" :value="option" />
          </el-select>
        </div>
        <div class="flex flex-wrap gap-2">
          <el-button type="primary" @click="saveClassification">保存覆盖</el-button>
          <el-button @click="emit('clear-override', entity)">清除覆盖</el-button>
          <el-button @click="emit('reclassify', entity)">重新判断</el-button>
        </div>
      </div>

      <el-descriptions :column="2" border size="small" class="entity-detail-panel__descriptions">
        <el-descriptions-item label="名称">{{ entity.name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ entity.type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="版本">{{ entity.current_version ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="别名">
          <span v-if="entity.aliases?.length">{{ entity.aliases.join('、') }}</span>
          <span v-else class="text-gray-400">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="系统分类">{{ entity.system_category || '-' }}</el-descriptions-item>
        <el-descriptions-item label="人工分类">{{ entity.manual_category || '-' }}</el-descriptions-item>
        <el-descriptions-item label="系统分组">{{ entity.system_group_name || entity.system_group_slug || '-' }}</el-descriptions-item>
        <el-descriptions-item label="人工分组">{{ entity.manual_group_name || entity.manual_group_slug || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-alert
        class="entity-detail-panel__reason"
        v-if="entity.classification_reason"
        title="分类依据"
        type="info"
        show-icon
        :closable="false"
      >
        <template #default>
          <pre class="mt-2 whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-300">{{ prettyJson(entity.classification_reason) }}</pre>
        </template>
      </el-alert>

      <div class="grid gap-3 lg:grid-cols-2">
        <div class="entity-detail-panel__section rounded-lg border p-3">
          <div class="mb-2 font-semibold">最新状态</div>
          <pre class="max-h-72 overflow-auto whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-200">{{ prettyJson(entity.latest_state) }}</pre>
        </div>
        <div class="entity-detail-panel__section rounded-lg border p-3">
          <div class="mb-2 font-semibold">关系摘要</div>
          <div v-if="relatedItems.length" class="space-y-2">
            <div v-for="item in relatedItems" :key="item.key" class="entity-detail-panel__relation rounded-md px-3 py-2">
              <div class="flex items-center justify-between gap-2">
                <div class="font-medium">{{ item.label }}</div>
                <el-button link type="primary" @click="emit('select-entity', item.otherEntityId)">查看关联实体</el-button>
              </div>
              <div class="text-xs text-gray-500 dark:text-gray-400">{{ item.detail }}</div>
            </div>
          </div>
          <div v-else class="text-sm text-gray-400">暂无关系数据</div>
        </div>
      </div>

      <div v-if="entity.search_document" class="entity-detail-panel__section rounded-lg border p-3">
        <div class="mb-2 font-semibold">搜索文档</div>
        <pre class="max-h-72 overflow-auto whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-200">{{ prettyJson(entity.search_document) }}</pre>
      </div>

      <el-dialog v-model="editDialogVisible" title="编辑实体" width="640px" class="entity-detail-panel__dialog">
        <div class="space-y-4">
          <div class="grid gap-3 md:grid-cols-2">
            <el-input class="entity-detail-panel__input" v-model="editForm.name" placeholder="实体名称">
              <template #prepend>名称</template>
            </el-input>
            <el-input class="entity-detail-panel__input" v-model="editForm.type" placeholder="实体类型">
              <template #prepend>类型</template>
            </el-input>
          </div>

          <el-input
            class="entity-detail-panel__input"
            v-model="editForm.aliasesText"
            placeholder="多个别名请用中文逗号、英文逗号或换行分隔"
          >
            <template #prepend>别名</template>
          </el-input>

          <div class="grid gap-3 md:grid-cols-2">
            <el-input
              v-for="field in EDITABLE_STATE_FIELDS"
              class="entity-detail-panel__input"
              :key="field.key"
              v-model="editForm.stateFields[field.key]"
              :placeholder="field.label"
            >
              <template #prepend>{{ field.label }}</template>
            </el-input>
          </div>
        </div>

        <template #footer>
          <div class="flex justify-end gap-2">
            <el-button @click="editDialogVisible = false">取消</el-button>
            <el-button type="primary" @click="saveEntity">保存修改</el-button>
          </div>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

const CATEGORY_OPTIONS = ['人物', '势力', '功法', '法宝神兵', '天材地宝', '其他']
const GROUP_OPTIONS = {
  人物: ['主角', '主角阵营', '反派', '盟友', '师门', '家族', '路人'],
  势力: ['宗门', '朝廷', '世家', '组织', '异族', '敌对势力'],
  功法: ['主修', '辅修', '禁术', '传承', '通用'],
  法宝神兵: ['本命', '常用', '传承', '敌对', '特殊'],
  天材地宝: ['修炼', '疗伤', '突破', '炼器', '炼丹'],
  其他: ['世界规则', '地点', '事件', '概念'],
}

const EDITABLE_STATE_FIELDS = [
  { key: 'identity', label: '身份' },
  { key: 'personality', label: '性格' },
  { key: 'goal', label: '目标' },
  { key: 'appearance', label: '外貌' },
  { key: 'background', label: '背景' },
  { key: 'ability', label: '能力' },
  { key: 'realm', label: '境界' },
  { key: 'resources', label: '资源' },
  { key: 'secrets', label: '秘密' },
  { key: 'conflict', label: '冲突' },
  { key: 'arc', label: '人物弧光' },
  { key: 'notes', label: '备注' },
  { key: 'description', label: '描述' },
  { key: 'significance', label: '重要性' },
]

const props = defineProps({
  entity: { type: Object, default: null },
  relationships: { type: Array, default: () => [] },
  title: { type: String, default: '实体详情' },
})

const emit = defineEmits(['save-classification', 'clear-override', 'reclassify', 'save-entity', 'delete-entity', 'select-entity'])
const manualCategory = ref('')
const manualGroupName = ref('')
const editDialogVisible = ref(false)
const editForm = reactive({
  name: '',
  type: '',
  aliasesText: '',
  stateFields: Object.fromEntries(EDITABLE_STATE_FIELDS.map((field) => [field.key, ''])),
})

watch(
  () => props.entity,
  (entity) => {
    manualCategory.value = entity?.manual_category || entity?.effective_category || entity?.system_category || ''
    manualGroupName.value = entity?.manual_category
      ? (entity?.manual_group_name || '')
      : (entity?.effective_group_name || entity?.system_group_name || '')
    resetEditForm(entity)
  },
  { immediate: true }
)

const groupOptions = computed(() => {
  const category = manualCategory.value || props.entity?.effective_category || props.entity?.system_category || '其他'
  const options = new Set(GROUP_OPTIONS[category] || [])
  for (const value of [props.entity?.effective_group_name, props.entity?.manual_group_name]) {
    if (value) options.add(value)
  }
  if (props.entity?.system_category === category && props.entity?.system_group_name) {
    options.add(props.entity.system_group_name)
  }
  return [...options]
})

const relatedItems = computed(() => {
  if (!props.entity?.entity_id) return []
  return (props.relationships || [])
    .filter(rel => rel.source_id === props.entity.entity_id || rel.target_id === props.entity.entity_id)
    .slice(0, 8)
    .map((rel, index) => {
      const isSource = rel.source_id === props.entity.entity_id
      const direction = isSource ? '→' : '←'
      return {
        key: `${rel.source_id}:${rel.target_id}:${rel.relation_type}:${index}`,
        otherEntityId: isSource ? rel.target_id : rel.source_id,
        label: `${direction} ${rel.relation_type || '关联'}`,
        detail: `${rel.source_id || '-'} ${direction} ${rel.target_id || '-'}${rel.is_inferred ? ' · 推断' : ''}`,
      }
    })
})

function slugify(value) {
  return (value || '')
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^a-z0-9\u4e00-\u9fa5-]/g, '')
}

function saveClassification() {
  if (!props.entity) return
  emit('save-classification', props.entity, {
    manual_category: manualCategory.value || null,
    manual_group_name: manualGroupName.value || null,
    manual_group_slug: manualGroupName.value ? slugify(manualGroupName.value) : null,
    clear_manual_override: !manualCategory.value,
  })
}

function handleCategoryChange() {
  manualGroupName.value = ''
}

function openEditDialog() {
  resetEditForm(props.entity)
  editDialogVisible.value = true
}

function resetEditForm(entity) {
  editForm.name = entity?.name || ''
  editForm.type = entity?.type || ''
  editForm.aliasesText = (entity?.aliases || []).join('，')
  for (const field of EDITABLE_STATE_FIELDS) {
    const value = entity?.latest_state?.[field.key]
    editForm.stateFields[field.key] = value == null ? '' : String(value)
  }
}

function saveEntity() {
  if (!props.entity) return
  const aliases = editForm.aliasesText
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  const stateFields = {}
  for (const field of EDITABLE_STATE_FIELDS) {
    stateFields[field.key] = editForm.stateFields[field.key] || ''
  }
  emit('save-entity', props.entity, {
    name: editForm.name.trim(),
    type: editForm.type.trim(),
    aliases,
    state_fields: stateFields,
  })
  editDialogVisible.value = false
}

function prettyJson(value) {
  if (value == null || value === '') return '-'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function statusLabel(status) {
  const labels = {
    manual_override: '人工覆盖',
    needs_review: '待确认',
    auto: '自动',
  }
  return labels[status] || status || '自动'
}

function statusTagType(status) {
  if (status === 'manual_override') return 'success'
  if (status === 'needs_review') return 'warning'
  return 'info'
}
</script>

<style scoped>
.entity-detail-panel {
  border: 1px solid var(--entities-panel-border);
  background: var(--entities-panel-bg);
  color: var(--entities-text);
}

.entity-detail-panel__section {
  border-color: var(--entities-panel-border);
  background: var(--entities-panel-bg-soft);
  color: var(--entities-text);
}

.entity-detail-panel__override {
  border-color: var(--entities-panel-border-strong);
  background: var(--entities-panel-bg-muted);
}

.entity-detail-panel__relation {
  border: 1px solid var(--entities-panel-border);
  background: var(--entities-panel-bg-muted);
  color: var(--entities-text);
}

.entity-detail-panel__descriptions {
  --el-descriptions-table-border: 1px solid var(--entities-panel-border);
  --el-descriptions-item-bordered-label-background: var(--entities-grid-label-bg);
  --el-descriptions-item-bordered-content-background: var(--entities-grid-content-bg);
  --el-text-color-regular: var(--entities-text);
  --el-text-color-primary: var(--entities-text);
  --el-border-color-lighter: var(--entities-panel-border);
  background: var(--entities-panel-bg-soft);
  color: var(--entities-text);
}

.entity-detail-panel__descriptions :deep(.el-descriptions__label.el-descriptions__cell.is-bordered-label) {
  color: var(--entities-text-muted);
}

.entity-detail-panel__descriptions :deep(.el-descriptions__content.el-descriptions__cell.is-bordered-content) {
  color: var(--entities-text);
}

.entity-detail-panel__reason {
  --el-alert-bg-color: var(--entities-info-bg);
  --el-alert-border-color: var(--entities-panel-border-strong);
  --el-alert-title-font-color: var(--entities-text);
  --el-alert-description-font-color: var(--entities-text-muted);
  background: var(--entities-info-bg);
  border: 1px solid var(--entities-panel-border-strong);
  color: var(--entities-text);
}

.entity-detail-panel__reason :deep(.el-alert__title),
.entity-detail-panel__reason :deep(.el-alert__description),
.entity-detail-panel__reason :deep(.el-alert__content) {
  color: var(--entities-text);
}

.entity-detail-panel__dialog :deep(.el-dialog),
.entity-detail-panel__dialog :deep(.el-overlay-dialog .el-dialog) {
  background: var(--entities-panel-bg);
  border: 1px solid var(--entities-panel-border);
}

.entity-detail-panel__dialog :deep(.el-dialog__header),
.entity-detail-panel__dialog :deep(.el-dialog__body),
.entity-detail-panel__dialog :deep(.el-dialog__footer) {
  background: var(--entities-panel-bg);
  color: var(--entities-text);
}

.entity-detail-panel__select :deep(.el-select__wrapper) {
  background: var(--entities-panel-bg-soft);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}

.entity-detail-panel__select :deep(.el-select__placeholder),
.entity-detail-panel__select :deep(.el-select__selected-item),
.entity-detail-panel__select :deep(.el-input__inner) {
  color: var(--entities-text);
}

.entity-detail-panel__input :deep(.el-input__wrapper) {
  background: var(--entities-panel-bg-soft);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}

.entity-detail-panel__input :deep(.el-input-group__prepend) {
  background: var(--entities-panel-bg-muted);
  color: var(--entities-text-muted);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}

.entity-detail-panel__input :deep(.el-input__inner) {
  color: var(--entities-text);
}
</style>
