<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">实体百科</h2>
    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />
    <template v-else>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="人物" name="character" />
        <el-tab-pane label="物品" name="item" />
        <el-tab-pane label="其他" name="other" />
      </el-tabs>
      <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
        <el-table :data="filtered" style="width: 100%">
          <el-table-column prop="name" label="名称" width="160" />
          <el-table-column prop="type" label="类型" width="100" />
          <el-table-column prop="current_version" label="版本" width="80" />
          <el-table-column label="实体信息" min-width="520">
            <template #default="{ row }">
              <div v-if="row.type === 'character'" class="space-y-2 text-sm">
                <div v-for="field in characterFields(row.latest_state)" :key="field.label">
                  <span class="font-semibold text-gray-700 dark:text-gray-200">{{ field.label }}：</span>
                  <span class="text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{{ field.value }}</span>
                </div>
                <div v-if="otherCharacterFields(row.latest_state).length">
                  <div class="font-semibold text-gray-700 dark:text-gray-200 mb-1">其他信息：</div>
                  <pre class="text-xs whitespace-pre-wrap overflow-auto bg-gray-50 dark:bg-gray-900 rounded p-2">{{ JSON.stringify(otherCharacterState(row.latest_state), null, 2) }}</pre>
                </div>
              </div>
              <div v-else class="space-y-2 text-sm">
                <div v-for="field in genericFields(row.latest_state)" :key="field.label">
                  <span class="font-semibold text-gray-700 dark:text-gray-200">{{ field.label }}：</span>
                  <span class="text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{{ field.value }}</span>
                </div>
                <pre v-if="!genericFields(row.latest_state).length" class="text-xs whitespace-pre-wrap max-h-24 overflow-auto">{{ JSON.stringify(row.latest_state, null, 2) }}</pre>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <EntityGraph :entities="store.entities" :relationships="store.entityRelationships" />
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import EntityGraph from '@/components/EntityGraph.vue'

const store = useNovelStore()
const activeTab = ref('character')
const filtered = computed(() => store.entities.filter(e => activeTab.value === 'other' ? !['character', 'item'].includes(e.type) : e.type === activeTab.value))

const characterFieldLabels = {
  identity: '身份',
  personality: '性格',
  goal: '目标',
  appearance: '外貌',
  background: '背景',
  ability: '能力',
  abilities: '能力',
  realm: '境界',
  relationship: '关系',
  relationships: '关系',
}

const genericFieldLabels = {
  description: '描述',
  significance: '重要性',
  usage: '用途',
  effect: '效果',
  origin: '来历',
}

function normalizeValue(value) {
  if (value == null || value === '') return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function fieldsFromMap(state, labels) {
  if (!state) return []
  return Object.entries(labels)
    .map(([key, label]) => ({ key, label, value: normalizeValue(state[key]) }))
    .filter(field => field.value)
}

function characterFields(state) {
  return [{ label: '名称', value: state?.name || '' }, ...fieldsFromMap(state, characterFieldLabels)].filter(field => field.value)
}

function genericFields(state) {
  return [{ label: '名称', value: state?.name || '' }, ...fieldsFromMap(state, genericFieldLabels)].filter(field => field.value)
}

function otherCharacterState(state) {
  if (!state) return {}
  const excluded = new Set(['name', ...Object.keys(characterFieldLabels)])
  return Object.fromEntries(Object.entries(state).filter(([key, value]) => !excluded.has(key) && value != null && value !== ''))
}

function otherCharacterFields(state) {
  return Object.keys(otherCharacterState(state))
}

function fetchIfReady() {
  if (store.novelId) store.fetchEntities()
}

onMounted(fetchIfReady)
watch(() => store.novelId, fetchIfReady)
</script>
