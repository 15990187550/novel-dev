<template>
  <el-form label-width="120px" size="small">
    <el-form-item label="模型配置">
      <el-select
        v-model="agent.model"
        filterable
        clearable
        placeholder="选择模型 profile"
        style="width: 280px"
      >
        <el-option
          v-for="name in modelNames"
          :key="name"
          :label="name"
          :value="name"
        />
      </el-select>
      <span v-if="agent.model" class="ml-2 text-xs text-gray-400">
        {{ modelInfo }}
      </span>
    </el-form-item>

    <el-form-item label="超时时间 (秒)">
      <el-input-number v-model="agent.timeout" :min="1" :max="300" />
    </el-form-item>

    <el-form-item label="重试次数">
      <el-input-number v-model="agent.retries" :min="0" :max="10" />
    </el-form-item>

    <el-form-item label="温度">
      <el-slider v-model="agent.temperature" :min="0" :max="2" :step="0.05" style="width: 200px" />
      <span class="ml-2 text-sm text-gray-500">{{ agent.temperature ?? defaultsTemp }}</span>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  agent: { type: Object, required: true },
  models: { type: Object, default: () => ({}) },
  defaultsTemp: { type: Number, default: 0.7 },
})

const modelNames = computed(() => Object.keys(props.models || {}))

const modelInfo = computed(() => {
  const profile = props.models?.[props.agent.model]
  if (!profile) return ''
  return `${profile.provider} / ${profile.model}`
})
</script>
