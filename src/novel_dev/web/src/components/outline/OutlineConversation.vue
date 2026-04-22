<template>
  <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
    <div class="flex items-start justify-between gap-3">
      <div>
        <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Conversation</div>
        <h3 class="mt-2 text-lg font-semibold text-gray-900">对话式优化</h3>
        <p class="mt-1 text-sm leading-6 text-gray-500">
          {{ descriptionText }}
        </p>
      </div>
      <span
        v-if="submitting"
        class="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700"
      >
        优化中
      </span>
    </div>

    <div class="mt-4 max-h-80 space-y-3 overflow-auto rounded-2xl bg-gray-50 p-4">
      <div v-if="!messages.length" class="rounded-2xl border border-dashed border-gray-200 bg-white px-4 py-6 text-sm leading-6 text-gray-500">
        暂无对话记录。可以直接输入你想修改的大纲意见，例如“强化第二卷主线冲突，提前埋入终局伏笔”。
      </div>

      <div
        v-for="message in messages"
        :key="message.id"
        class="rounded-2xl px-4 py-3"
        :class="message.role === 'user' ? 'bg-white' : 'bg-slate-900 text-white'"
      >
        <div class="text-xs font-medium uppercase tracking-wide" :class="message.role === 'user' ? 'text-gray-400' : 'text-slate-300'">
          {{ message.role === 'user' ? '你的意见' : '系统回应' }}
        </div>
        <div class="mt-2 whitespace-pre-wrap text-sm leading-6" :class="message.role === 'user' ? 'text-gray-700' : 'text-slate-100'">
          {{ message.content }}
        </div>
      </div>
    </div>

    <label class="mt-4 block text-sm font-medium text-gray-700" for="outline-feedback-input">
      输入修改意见
    </label>
    <textarea
      id="outline-feedback-input"
      v-model="draft"
      class="mt-2 min-h-[120px] w-full rounded-2xl border border-gray-200 px-4 py-3 text-sm leading-6 text-gray-700 outline-none transition focus:border-slate-400"
      :disabled="disabled || submitting"
      placeholder="例如：把总纲里的终局目标写得更明确，第二卷提前埋下关键人物反转。"
    />

    <div class="mt-4 flex items-center justify-between gap-3">
      <p class="text-xs leading-5 text-gray-400">
        每个总纲/卷纲都有独立上下文，切换左侧项后会加载对应历史。
      </p>
      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:bg-slate-300"
        :disabled="submitDisabled"
        @click="submit"
      >
        <svg
          v-if="submitting"
          class="h-4 w-4 animate-spin"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-opacity="0.25" stroke-width="3" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
        </svg>
        {{ submitText }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
  submitting: {
    type: Boolean,
    default: false,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  currentTitle: {
    type: String,
    default: '',
  },
  submitLabel: {
    type: String,
    default: '发送修改意见',
  },
  allowEmptySubmit: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['submit-feedback'])

const draft = ref('')

const descriptionText = computed(() => {
  if (props.currentTitle) return `当前目标：${props.currentTitle}`
  return '围绕当前选中的大纲项继续提意见，系统会基于对应上下文进行优化。'
})

const submitDisabled = computed(() => (
  props.disabled ||
  props.submitting ||
  (!props.allowEmptySubmit && !draft.value.trim())
))

const submitText = computed(() => {
  if (!props.submitting) return props.submitLabel
  return props.submitLabel === '生成大纲' ? '生成中...' : '发送中...'
})

function submit() {
  const content = draft.value.trim()
  if ((!content && !props.allowEmptySubmit) || props.submitting || props.disabled) return
  emit('submit-feedback', content)
  draft.value = ''
}
</script>
