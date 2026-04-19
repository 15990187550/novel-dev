<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">地点</h2>
    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <el-table :data="store.spacelines" row-key="id" :tree-props="{ children: 'children' }">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="narrative" label="描述" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
const store = useNovelStore()
onMounted(() => store.fetchSpacelines())
</script>
