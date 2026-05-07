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
                <div class="flex items-center gap-2">
                  <el-button
                    size="small"
                    :loading="testingModels[name]"
                    :data-testid="`test-model-${name}`"
                    @click="testModelProfile(name, profile)"
                  >
                    测试连接
                  </el-button>
                  <el-button type="danger" size="small" text @click="removeModelProfile(name)">删除</el-button>
                </div>
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
                <el-form-item label="API Key">
                  <el-input v-model="profile.api_key" show-password placeholder="留空使用环境变量" style="width: 350px" />
                </el-form-item>
              </el-form>
              <div
                v-if="modelTestResults[name]"
                class="mt-3 rounded-md border px-3 py-2 text-xs"
                :class="modelTestResults[name].ok
                  ? 'border-green-200 bg-green-50 text-green-700 dark:border-green-900/60 dark:bg-green-900/20 dark:text-green-300'
                  : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-300'"
              >
                <span class="font-medium">{{ modelTestResults[name].message }}</span>
                <span v-if="modelTestResults[name].latency_ms !== undefined" class="ml-2 text-gray-500 dark:text-gray-400">
                  {{ modelTestResults[name].latency_ms }}ms
                </span>
              </div>
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
              <AgentModelForm :agent="config.agents[currentKey]" :models="config.models" :defaultsTemp="config.defaults.temperature" />
            </div>

            <div class="mb-6">
              <div class="flex items-center justify-between mb-3 pb-2 border-b border-gray-200 dark:border-gray-700">
                <div class="flex items-center gap-2">
                  <el-tag type="warning" size="small">备用</el-tag>
                  <span class="font-medium text-sm">备用模型 (Fallback)</span>
                </div>
                <el-switch v-model="fallbackEnabled[currentKey]" active-text="启用" @change="toggleFallback(currentKey)" />
              </div>
              <AgentModelForm v-if="fallbackEnabled[currentKey]" :agent="config.agents[currentKey].fallback" :models="config.models" :defaultsTemp="config.defaults.temperature" />
              <el-text v-else type="info" size="small">未启用备用模型</el-text>
            </div>

            <div
              v-if="hasOrchestrationPanel(currentKey, null, config.agents[currentKey])"
              class="mb-6 rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/40"
            >
              <div class="mb-3 flex items-center justify-between border-b border-gray-200 pb-2 dark:border-gray-700">
                <div>
                  <div class="font-medium text-sm">新链路 Orchestration</div>
                  <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">控制结构化输出、只读工具和校验/修复子任务。</div>
                </div>
                <label class="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    :checked="orchestrationFor(config.agents[currentKey], currentKey).enabled"
                    :data-testid="`orchestration-enabled-${currentKey}`"
                    @change="setOrchestrationEnabled(config.agents[currentKey], currentKey, null, $event.target.checked)"
                  />
                  启用
                </label>
              </div>
              <div class="grid gap-4 lg:grid-cols-2">
                <div>
                  <div class="mb-2 text-xs font-semibold text-gray-600 dark:text-gray-300">允许工具</div>
                  <div class="space-y-2">
                    <label
                      v-for="tool in orchestrationToolOptions(currentKey)"
                      :key="tool.value"
                      class="flex items-start gap-2 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
                    >
                      <input
                        type="checkbox"
                        class="mt-1"
                        :checked="orchestrationToolEnabled(orchestrationFor(config.agents[currentKey], currentKey), tool.value)"
                        :data-testid="`orchestration-tool-${currentKey}-${tool.value}`"
                        @change="setOrchestrationTool(orchestrationFor(config.agents[currentKey], currentKey), tool.value, $event.target.checked)"
                      />
                      <span>
                        <span class="block font-medium">{{ tool.label }}</span>
                        <span class="block text-xs text-gray-500 dark:text-gray-400">{{ tool.value }}</span>
                      </span>
                    </label>
                  </div>
                </div>
                <div class="space-y-3 text-sm">
                  <label class="block">
                    <span class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">最大工具调用数</span>
                    <input
                      type="number"
                      min="0"
                      max="20"
                      class="w-28 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-600 dark:bg-gray-800"
                      :value="orchestrationFor(config.agents[currentKey], currentKey).max_tool_calls"
                      :data-testid="`orchestration-max-tool-calls-${currentKey}`"
                      @input="orchestrationFor(config.agents[currentKey], currentKey).max_tool_calls = Number($event.target.value)"
                    />
                  </label>
                  <label class="block">
                    <span class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">工具超时秒数</span>
                    <input
                      type="number"
                      min="1"
                      max="60"
                      class="w-28 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-600 dark:bg-gray-800"
                      :value="orchestrationFor(config.agents[currentKey], currentKey).tool_timeout_seconds"
                      @input="orchestrationFor(config.agents[currentKey], currentKey).tool_timeout_seconds = Number($event.target.value)"
                    />
                  </label>
                  <label class="block">
                    <span class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">最大工具返回字符</span>
                    <input
                      type="number"
                      min="200"
                      max="20000"
                      class="w-32 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-600 dark:bg-gray-800"
                      :value="orchestrationFor(config.agents[currentKey], currentKey).max_tool_result_chars"
                      @input="orchestrationFor(config.agents[currentKey], currentKey).max_tool_result_chars = Number($event.target.value)"
                    />
                  </label>
                  <label class="flex items-center gap-2">
                    <input
                      type="checkbox"
                      :checked="orchestrationFor(config.agents[currentKey], currentKey).enable_subtasks"
                      @change="orchestrationFor(config.agents[currentKey], currentKey).enable_subtasks = $event.target.checked"
                    />
                    启用子任务校验/修复
                  </label>
                  <label class="block">
                    <span class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">Validator</span>
                    <select
                      class="w-full rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-600 dark:bg-gray-800"
                      :value="orchestrationFor(config.agents[currentKey], currentKey).validator_subtask || ''"
                      @change="setOptionalField(orchestrationFor(config.agents[currentKey], currentKey), 'validator_subtask', $event.target.value)"
                    >
                      <option value="">无</option>
                      <option value="location_context_quality">location_context_quality</option>
                    </select>
                  </label>
                  <label class="block">
                    <span class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">Repairer</span>
                    <select
                      class="w-full rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-600 dark:bg-gray-800"
                      :value="orchestrationFor(config.agents[currentKey], currentKey).repairer_subtask || ''"
                      @change="setOptionalField(orchestrationFor(config.agents[currentKey], currentKey), 'repairer_subtask', $event.target.value)"
                    >
                      <option value="">无</option>
                      <option value="schema_repair">schema_repair</option>
                    </select>
                  </label>
                </div>
              </div>
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
                  <div
                    v-if="hasOrchestrationPanel(currentKey, taskName, config.agents[currentKey].tasks[taskName])"
                    class="mt-3 rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800"
                  >
                    <div class="mb-3 flex items-center justify-between">
                      <div>
                        <div class="font-medium text-sm">任务新链路</div>
                        <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ taskName }} 的工具和子任务配置。</div>
                      </div>
                      <label class="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          :checked="orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName).enabled"
                          :data-testid="`orchestration-enabled-${currentKey}-${taskName}`"
                          @change="setOrchestrationEnabled(config.agents[currentKey].tasks[taskName], currentKey, taskName, $event.target.checked)"
                        />
                        启用
                      </label>
                    </div>
                    <div class="grid gap-3 lg:grid-cols-2">
                      <div class="space-y-2">
                        <label
                          v-for="tool in orchestrationToolOptions(currentKey, taskName)"
                          :key="tool.value"
                          class="flex items-start gap-2 text-sm"
                        >
                          <input
                            type="checkbox"
                            class="mt-1"
                            :checked="orchestrationToolEnabled(orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName), tool.value)"
                            :data-testid="`orchestration-tool-${currentKey}-${taskName}-${tool.value}`"
                            @change="setOrchestrationTool(orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName), tool.value, $event.target.checked)"
                          />
                          <span>
                            <span class="block font-medium">{{ tool.label }}</span>
                            <span class="block text-xs text-gray-500 dark:text-gray-400">{{ tool.value }}</span>
                          </span>
                        </label>
                      </div>
                      <div class="space-y-3 text-sm">
                        <label class="block">
                          <span class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">最大工具调用数</span>
                          <input
                            type="number"
                            min="0"
                            max="20"
                            class="w-28 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-600 dark:bg-gray-800"
                            :value="orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName).max_tool_calls"
                            :data-testid="`orchestration-max-tool-calls-${currentKey}-${taskName}`"
                            @input="orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName).max_tool_calls = Number($event.target.value)"
                          />
                        </label>
                        <label class="block">
                          <span class="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">最大工具返回字符</span>
                          <input
                            type="number"
                            min="200"
                            max="20000"
                            class="w-32 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-600 dark:bg-gray-800"
                            :value="orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName).max_tool_result_chars"
                            @input="orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName).max_tool_result_chars = Number($event.target.value)"
                          />
                        </label>
                        <label class="flex items-center gap-2">
                          <input
                            type="checkbox"
                            :checked="orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName).enable_subtasks"
                            @change="orchestrationFor(config.agents[currentKey].tasks[taskName], currentKey, taskName).enable_subtasks = $event.target.checked"
                          />
                          启用子任务
                        </label>
                      </div>
                    </div>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </template>
        </div>
      </div>

      <div class="flex justify-end pt-2">
        <el-button type="primary" :loading="savingConfig" data-testid="save-config" @click="saveConfig">保存配置</el-button>
      </div>
    </template>

    <template v-else>
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">LLM 配置 (JSON)</h3>
        <el-input v-model="configText" type="textarea" :rows="20" />
        <el-button type="primary" class="mt-4" :loading="savingConfig" @click="saveConfigJson">保存配置</el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { getLLMConfig, saveLLMConfig, testLLMModel } from '@/api.js'
import { ElMessage } from 'element-plus'
import AgentModelForm from '@/components/AgentModelForm.vue'

const viewMode = ref('visual')
const configText = ref('')
const savingConfig = ref(false)
const currentKey = ref('defaults')
const modelNames = ref({})
const modelTestResults = ref({})
const testingModels = ref({})

const config = ref({
  defaults: { timeout: 30, retries: 2, temperature: 0.7 },
  models: {},
  embedding: { provider: 'openai_compatible', model: 'bge-m3', base_url: 'http://127.0.0.1:9997/v1', timeout: 30, retries: 3, dimensions: 1024 },
  agents: {}
})

const fallbackEnabled = ref({})

const agentOrder = [
  'brainstorm_agent', 'volume_planner_agent', 'setting_extractor_agent',
  'setting_consolidation_agent', 'setting_workbench_service', 'style_profiler_agent',
  'file_classifier', 'entity_classifier_agent',
  'outline_workbench_service', 'context_agent', 'writer_agent', 'critic_agent',
  'editor_agent', 'fast_review_agent', 'librarian_agent',
]

const agentLabels = {
  brainstorm_agent: 'Brainstorm', volume_planner_agent: 'Volume Planner',
  setting_extractor_agent: 'Setting Extractor', setting_consolidation_agent: 'Setting Consolidation',
  setting_workbench_service: 'Setting Workbench', style_profiler_agent: 'Style Profiler',
  file_classifier: 'File Classifier', entity_classifier_agent: 'Entity Classifier',
  outline_workbench_service: 'Outline Workbench', context_agent: 'Context',
  writer_agent: 'Writer', critic_agent: 'Critic',
  editor_agent: 'Editor', fast_review_agent: 'Fast Review',
  librarian_agent: 'Librarian',
}

const orchestrationToolCatalog = {
  context_agent: [
    { value: 'get_context_location_details', label: '批量地点详情' },
    { value: 'get_context_entity_states', label: '批量实体状态' },
    { value: 'get_context_foreshadowing_details', label: '批量伏笔详情' },
    { value: 'get_context_timeline_events', label: '最近时间线' },
    { value: 'get_novel_state', label: '小说状态' },
    { value: 'get_chapter_draft_status', label: '章节草稿状态' },
  ],
  setting_workbench_service: [
    { value: 'get_setting_workbench_context', label: '设定工作台上下文' },
    { value: 'query_entity', label: '实体详情' },
    { value: 'get_novel_state', label: '小说状态' },
    { value: 'get_novel_documents', label: '文档摘要列表' },
    { value: 'search_domain_documents', label: '规则域资料检索' },
    { value: 'get_novel_document_full', label: '全文文档' },
  ],
  'volume_planner_agent.generate_volume_plan': [
    { value: 'get_volume_planner_context', label: '卷纲规划上下文' },
    { value: 'get_novel_state', label: '小说状态' },
    { value: 'get_synopsis', label: '总纲' },
    { value: 'get_novel_documents', label: '文档摘要列表' },
    { value: 'get_novel_document_full', label: '全文文档' },
  ],
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

function orchestrationCatalogKey(agentKey, taskName = null) {
  return taskName ? `${agentKey}.${taskName}` : agentKey
}

function orchestrationToolOptions(agentKey, taskName = null) {
  const key = orchestrationCatalogKey(agentKey, taskName)
  return orchestrationToolCatalog[key] || []
}

function hasOrchestrationPanel(agentKey, taskName = null, target = null) {
  return !!target?.orchestration || orchestrationToolOptions(agentKey, taskName).length > 0
}

function defaultOrchestration(agentKey, taskName = null) {
  return {
    enabled: false,
    tool_allowlist: orchestrationToolOptions(agentKey, taskName).map(tool => tool.value),
    max_tool_calls: 3,
    tool_timeout_seconds: 5,
    max_tool_result_chars: agentKey === 'volume_planner_agent' ? 6000 : 1600,
    retriever_subtasks: [],
    enable_subtasks: true,
    repairer_subtask: 'schema_repair',
  }
}

function orchestrationFor(target, agentKey, taskName = null) {
  if (!target.orchestration) {
    target.orchestration = defaultOrchestration(agentKey, taskName)
  }
  const orchestration = target.orchestration
  if (!Array.isArray(orchestration.tool_allowlist)) orchestration.tool_allowlist = []
  if (!Array.isArray(orchestration.retriever_subtasks)) orchestration.retriever_subtasks = []
  if (orchestration.max_tool_calls === undefined) orchestration.max_tool_calls = 3
  if (orchestration.tool_timeout_seconds === undefined) orchestration.tool_timeout_seconds = 5
  if (orchestration.max_tool_result_chars === undefined) orchestration.max_tool_result_chars = 1600
  if (orchestration.enable_subtasks === undefined) orchestration.enable_subtasks = true
  return orchestration
}

function setOrchestrationEnabled(target, agentKey, taskName, enabled) {
  orchestrationFor(target, agentKey, taskName).enabled = enabled
}

function orchestrationToolEnabled(orchestration, toolValue) {
  return (orchestration.tool_allowlist || []).includes(toolValue)
}

function setOrchestrationTool(orchestration, toolValue, enabled) {
  if (!Array.isArray(orchestration.tool_allowlist)) orchestration.tool_allowlist = []
  if (enabled && !orchestration.tool_allowlist.includes(toolValue)) {
    orchestration.tool_allowlist.push(toolValue)
  }
  if (!enabled) {
    orchestration.tool_allowlist = orchestration.tool_allowlist.filter(value => value !== toolValue)
  }
}

function setOptionalField(target, field, value) {
  if (value) target[field] = value
  else delete target[field]
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
  delete modelTestResults.value[name]
  delete testingModels.value[name]
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
  if (modelTestResults.value[oldName]) {
    modelTestResults.value[newName] = modelTestResults.value[oldName]
    delete modelTestResults.value[oldName]
  }
  if (testingModels.value[oldName]) {
    testingModels.value[newName] = testingModels.value[oldName]
    delete testingModels.value[oldName]
  }

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
    if (!agent.fallback) agent.fallback = { model: '', timeout: 30, retries: 2 }
    agent.fallback.temperature = agent.temperature ?? config.value.defaults.temperature
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

function syncFallbackTemps() {
  for (const key of agentOrder) {
    const agent = config.value.agents?.[key]
    if (agent?.fallback && agent.fallback.model) {
      // 只有当主模型温度存在时，才同步到备用模型
      if (agent.temperature !== undefined) {
        agent.fallback.temperature = agent.temperature
      }
    }
  }
}

function initModelNames() {
  const names = {}
  for (const name of Object.keys(config.value.models || {})) {
    names[name] = name
  }
  modelNames.value = names
}

function compactProfile(profile) {
  const payload = {}
  for (const [key, value] of Object.entries(profile || {})) {
    if (value !== undefined && value !== '') payload[key] = value
  }
  return payload
}

async function testModelProfile(name, profile) {
  testingModels.value[name] = true
  modelTestResults.value[name] = null
  try {
    const result = await testLLMModel(name, compactProfile(profile))
    modelTestResults.value[name] = result
    if (result.ok) {
      ElMessage.success(`${name} 连接成功`)
    } else {
      ElMessage.error(`${name} ${result.message || '连接失败'}`)
    }
  } catch (err) {
    modelTestResults.value[name] = {
      ok: false,
      status: 'failed',
      message: err?.response?.data?.detail || err?.message || '连接失败',
    }
  } finally {
    testingModels.value[name] = false
  }
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
    syncFallbackTemps()
    fallbackEnabled.value = buildFallbackState()
  } catch {}
})

// 同步主模型温度到备用模型（仅当主模型温度已定义且模型相同时）
watch(() => config.value.agents, (agents) => {
  for (const key of agentOrder) {
    const agent = agents?.[key]
    if (agent?.fallback && agent.fallback.model === agent.model && agent.temperature !== undefined) {
      agent.fallback.temperature = agent.temperature
    }
  }
}, { deep: true })

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
    syncFallbackTemps()
    fallbackEnabled.value = buildFallbackState()
    ElMessage.success('配置已保存')
  } catch { ElMessage.error('JSON 格式错误') }
  finally { savingConfig.value = false }
}

</script>
