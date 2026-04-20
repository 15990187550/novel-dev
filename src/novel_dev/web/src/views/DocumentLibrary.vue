<template>
  <div class="space-y-4" v-if="store.novelId">
    <div class="grid grid-cols-[280px_1fr] gap-4">
      <!-- Left sidebar: document list -->
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700 space-y-3">
        <el-select v-model="selectedType" clearable placeholder="按类型筛选" @change="loadList" class="w-full">
          <el-option v-for="t in docTypes" :key="t" :label="t" :value="t" />
        </el-select>
        <el-menu :default-active="selectedDocId" @select="selectDoc" class="border-none">
          <el-menu-item v-for="doc in filteredDocs" :key="doc.id" :index="doc.id">
            <div class="flex flex-col">
              <span class="text-sm">{{ doc.title }}</span>
              <span class="text-xs text-gray-400">{{ doc.doc_type }} · v{{ doc.version }}</span>
            </div>
          </el-menu-item>
        </el-menu>
      </div>

      <!-- Right panel: detail/edit -->
      <div v-if="store.documentDetail" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700 space-y-4">
        <div class="flex items-center gap-3 flex-wrap">
          <el-input v-model="form.title" placeholder="标题" class="flex-1" />
          <el-select v-model="selectedVersion" placeholder="版本" @change="switchVersion" class="w-28">
            <el-option v-for="v in store.documentVersions" :key="v.id" :label="`v${v.version}`" :value="v.id" />
          </el-select>
          <el-button :loading="reindexing" @click="runReindex">重新入库</el-button>
        </div>
        <el-input v-model="form.content" type="textarea" :rows="20" placeholder="文档内容" />
        <div class="flex justify-end">
          <el-button type="primary" :loading="saving" @click="saveVersion">保存为新版本</el-button>
        </div>
      </div>
      <div v-else-if="store.novelId" class="flex items-center justify-center h-64 text-gray-400">
        选择左侧文档查看详情
      </div>
    </div>
  </div>
  <el-alert v-else title="请先选择或新建小说" type="info" show-icon />
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const route = useRoute()
const selectedType = ref('')
const selectedVersion = ref('')
const selectedDocId = ref('')
const saving = ref(false)
const reindexing = ref(false)
const form = reactive({ title: '', content: '' })

const docTypes = computed(() => [...new Set(store.documents.map(d => d.doc_type))])
const filteredDocs = computed(() => selectedType.value
  ? store.documents.filter(d => d.doc_type === selectedType.value)
  : store.documents)

async function loadList() {
  await store.fetchDocuments()
  if (selectedType.value) {
    // filteredDocs computed handles client-side filtering
  }
}

async function loadDetail(docId) {
  selectedDocId.value = docId
  await store.fetchDocumentDetail(docId)
  if (store.documentDetail) {
    await store.fetchDocumentVersions(store.documentDetail.doc_type)
    selectedVersion.value = docId
    form.title = store.documentDetail.title
    form.content = store.documentDetail.content || ''
  }
}

async function selectDoc(docId) {
  await loadDetail(docId)
}

async function switchVersion(docId) {
  await loadDetail(docId)
}

async function saveVersion() {
  saving.value = true
  try {
    const saved = await store.saveDocumentVersion(selectedDocId.value, {
      title: form.title,
      content: form.content,
    })
    selectedDocId.value = saved.id
    await loadDetail(saved.id)
    ElMessage.success('保存成功')
  } finally {
    saving.value = false
  }
}

async function runReindex() {
  reindexing.value = true
  try {
    await store.reindexDocument(selectedDocId.value)
    ElMessage.success('重新入库成功')
  } finally {
    reindexing.value = false
  }
}

onMounted(async () => {
  await loadList()
  const initialId = route.query.documentId
  if (initialId) {
    await loadDetail(initialId)
  }
})

watch(() => route.query.documentId, async (newId) => {
  if (newId && newId !== selectedDocId.value) {
    await loadDetail(newId)
  }
})
</script>
