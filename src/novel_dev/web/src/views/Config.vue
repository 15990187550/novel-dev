<template>
  <div class="space-y-4 h-full flex flex-col">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-bold">模型配置</h2>
      <el-radio-group v-model="viewMode" size="small">
        <el-radio-button value="visual">可视化</el-radio-button>
        <el-radio-button value="json">JSON</el-radio-button>
      </el-radio-group>
    </div>

    <template v-if="viewMode === 'visual'">
      <div class="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-4 min-h-0">
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 flex flex-col overflow-hidden">
          <div class="p-3 border-b border-gray-200 dark:border-gray-700 font-medium text-sm">配置项</div>
          <div class="flex-1 overflow-y-auto p-2 space-y-1">
            <div
              v-for="item in navItems"
              :key="item.key"
              class="px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors"
              :class="currentKey === item.key
                ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 font-medium'
                : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'"
              @click="currentKey = item.key"
            >
              {{ item.label }}
            </div>
          </div>
        </div>

        <div class="lg:col-span-3 bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 overflow-y-auto">
          <template v-if="currentKey === 'defaults'">
            <h3 class="font-bold mb-4">全局默认配置</h3>
            <p class="text-sm text-gray-500 mb-4">这些参数会被所有 agent 继承，除非 agent 或 task 显式覆盖。</p>
            <el-form label-width="140px" size="small">
              <el-form-item label="超时时间 (秒)">
                <el-input-number v-model="config.defaults.timeout" :min="1" :max="300" />
              </el-form-item>
              <el-form-item label="重试次数">
                <el-input-number v-model="config.defaults.retries" :min="0" :max="10" />
              </el-form-item>
              <el-form-item label="温度">
                <el-slider v-model="config.defaults.temperature" :min="0" :max="2" :step="0.1" style="width: 200px" />
                <span class="ml-2 text-sm text-gray-500">{{ config.defaults.temperature }}</span>
              </el-form-item>
            </el-form>
          </template>

          <template v-else-if="currentKey === 'models'">
            <div class="flex items-center justify-between mb-4">
              <h3 class="font-bold">模型 Profiles</h3>
              <el-button type="primary" size="small" @click="addModelProfile">添加 Profile</el-button>
            </div>
            <p class="text-sm text-gray-500 mb-4">定义可复用的模型配置，agent 通过名称引用。provider 和 model 为必填项。</p>

            <div v-for="(profile, name) in config.models" :key="name" class="mb-4 p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
              <div class="flex items-center justify-between mb-3">
                <el-input v-model="modelNames[name]" placeholder="Profile 名称" style="width: 200px" size="small" @blur="renameModel(name, modelNames[name])">
                  <template #prefix>
                    <el-tag type="success" size="small">Profile</el-tag>
                  </template>
                </el-input>
                <el-button type="danger" size="small" text @click="removeModelProfile(name)">删除</el-button>
              </div>
              <el-form label-width="100px" size="small">
                <el-form-item label="Provider">
                  <el-select v-model="profile.provider" placeholder="选择 provider" style="width: 200px">
                    <el-option label="Anthropic" value="anthropic" />
                    <el-option label="MiniMax" value="minimax" />
                    <el-option label="OpenAI Compatible" value="openai_compatible" />
                  </el-select>
                </el-form-item>
                <el-form-item label="Model">
                  <el-input v-model="profile.model" placeholder="模型名称，如 claude-sonnet-4-6" style="width: 300px" />
                </el-form-item>
                <el-form-item label="Base URL">
                  <el-input v-model="profile.base_url" placeholder="留空则使用 Provider 默认值" style="width: 400px" />
                </el-form-item>
              </el-form>
            </div>

            <el-empty v-if="Object.keys(config.models || {}).length === 0" description="暂无模型 Profiles，点击上方按钮添加" />
          </template>

          <template v-else-if="currentKey === 'embedding'">
            <h3 class="font-bold mb-4">Embedding 配置</h3>
            <el-form label-width="140px" size="small">
              <el-form-item label="Provider">
                <el-select v-model="config.embedding.provider" placeholder="选择 provider" style="width: 200px">
                  <el-option label="OpenAI Compatible" value="openai_compatible" />
                </el-select>
              </el-form-item>
              <el-form-item label="模型">
                <el-input v-model="config.embedding.model" placeholder="text-embedding-3-small" style="width: 300px" />
              </el-form-item>
              <el-form-item label="Base URL">
                <el-input v-model="config.embedding.base_url" placeholder="https://api.openai.com/v1" style="width: 400px" />
              </el-form-item>
              <el-form-item label="维度">
                <el-input-number v-model="config.embedding.dimensions" :min="1" :max="8192" />
              </el-form-item>
              <el-form-item label="超时时间 (秒)">
                <el-input-number v-model="config.embedding.timeout" :min="1" :max="300" />
              </el-form-item>
              <el-form-item label="重试次数">
                <el-input-number v-model="config.embedding.retries" :min="0" :max="10" />
              </el-form-item>
            </el-form>
          </template>

          <template v-else-if="currentKey === 'api_keys'">
            <h3 class="font-bold mb-4">API Key 配置</h3>
            <el-form label-width="140px" size="small">
              <el-form-item v-for="key in envKeys" :key="key" :label="keyLabels[key]">
                <el-input v-model="envConfig[key]" show-password placeholder="输入 API Key" style="width: 400px" />
              </el-form-item>
            </el-form>
            <el-button type="primary" :loading="savingEnv" @click="saveEnv" class="mt-2">保存 API Key</el-button>
          </template>

          <template v-else-if="isAgentKey(currentKey)">
            <div class="flex items-center justify-between mb-4">
              <h3 class="font-bold">{{ agentLabel(currentKey) }} 模型配置</h3>
              <el-button type="danger" size="small" text @click="resetAgent(currentKey)">重置为默认</el-button>
            </div>

            <div class="mb-6">
              <div class="flex items-center gap-2 mb-3 pb-2 border-b border-gray-200 dark:border-gray-700">
                <el-tag type="primary" size="small">主用</el-tag>
                <span class="font-medium text-sm">主用模型</span>
              </div>
              <AgentModelForm :agent="config.agents[currentKey]" :models="config.models" />
            </div>

            <div class="mb-6">
              <div class="flex items-center justify-between mb-3 pb-2 border-b border-gray-200 dark:border-gray-700">
                <div class="flex items-center gap-2">
                  <el-tag type="warning" size="small">备用</el-tag>
                  <span class="font-medium text-sm">备用模型 (Fallback)</span>
                </div>
                <el-switch v-model="fallbackEnabled[currentKey]" active-text="启用" @change="toggleFallback(currentKey)" />
              </div>
              <AgentModelForm v-if="fallbackEnabled[currentKey]" :agent="config.agents[currentKey].fallback" :models="config.models" />
              <el-text v-else type="info" size="small">未启用备用模型</el-text>
            </div>

            <el-collapse v-if="hasTasks(currentKey)">
              <el-collapse-item title="任务级配置 (Tasks)">
                <div v-for="taskName in taskNames(currentKey)" :key="taskName" class="mb-4 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <div class="font-medium text-sm mb-2">{{ taskName }}</div>
                  <el-form label-width="100px" size="small">
                    <el-form-item label="模型配置">
                      <el-select
                        v-model="config.agents[currentKey].tasks[taskName].model"
                        clearable
                        placeholder="继承 agent 配置"
                        style="width: 200px"
                      >
                        <el-option
                          v-for="name in Object.keys(config.models || {})"
                          :key="name"
                          :label="name"
                          :value="name"
                        />
                      </el-select>
                      <span v-if="config.agents[currentKey].tasks[taskName].model" class="ml-2 text-xs text-gray-400">
                        {{ modelProfileInfo(config.agents[currentKey].tasks[taskName].model) }}
                      </span>
                    </el-form-item>
                    <el-form-item label="温度">
                      <el-slider v-model="config.agents[currentKey].tasks[taskName].temperature" :min="0" :max="2" :step="0.05" style="width: 180px" />
                      <span class="ml-2 text-sm text-gray-500">{{ config.agents[currentKey].tasks[taskName].temperature }}</span>
                    </el-form-item>
                    <el-form-item v-if="config.agents[currentKey].tasks[taskName].timeout !== undefined" label="超时">
                      <el-input-number v-model="config.agents[currentKey].tasks[taskName].timeout" :min="1" :max="300" />
                    </el-form-item>
                    <el-form-item v-if="config.agents[currentKey].tasks[taskName].retries !== undefined" label="重试">
                      <el-input-number v-model="config.agents[currentKey].tasks[taskName].retries" :min="0" :max="10" />
                    </el-form-item>
                  </el-form>
                </div>
              </el-collapse-item>
            </el-collapse>
          </template>
        </div>
      </div>

      <div class="flex justify-end pt-2">
        <el-button type="primary" :loading="savingConfig" @click="saveConfig">保存配置</el-button>
      </div>
    </template>

    <template v-else>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
          <h3 class="font-bold mb-3">LLM 配置 (JSON)</h3>
          <el-input v-model="configText" type="textarea" :rows="20" />
          <el-button type="primary" class="mt-4" :loading="savingConfig" @click="saveConfigJson">保存配置</el-button>
        </div>
        <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
          <h3 class="font-bold mb-3">API Key</h3>
          <el-form label-width="120px">
            <el-form-item v-for="key in envKeys" :key="key" :label="keyLabels[key]">
              <el-input v-model="envConfig[key]" />
            </el-form-item>
          </el-form>
          <el-button type="primary" :loading="savingEnv" @click="saveEnv">保存 Key</el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getLLMConfig, saveLLMConfig, getEnvConfig, saveEnvConfig } from '@/api.js'
import { ElMessage } from 'element-plus'
import AgentModelForm from '@/components/AgentModelForm.vue'

const viewMode = ref('visual')
const configText = ref('')
const envConfig = ref({})
const savingConfig = ref(false)
const savingEnv = ref(false)
const currentKey = ref('defaults')
const modelNames = ref({})

const envKeys = ['anthropic_api_key', 'openai_api_key', 'moonshot_api_key', 'minimax_api_key', 'zhipu_api_key']
const keyLabels = { anthropic_api_key: 'Anthropic', openai_api_key: 'OpenAI', moonshot_api_key: 'Moonshot', minimax_api_key: 'MiniMax', zhipu_api_key: 'Zhipu' }

const config = ref({
  defaults: { timeout: 30, retries: 2, temperature: 0.7 },
  models: {},
  embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', timeout: 30, retries: 3, dimensions: 1024 },
  agents: {}
})

const fallbackEnabled = ref({})

const agentOrder = [
  'brainstorm_agent', 'volume_planner_agent', 'setting_extractor_agent',
  'style_profiler_agent', 'file_classifier', 'context_agent', 'writer_agent',
  'critic_agent', 'editor_agent', 'fast_review_agent', 'librarian_agent',
]

const agentLabels = {
  brainstorm_agent: 'Brainstorm', volume_planner_agent: 'Volume Planner',
  setting_extractor_agent: 'Setting Extractor', style_profiler_agent: 'Style Profiler',
  file_classifier: 'File Classifier', context_agent: 'Context',
  writer_agent: 'Writer', critic_agent: 'Critic',
  editor_agent: 'Editor', fast_review_agent: 'Fast Review',
  librarian_agent: 'Librarian',
}

const navItems = computed(() => {
  const items = [
    { key: 'defaults', label: '全局默认 (Defaults)' },
    { key: 'models', label: '模型 Profiles' },
    { key: 'embedding', label: 'Embedding' },
  ]
  const agents = config.value.agents || {}
  for (const key of agentOrder) {
    if (agents[key]) items.push({ key, label: agentLabels[key] || key })
  }
  items.push({ key: 'api_keys', label: 'API Keys' })
  return items
})

function isAgentKey(key) { return agentOrder.includes(key) }
function agentLabel(key) { return agentLabels[key] || key }

function hasTasks(key) {
  const agent = config.value.agents?.[key]
  return agent && agent.tasks && Object.keys(agent.tasks).length > 0
}
function taskNames(key) {
  const agent = config.value.agents?.[key]
  return agent?.tasks ? Object.keys(agent.tasks) : []
}

function modelProfileInfo(name) {
  const profile = config.value.models?.[name]
  if (!profile) return ''
  return `${profile.provider} / ${profile.model}`
}

function addModelProfile() {
  if (!config.value.models) config.value.models = {}
  let name = 'new-profile'
  let i = 1
  while (config.value.models[name]) {
    name = `new-profile-${i++}`
  }
  config.value.models[name] = { provider: 'anthropic', model: '', base_url: '' }
  modelNames.value[name] = name
}

function removeModelProfile(name) {
  delete config.value.models[name]
  delete modelNames.value[name]
}

function renameModel(oldName, newName) {
  if (!newName || newName === oldName) return
  if (config.value.models[newName]) {
    ElMessage.warning('Profile 名称已存在')
    modelNames.value[oldName] = oldName
    return
  }
  config.value.models[newName] = config.value.models[oldName]
  delete config.value.models[oldName]
  delete modelNames.value[oldName]
  modelNames.value[newName] = newName

  // Update all agent references
  for (const agent of Object.values(config.value.agents || {})) {
    if (agent.model === oldName) agent.model = newName
    if (agent.fallback?.model === oldName) agent.fallback.model = newName
    for (const task of Object.values(agent.tasks || {})) {
      if (task.model === oldName) task.model = newName
    }
  }
}

function toggleFallback(key) {
  const agent = config.value.agents[key]
  if (fallbackEnabled.value[key]) {
    if (!agent.fallback) agent.fallback = { model: '', timeout: 30, retries: 2, temperature: 0.7 }
  } else {
    delete agent.fallback
  }
}

function resetAgent(key) {
  const agent = config.value.agents[key]
  if (!agent) return
  delete agent.model; delete agent.timeout; delete agent.retries; delete agent.temperature; delete agent.fallback
  fallbackEnabled.value[key] = false
  ElMessage.success('已重置，将使用全局默认配置')
}

function buildFallbackState() {
  const state = {}
  for (const key of agentOrder) {
    const agent = config.value.agents?.[key]
    state[key] = !!(agent && agent.fallback)
  }
  return state
}

function initModelNames() {
  const names = {}
  for (const name of Object.keys(config.value.models || {})) {
    names[name] = name
  }
  modelNames.value = names
}

onMounted(async () => {
  try {
    const data = await getLLMConfig()
    config.value = {
      defaults: { timeout: 30, retries: 2, temperature: 0.7, ...(data.defaults || {}) },
      models: data.models || {},
      embedding: data.embedding || { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', timeout: 30, retries: 3, dimensions: 1024 },
      agents: data.agents || {},
    }
    initModelNames()
    configText.value = JSON.stringify(data, null, 2)
    for (const key of agentOrder) {
      if (!config.value.agents[key]) config.value.agents[key] = {}
    }
    fallbackEnabled.value = buildFallbackState()
  } catch {}
  try { envConfig.value = await getEnvConfig() } catch {}
})

function cleanPayload(payload) {
  // Remove empty agents
  for (const key of Object.keys(payload.agents || {})) {
    const agent = payload.agents[key]
    if (agent.fallback && !agent.fallback.model) delete agent.fallback
    const hasNonEmpty = Object.keys(agent).some(k => {
      if (k === 'tasks') return Object.keys(agent[k] || {}).length > 0
      if (typeof agent[k] === 'object') return Object.keys(agent[k] || {}).length > 0
      return agent[k] !== undefined && agent[k] !== ''
    })
    if (!hasNonEmpty) delete payload.agents[key]
  }
  // Remove empty models
  for (const key of Object.keys(payload.models || {})) {
    const model = payload.models[key]
    if (!model.provider || !model.model) delete payload.models[key]
  }
  return payload
}

async function saveConfig() {
  savingConfig.value = true
  try {
    const payload = cleanPayload(JSON.parse(JSON.stringify(config.value)))
    await saveLLMConfig(payload)
    configText.value = JSON.stringify(payload, null, 2)
    ElMessage.success('配置已保存')
  } catch { ElMessage.error('保存失败') }
  finally { savingConfig.value = false }
}

async function saveConfigJson() {
  savingConfig.value = true
  try {
    const payload = JSON.parse(configText.value)
    await saveLLMConfig(payload)
    config.value = {
      defaults: { timeout: 30, retries: 2, temperature: 0.7, ...(payload.defaults || {}) },
      models: payload.models || {},
      embedding: payload.embedding || { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', timeout: 30, retries: 3, dimensions: 1024 },
      agents: payload.agents || {},
    }
    initModelNames()
    for (const key of agentOrder) { if (!config.value.agents[key]) config.value.agents[key] = {} }
    fallbackEnabled.value = buildFallbackState()
    ElMessage.success('配置已保存')
  } catch { ElMessage.error('JSON 格式错误') }
  finally { savingConfig.value = false }
}

async function saveEnv() {
  savingEnv.value = true
  try { await saveEnvConfig(envConfig.value); ElMessage.success('API Key 已保存') }
  finally { savingEnv.value = false }
}
</script>
