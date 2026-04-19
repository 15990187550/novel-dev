<template>
  <div class="space-y-2">
    <el-select-v2
      v-model="selected"
      :options="options"
      placeholder="选择或输入小说"
      filterable
      allow-create
      clearable
      style="width: 100%"
    />
    <el-button type="primary" size="small" style="width: 100%" @click="load" :disabled="!selected">
      加载
    </el-button>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { listNovels } from '@/api.js'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const selected = ref('')
const options = ref([])

async function fetchNovels() {
  try {
    const res = await listNovels()
    options.value = (res.items || []).map(n => ({ value: n.novel_id, label: n.novel_id }))
  } catch {
    options.value = []
  }
}

function load() {
  if (selected.value) {
    store.loadNovel(selected.value)
  }
}

fetchNovels()

watch(() => store.novelId, (id) => {
  if (id && !options.value.find(o => o.value === id)) {
    options.value.push({ value: id, label: id })
  }
  selected.value = id
})
</script>
