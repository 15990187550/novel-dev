<template>
  <div class="space-y-4">
    <h2 class="text-xl font-bold">模型配置</h2>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <h3 class="font-bold mb-3">LLM 配置 (JSON)</h3>
        <el-input v-model="configText" type="textarea" :rows="20" />
        <el-button type="primary" class="mt-4" :loading="savingConfig" @click="saveConfig">保存配置</el-button>
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getLLMConfig, saveLLMConfig, getEnvConfig, saveEnvConfig } from '@/api.js'
import { ElMessage } from 'element-plus'

const configText = ref('')
const envConfig = ref({})
const savingConfig = ref(false)
const savingEnv = ref(false)
const envKeys = ['anthropic_api_key', 'openai_api_key', 'moonshot_api_key', 'minimax_api_key', 'zhipu_api_key']
const keyLabels = { anthropic_api_key: 'Anthropic', openai_api_key: 'OpenAI', moonshot_api_key: 'Moonshot', minimax_api_key: 'MiniMax', zhipu_api_key: 'Zhipu' }

onMounted(async () => {
  try { configText.value = JSON.stringify(await getLLMConfig(), null, 2) } catch {}
  try { envConfig.value = await getEnvConfig() } catch {}
})

async function saveConfig() {
  savingConfig.value = true
  try { await saveLLMConfig(JSON.parse(configText.value)); ElMessage.success('配置已保存') }
  catch { ElMessage.error('JSON 格式错误') }
  finally { savingConfig.value = false }
}

async function saveEnv() {
  savingEnv.value = true
  try { await saveEnvConfig(envConfig.value); ElMessage.success('API Key 已保存') }
  finally { savingEnv.value = false }
}
</script>
