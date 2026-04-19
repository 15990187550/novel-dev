<template>
  <div class="flex flex-wrap items-center gap-2">
    <template v-for="(step, idx) in steps" :key="step.key">
      <el-button
        :type="stepType(step, idx)"
        :loading="store.loadingActions[step.key]"
        :disabled="!step.enabled"
        size="default"
        @click="store.executeAction(step.key)"
      >
        <el-icon v-if="stepDone(idx)" class="mr-1"><Check /></el-icon>
        {{ step.label }}
      </el-button>
      <el-icon v-if="idx < steps.length - 1" class="text-gray-300 dark:text-gray-600"><ArrowRight /></el-icon>
    </template>
    <el-button :loading="store.loadingActions['export']" @click="store.executeAction('export')">导出小说</el-button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const phaseOrder = ['brainstorming', 'volume_planning', 'context_preparation', 'drafting', 'reviewing', 'editing', 'fast_reviewing', 'librarian', 'completed']

const steps = computed(() => [
  { key: 'brainstorm', label: '脑暴', enabled: store.canBrainstorm, phase: 'brainstorming' },
  { key: 'volume_plan', label: '分卷', enabled: store.canVolumePlan, phase: 'volume_planning' },
  { key: 'context', label: '上下文', enabled: store.canContext, phase: 'context_preparation' },
  { key: 'draft', label: '草稿', enabled: store.canDraft, phase: 'drafting' },
  { key: 'advance', label: '推进', enabled: store.canAdvance, phase: 'reviewing' },
  { key: 'librarian', label: '归档', enabled: store.canLibrarian, phase: 'librarian' },
])

const currentIdx = computed(() => phaseOrder.indexOf(store.novelState.current_phase))

function stepDone(idx) {
  const pi = phaseOrder.indexOf(steps.value[idx].phase)
  return pi < currentIdx.value
}

function stepType(step, idx) {
  const pi = phaseOrder.indexOf(step.phase)
  if (pi === currentIdx.value) return 'primary'
  if (pi < currentIdx.value) return 'success'
  return 'default'
}
</script>
