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
    <div class="flex gap-2">
      <el-button type="primary" size="small" class="flex-1" @click="load" :disabled="!selected">
        加载
      </el-button>
      <el-button type="success" size="small" @click="showCreateDialog = true">
        新建
      </el-button>
    </div>

    <el-dialog v-model="showCreateDialog" title="新建小说" width="400px" :close-on-click-modal="false">
      <el-form :model="createForm" @submit.prevent="doCreate">
        <el-form-item label="标题">
          <el-input v-model="createForm.title" placeholder="请输入小说标题" @keyup.enter="doCreate" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="!createForm.title.trim()" @click="doCreate">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { listNovels, createNovel } from '@/api.js'
import { useNovelStore } from '@/stores/novel.js'
import { ElMessage } from 'element-plus'

const store = useNovelStore()
const selected = ref('')
const options = ref([])
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({ title: '' })

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

async function doCreate() {
  const title = createForm.value.title.trim()
  if (!title) return
  creating.value = true
  try {
    const res = await createNovel(title)
    ElMessage.success('小说创建成功')
    showCreateDialog.value = false
    createForm.value.title = ''
    await fetchNovels()
    if (res.novel_id) {
      store.loadNovel(res.novel_id)
    }
  } catch (e) {
    // api interceptor already shows error
  } finally {
    creating.value = false
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
