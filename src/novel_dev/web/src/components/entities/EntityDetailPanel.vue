<template>
  <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 space-y-4">
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
      <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-3">
        <div class="font-semibold">人工覆盖</div>
        <div class="grid gap-3 lg:grid-cols-2">
          <el-select v-model="manualCategory" placeholder="选择一级分类" clearable @change="handleCategoryChange">
            <el-option v-for="option in CATEGORY_OPTIONS" :key="option" :label="option" :value="option" />
          </el-select>
          <el-select
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

      <el-descriptions :column="2" border size="small">
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
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-3">
          <div class="mb-2 font-semibold">最新状态</div>
          <pre class="max-h-72 overflow-auto whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-200">{{ prettyJson(entity.latest_state) }}</pre>
        </div>
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-3">
          <div class="mb-2 font-semibold">关系摘要</div>
          <div v-if="relatedItems.length" class="space-y-2">
            <div v-for="item in relatedItems" :key="item.key" class="rounded-md bg-gray-50 dark:bg-gray-900 px-3 py-2">
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

      <div v-if="entity.search_document" class="rounded-lg border border-gray-200 dark:border-gray-700 p-3">
        <div class="mb-2 font-semibold">搜索文档</div>
        <pre class="max-h-72 overflow-auto whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-200">{{ prettyJson(entity.search_document) }}</pre>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

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
  entity: { type: Object, default: null },
  relationships: { type: Array, default: () => [] },
  title: { type: String, default: '实体详情' },
})

const emit = defineEmits(['save-classification', 'clear-override', 'reclassify', 'select-entity'])
const manualCategory = ref('')
const manualGroupName = ref('')

watch(
  () => props.entity,
  (entity) => {
    manualCategory.value = entity?.manual_category || entity?.effective_category || entity?.system_category || ''
    manualGroupName.value = entity?.manual_category
      ? (entity?.manual_group_name || '')
      : (entity?.effective_group_name || entity?.system_group_name || '')
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
