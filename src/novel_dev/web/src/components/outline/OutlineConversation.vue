<template>
  <section class="surface-card p-5">
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
        class="outline-conversation-badge rounded-full px-3 py-1 text-xs font-medium"
      >
        优化中
      </span>
    </div>

    <div class="outline-conversation-log mt-4 max-h-80 space-y-3 overflow-auto rounded-2xl border p-4">
      <div v-if="!messages.length" class="outline-conversation-empty rounded-2xl border border-dashed px-4 py-6 text-sm leading-6">
        暂无对话记录。可以直接输入你想修改的大纲意见，例如“强化第二卷主线冲突，提前埋入终局伏笔”。
      </div>

      <div
        v-for="message in messages"
        :key="message.id"
        class="outline-conversation-message rounded-2xl px-4 py-3"
        :class="message.role === 'user' ? 'outline-conversation-message--user' : 'outline-conversation-message--assistant'"
      >
        <div class="text-xs font-medium uppercase tracking-wide" :class="message.role === 'user' ? 'outline-conversation-message__eyebrow--user' : 'outline-conversation-message__eyebrow--assistant'">
          {{ message.role === 'user' ? '你的意见' : '系统回应' }}
        </div>
        <div class="mt-2 whitespace-pre-wrap text-sm leading-6" :class="message.role === 'user' ? 'outline-conversation-message__body--user' : 'outline-conversation-message__body--assistant'">
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
      class="outline-conversation-input mt-2 min-h-[120px] w-full rounded-2xl border px-4 py-3 text-sm leading-6 outline-none transition"
      :disabled="disabled || submitting"
      placeholder="例如：把总纲里的终局目标写得更明确，第二卷提前埋下关键人物反转。"
    />

    <div class="mt-4 flex items-center justify-between gap-3">
      <p class="text-xs leading-5 text-gray-400 dark:text-gray-500">
        每个总纲/卷纲都有独立上下文，切换左侧项后会加载对应历史。
      </p>
      <button
        type="button"
        class="outline-conversation-submit inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium transition duration-200 disabled:cursor-not-allowed"
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

<style scoped>
.outline-conversation-badge {
  background: color-mix(in srgb, #f59e0b 12%, var(--app-surface-soft));
  color: color-mix(in srgb, #f59e0b 72%, var(--app-text));
}

.outline-conversation-log,
.outline-conversation-empty,
.outline-conversation-input,
.outline-conversation-message--user,
.outline-conversation-message--assistant {
  border-color: var(--app-border);
}

.outline-conversation-log {
  background: var(--app-surface-soft);
}

.outline-conversation-empty {
  background: var(--app-surface);
  color: var(--app-text-muted);
}

.outline-conversation-message--user {
  background: var(--app-surface);
}

.outline-conversation-message--assistant {
  background: color-mix(in srgb, var(--app-accent, #14b8a6) 10%, var(--app-surface));
}

.outline-conversation-message__eyebrow--user {
  color: var(--app-text-muted);
}

.outline-conversation-message__eyebrow--assistant {
  color: color-mix(in srgb, var(--app-accent, #14b8a6) 45%, var(--app-text-muted));
}

.outline-conversation-message__body--user,
.outline-conversation-message__body--assistant {
  color: var(--app-text);
}

.outline-conversation-input {
  background: var(--app-surface);
  color: var(--app-text);
}

.outline-conversation-input::placeholder {
  color: var(--app-text-muted);
}

.outline-conversation-input:focus {
  border-color: var(--app-border-strong);
  background: var(--app-surface-soft);
}

.outline-conversation-submit {
  border: 1px solid color-mix(in srgb, var(--app-accent, #14b8a6) 38%, transparent);
  background: color-mix(in srgb, var(--app-accent, #14b8a6) 78%, white 10%);
  color: #fff;
}

.outline-conversation-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.04);
}

.outline-conversation-submit:disabled {
  opacity: 0.5;
}
</style>
