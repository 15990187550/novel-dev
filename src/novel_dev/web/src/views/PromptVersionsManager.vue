<template>
  <div class="prompt-versions-manager" data-testid="prompt-versions-manager">
    <header class="header">
      <h2>Prompt 版本管理</h2>
      <div class="controls">
        <select v-model="selectedAgent" data-testid="agent-select">
          <option v-for="a in AGENT_NAMES" :key="a" :value="a">{{ a }}</option>
        </select>
        <button @click="showCreate = true" data-testid="create-btn" class="primary">
          创建新版本
        </button>
      </div>
    </header>

    <div v-if="!versions.length" data-testid="empty-state" class="empty">
      <p>此 agent 尚无 prompt。可从系统默认导入。</p>
      <button @click="bootstrap" data-testid="bootstrap-btn">导入默认</button>
    </div>

    <table v-else class="versions-table" data-testid="versions-table">
      <thead>
        <tr>
          <th>版本</th>
          <th>状态</th>
          <th>调用次数</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="v in versions" :key="v.version" data-testid="version-row">
          <td>{{ v.version }}</td>
          <td>
            <span v-if="v.is_active" class="badge active" data-testid="active-badge">active</span>
            <span v-else class="badge inactive">inactive</span>
          </td>
          <td>{{ v.sample_count }}</td>
          <td>{{ formatDate(v.created_at) }}</td>
          <td class="actions">
            <button data-testid="view-btn" @click="viewContent(v)">查看</button>
            <button
              v-if="!v.is_active"
              data-testid="set-active-btn"
              @click="setActive(v)"
            >设 active</button>
            <button
              v-if="!v.is_active"
              data-testid="delete-btn"
              @click="deleteVersion(v)"
            >删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 创建版本弹窗 -->
    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal">
        <h3>创建新版本</h3>
        <label>版本号 <input v-model="newVersion" placeholder="v1.1" data-testid="new-version-input" /></label>
        <label>内容 <textarea v-model="newContent" rows="10" data-testid="new-content-input"></textarea></label>
        <label><input type="checkbox" v-model="newIsActive" data-testid="new-active-checkbox" /> 设为 active</label>
        <div class="modal-actions">
          <button @click="showCreate = false">取消</button>
          <button @click="createVersion" data-testid="create-confirm" class="primary">创建</button>
        </div>
      </div>
    </div>

    <!-- 查看内容弹窗 -->
    <div v-if="showView" class="modal-backdrop" @click.self="showView = false">
      <div class="modal">
        <h3>{{ viewTarget?.version }}</h3>
        <pre data-testid="view-content" class="content-pre">{{ viewTarget?.content }}</pre>
        <div class="modal-actions">
          <button @click="showView = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import axios from 'axios'

const AGENT_NAMES = [
  'brainstorm', 'volume_planner', 'context_agent',
  'writer', 'critic', 'editor',
  'fast_review', 'librarian', 'root_cause_analyzer'
]

const selectedAgent = ref('writer')
const versions = ref([])
const showCreate = ref(false)
const showView = ref(false)
const viewTarget = ref(null)
const newVersion = ref('')
const newContent = ref('')
const newIsActive = ref(false)

const fetchVersions = async () => {
  try {
    const resp = await axios.get(`/api/prompts/${selectedAgent.value}/versions`)
    versions.value = resp.data?.versions || []
  } catch (e) {
    console.error('fetchVersions failed', e)
    versions.value = []
  }
}

const setActive = async (v) => {
  try {
    await axios.patch(`/api/prompts/${selectedAgent.value}/versions/${v.version}`, { is_active: true })
  } catch (e) {
    console.error('setActive failed', e)
  }
  await fetchVersions()
}

const deleteVersion = async (v) => {
  if (!confirm(`确认删除版本 ${v.version}?`)) return
  try {
    await axios.delete(`/api/prompts/${selectedAgent.value}/versions/${v.version}`)
  } catch (e) {
    console.error('deleteVersion failed', e)
  }
  await fetchVersions()
}

const viewContent = (v) => {
  viewTarget.value = v
  showView.value = true
}

const createVersion = async () => {
  try {
    await axios.post(`/api/prompts/${selectedAgent.value}/versions`, {
      version: newVersion.value,
      content: newContent.value,
      is_active: newIsActive.value,
    })
  } catch (e) {
    console.error('createVersion failed', e)
  }
  showCreate.value = false
  newVersion.value = ''
  newContent.value = ''
  newIsActive.value = false
  await fetchVersions()
}

const bootstrap = async () => {
  // No backend endpoint to seed defaults; trigger a refetch.
  await fetchVersions()
}

const formatDate = (iso) => {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

onMounted(fetchVersions)
watch(selectedAgent, fetchVersions)
</script>

<style scoped>
.prompt-versions-manager { padding: 1rem; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.controls { display: flex; gap: 0.5rem; }
.empty { padding: 2rem; text-align: center; color: #666; }
.versions-table { width: 100%; border-collapse: collapse; }
.versions-table th, .versions-table td { padding: 0.5rem; border-bottom: 1px solid #eee; text-align: left; }
.actions { display: flex; gap: 0.25rem; }
.badge { padding: 0.125rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; }
.badge.active { background: #dcfce7; color: #166534; }
.badge.inactive { background: #f3f4f6; color: #6b7280; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; padding: 1.5rem; border-radius: 0.5rem; max-width: 600px; width: 90%; }
.modal label { display: block; margin-bottom: 0.5rem; }
.modal input, .modal textarea { width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 0.25rem; }
.modal-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
.content-pre { white-space: pre-wrap; max-height: 400px; overflow-y: auto; background: #f9fafb; padding: 1rem; }
button { padding: 0.375rem 0.75rem; border: 1px solid #ddd; background: white; border-radius: 0.25rem; cursor: pointer; }
button.primary { background: #2563eb; color: white; border-color: #2563eb; }
</style>
