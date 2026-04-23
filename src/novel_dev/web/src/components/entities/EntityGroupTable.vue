<template>
  <div class="entity-group-table surface-card p-4 space-y-3">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 class="font-bold">{{ title }}</h3>
        <p class="entity-group-table__meta text-sm">
          {{ selectedNodeLabel ? `当前目录：${selectedNodeLabel}` : '请选择左侧目录节点' }}
        </p>
      </div>
      <div class="entity-group-table__meta flex flex-wrap gap-2 text-xs">
        <span>分组 {{ groupCount }}</span>
        <span>实体 {{ totalCount }}</span>
      </div>
    </div>

    <el-empty v-if="showEmptyState" class="entity-group-table__empty" description="该目录下暂无实体" />

    <el-table v-else :data="items" class="entity-group-table__table" style="width: 100%" @row-click="emit('select-entity', $event)">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="分类 / 分组" min-width="220">
        <template #default="{ row }">
          <div class="space-y-1 text-sm">
            <div>{{ row.effective_category || row.system_category || row.type || '-' }}</div>
            <div class="entity-group-table__subtext">
              {{ currentGroupLabel(row) }}
            </div>
            <div class="entity-group-table__subtext entity-group-table__subtext--soft text-xs">
              自动建议：{{ row.system_category || '-' }} / {{ row.system_group_name || '-' }}
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.classification_status)" size="small">
            {{ statusLabel(row.classification_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="别名" min-width="180">
        <template #default="{ row }">
          <div v-if="row.aliases?.length" class="flex flex-wrap gap-1">
            <el-tag v-for="alias in row.aliases" :key="alias" size="small" type="info">{{ alias }}</el-tag>
          </div>
          <span v-else class="entity-group-table__empty">-</span>
        </template>
      </el-table-column>
      <el-table-column label="信息摘要" min-width="280">
        <template #default="{ row }">
          <div class="entity-group-table__summary space-y-1 text-sm">
            <div v-if="row.search_match_reason">命中：{{ row.search_match_reason }}</div>
            <div v-else-if="row.classification_reason">系统依据：{{ stringifyReason(row.classification_reason) }}</div>
            <div v-else-if="summaryText(row.latest_state)">摘要：{{ summaryText(row.latest_state) }}</div>
            <div v-else class="entity-group-table__empty">暂无摘要</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="快速调整" min-width="320">
        <template #default="{ row }">
          <div class="space-y-2" @click.stop>
            <el-select
              class="entity-group-table__select"
              v-model="draftFor(row).manualCategory"
              placeholder="选择一级分类"
              clearable
              style="width: 100%"
              @change="handleCategoryChange(row)"
            >
              <el-option v-for="option in CATEGORY_OPTIONS" :key="option" :label="option" :value="option" />
            </el-select>
            <el-select
              class="entity-group-table__select"
              v-model="draftFor(row).manualGroupName"
              placeholder="选择或输入二级分组"
              clearable
              filterable
              allow-create
              default-first-option
              style="width: 100%"
            >
              <el-option
                v-for="option in groupOptionsFor(row)"
                :key="option"
                :label="option"
                :value="option"
              />
            </el-select>
            <div class="entity-group-table__quick-actions flex flex-wrap gap-2">
              <el-button size="small" type="primary" @click="saveDraft(row)">保存</el-button>
              <el-button size="small" @click="emit('clear-override', row)">清除覆盖</el-button>
              <el-button size="small" link type="primary" @click="emit('select-entity', row)">详情</el-button>
            </div>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const CATEGORY_OPTIONS = ['人物', '势力', '功法', '法宝神兵', '天材地宝', '其他']
const GROUP_OPTIONS = {
  人物: ['主角', '主角阵营', '反派', '盟友', '师门', '家族', '路人'],
  势力: ['宗门', '朝廷', '世家', '组织', '异族', '敌对势力'],
  功法: ['主修', '辅修', '禁术', '传承', '通用'],
  法宝神兵: ['本命', '常用', '传承', '敌对', '特殊'],
  天材地宝: ['修炼', '疗伤', '突破', '炼器', '炼丹'],
  其他: ['世界规则', '地点', '事件', '概念'],
}

const props = defineProps({
  title: { type: String, default: '实体列表' },
  items: { type: Array, default: () => [] },
  selectedNodeLabel: { type: String, default: '' },
  groupCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 },
  showEmptyState: { type: Boolean, default: false },
})

const emit = defineEmits(['select-entity', 'save-classification', 'clear-override'])
const drafts = reactive({})

function slugify(value) {
  return (value || '')
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^a-z0-9\u4e00-\u9fa5-]/g, '')
}

function draftFor(row) {
  if (!drafts[row.entity_id]) {
    drafts[row.entity_id] = {
      manualCategory: row.manual_category || row.effective_category || row.system_category || '',
      manualGroupName: row.manual_category
        ? (row.manual_group_name || '')
        : (row.effective_group_name || row.system_group_name || ''),
    }
  }
  return drafts[row.entity_id]
}

function groupOptionsFor(row) {
  const category = draftFor(row).manualCategory || row.effective_category || row.system_category || '其他'
  const options = new Set(GROUP_OPTIONS[category] || [])
  for (const value of [row.effective_group_name, row.manual_group_name]) {
    if (value) options.add(value)
  }
  if (row.system_category === category && row.system_group_name) options.add(row.system_group_name)
  return [...options]
}

function handleCategoryChange(row) {
  draftFor(row).manualGroupName = ''
}

function currentGroupLabel(row) {
  if (row.effective_group_name) return row.effective_group_name
  if (row.manual_category) return row.manual_group_name || '未分组'
  return row.system_group_name || '-'
}

function saveDraft(row) {
  const draft = draftFor(row)
  emit('save-classification', row, {
    manual_category: draft.manualCategory || null,
    manual_group_name: draft.manualGroupName || null,
    manual_group_slug: draft.manualGroupName ? slugify(draft.manualGroupName) : null,
    clear_manual_override: !draft.manualCategory,
  })
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

function stringifyReason(reason) {
  if (!reason) return '-'
  return typeof reason === 'string' ? reason : JSON.stringify(reason)
}

function summaryText(state) {
  if (!state || typeof state !== 'object') return ''
  const keys = ['name', 'identity', 'goal', 'personality', 'description', 'significance']
  for (const key of keys) {
    const value = state[key]
    if (value != null && value !== '') return `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`
  }
  return ''
}
</script>

<style scoped>
.entity-group-table {
  background: var(--entities-panel-bg);
  border: 1px solid var(--entities-panel-border);
}

.entity-group-table__meta {
  color: var(--entities-text-muted);
}

.entity-group-table__subtext {
  color: var(--entities-text-muted);
}

.entity-group-table__subtext--soft {
  color: var(--entities-text-soft);
}

.entity-group-table__summary {
  color: var(--entities-text);
}

.entity-group-table__empty {
  color: var(--entities-text-soft);
}

.entity-group-table__table {
  --el-table-border-color: var(--entities-panel-border);
  --el-table-border: 1px solid var(--entities-panel-border);
  --el-table-header-bg-color: var(--entities-panel-bg-soft);
  --el-table-tr-bg-color: var(--entities-panel-bg);
  --el-table-row-hover-bg-color: var(--entities-panel-bg-soft);
  --el-table-bg-color: var(--entities-panel-bg);
  --el-table-expanded-cell-bg-color: var(--entities-panel-bg);
  --el-table-header-text-color: var(--entities-text-soft);
  --el-table-text-color: var(--entities-text);
  --el-fill-color-lighter: var(--entities-panel-bg-soft);
  --el-fill-color-blank: transparent;
  border-radius: 0.9rem;
  overflow: hidden;
}

.entity-group-table__table :deep(.el-table__inner-wrapper::before),
.entity-group-table__table :deep(.el-table::before) {
  display: none;
}

.entity-group-table__table :deep(th.el-table__cell) {
  background: var(--entities-panel-bg-soft);
  font-weight: 700;
}

.entity-group-table__table :deep(td.el-table__cell),
.entity-group-table__table :deep(tr) {
  background: var(--entities-panel-bg);
}

.entity-group-table__select :deep(.el-select__wrapper) {
  background: var(--entities-panel-bg-soft);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}

.entity-group-table__select :deep(.el-select__placeholder),
.entity-group-table__select :deep(.el-select__selected-item),
.entity-group-table__select :deep(.el-input__inner) {
  color: var(--entities-text);
}

.entity-group-table__empty :deep(.el-empty__description) {
  color: var(--entities-text-soft);
}
</style>
