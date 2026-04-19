<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">实体百科</h2>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="人物" name="character" />
      <el-tab-pane label="物品" name="item" />
      <el-tab-pane label="其他" name="other" />
    </el-tabs>
    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="filtered" style="width: 100%">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column prop="current_version" label="版本" width="80" />
        <el-table-column label="最新状态">
          <template #default="{ row }"><pre class="text-xs whitespace-pre-wrap max-h-24 overflow-auto">{{ JSON.stringify(row.latest_state, null, 2) }}</pre></template>
        </el-table-column>
      </el-table>
    </div>
    <EntityGraph :entities="store.entities" :relationships="[]" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import EntityGraph from '@/components/EntityGraph.vue'
const store = useNovelStore()
const activeTab = ref('character')
const filtered = computed(() => store.entities.filter(e => e.type === activeTab.value))
onMounted(() => store.fetchEntities())
</script>
