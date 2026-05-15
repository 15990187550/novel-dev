<template>
  <div class="space-y-3">
    <div class="flex items-start justify-between gap-3">
      <div>
        <div class="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Workspace</div>
        <div class="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-100">小说工作区</div>
      </div>
      <span class="rounded-full border border-slate-200 bg-white/70 px-2.5 py-1 text-[11px] font-medium text-slate-500 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
        {{ options.length }} 部
      </span>
    </div>

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

    <div class="rounded-2xl border border-slate-200/80 bg-white/70 px-3 py-2.5 text-xs leading-5 text-slate-500 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300">
      先选定小说，再进入资料、卷纲和正文模块，避免不同项目上下文串线。
    </div>

    <el-dialog
      v-model="showCreateDialog"
      title="新建小说"
      width="400px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form :model="createForm" @submit.prevent="doCreate">
        <el-form-item label="标题">
          <el-input v-model="createForm.title" placeholder="请输入小说标题" @keyup.enter="doCreate" />
        </el-form-item>
        <el-form-item label="一级分类">
          <el-select
            v-model="createForm.primary_category_slug"
            placeholder="请选择一级分类"
            style="width: 100%"
          >
            <el-option
              v-for="category in categoryOptions"
              :key="category.slug"
              :label="category.name"
              :value="category.slug"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="二级分类">
          <el-select
            v-model="createForm.secondary_category_slug"
            placeholder="请选择二级分类"
            :disabled="!createForm.primary_category_slug"
            style="width: 100%"
          >
            <el-option
              v-for="category in secondaryCategoryOptions"
              :key="category.slug"
              :label="category.name"
              :value="category.slug"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="!canCreate" @click="doCreate">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { listNovels, createNovel, getNovelCategories } from '@/api.js'
import { useNovelStore } from '@/stores/novel.js'
import { ElMessage } from 'element-plus'

const store = useNovelStore()
const selected = ref('')
const options = ref([])
const categoryOptions = ref([])
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({ title: '', primary_category_slug: '', secondary_category_slug: '' })

const selectedPrimaryCategory = computed(() =>
  categoryOptions.value.find(category => category.slug === createForm.value.primary_category_slug)
)
const secondaryCategoryOptions = computed(() => selectedPrimaryCategory.value?.children || [])
const canCreate = computed(() =>
  Boolean(
    createForm.value.title.trim() &&
    createForm.value.primary_category_slug &&
    createForm.value.secondary_category_slug
  )
)

async function fetchNovels() {
  try {
    const res = await listNovels()
    options.value = (res.items || []).map(n => ({ value: n.novel_id, label: n.title || n.novel_id }))
  } catch {
    options.value = []
  }
}

async function fetchCategories() {
  try {
    const res = await getNovelCategories()
    categoryOptions.value = Array.isArray(res) ? res : (res.items || [])
  } catch {
    categoryOptions.value = []
  }
}

function load() {
  if (selected.value) {
    store.loadNovel(selected.value)
  }
}

async function doCreate() {
  const title = createForm.value.title.trim()
  if (!canCreate.value) return
  creating.value = true
  try {
    const res = await createNovel({
      title,
      primary_category_slug: createForm.value.primary_category_slug,
      secondary_category_slug: createForm.value.secondary_category_slug,
    })
    ElMessage.success('小说创建成功')
    showCreateDialog.value = false
    createForm.value = { title: '', primary_category_slug: '', secondary_category_slug: '' }
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
fetchCategories()

watch(() => createForm.value.primary_category_slug, () => {
  createForm.value.secondary_category_slug = ''
})

watch(() => store.novelId, (id) => {
  if (id && !options.value.find(o => o.value === id)) {
    options.value.push({ value: id, label: store.novelTitle || id })
  }
  selected.value = id
})

watch(() => store.novelTitle, (title) => {
  if (!store.novelId || !title) return
  const option = options.value.find(o => o.value === store.novelId)
  if (option) {
    option.label = title
  } else {
    options.value.push({ value: store.novelId, label: title })
  }
})
</script>
