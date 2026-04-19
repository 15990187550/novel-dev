<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">设定资料</h2>
    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 class="font-bold mb-3">上传设定文件</h3>
      <div class="flex items-center gap-2">
        <input ref="fileInput" type="file" accept=".txt,.md" @change="onFileChange" class="text-sm" />
        <el-button type="primary" :loading="uploading" @click="upload">上传</el-button>
      </div>
    </div>
    <div v-if="store.pendingDocs.length" class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 class="font-bold mb-3">待审批</h3>
      <el-table :data="store.pendingDocs">
        <el-table-column prop="extraction_type" label="类型" />
        <el-table-column prop="status" label="状态" />
        <el-table-column prop="created_at" label="创建时间" />
        <el-table-column label="操作">
          <template #default="{ row }"><el-button size="small" @click="approve(row.id)">批准</el-button></template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useNovelStore } from '@/stores/novel.js'
import { uploadDocument, approvePending } from '@/api.js'
import { ElMessage } from 'element-plus'

const store = useNovelStore()
const fileInput = ref(null)
const selectedFile = ref(null)
const fileContent = ref('')
const uploading = ref(false)

function onFileChange(e) {
  const file = e.target.files[0]
  if (!file) return
  selectedFile.value = file
  const reader = new FileReader()
  reader.onload = (ev) => { fileContent.value = ev.target.result }
  reader.readAsText(file)
}

async function upload() {
  if (!selectedFile.value || !fileContent.value) return
  uploading.value = true
  try {
    await uploadDocument(store.novelId, selectedFile.value.name, fileContent.value)
    ElMessage.success('上传成功')
    await store.fetchDocuments()
  } finally {
    uploading.value = false
    selectedFile.value = null
    fileContent.value = ''
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function approve(id) {
  await approvePending(store.novelId, id)
  ElMessage.success('已批准')
  await store.fetchDocuments()
}

onMounted(() => store.fetchDocuments())
</script>
