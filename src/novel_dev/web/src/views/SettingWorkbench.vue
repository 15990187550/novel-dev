<template>
  <div class="setting-workbench space-y-6" :class="{ 'setting-workbench--embedded': embedded }">
    <section v-if="!embedded" class="page-header">
      <div>
        <div class="page-header__eyebrow">Settings Workbench</div>
        <h1 class="page-header__title">设定工作台</h1>
        <p class="page-header__description">
          从一个初始想法开始，创建独立的 AI 生成设定会话。
        </p>
      </div>
    </section>

    <el-alert v-if="!store.novelId" title="请先选择小说" type="info" show-icon />
    <template v-else>
      <section class="surface-card setting-ai-panel p-5" data-testid="setting-ai-panel">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">AI Settings</div>
            <h2 class="mt-2 text-xl font-semibold text-gray-900 dark:text-gray-100">AI 生成设定</h2>
            <p class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
              每个会话独立保存初始想法和后续上下文，后续生成结果进入审核记录。
            </p>
          </div>
          <div class="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              class="setting-secondary"
              data-testid="setting-consolidation-open"
              @click="openConsolidationDialog"
            >
              一键整合设定
            </button>
            <button
              type="button"
              class="setting-primary"
              data-testid="setting-new-session"
              @click="showCreateForm = true"
            >
              新建会话
            </button>
          </div>
        </div>

        <div v-if="showCreateForm" class="setting-create-box mt-4 grid gap-3 rounded-xl border p-4">
          <label class="setting-field">
            <span>初始想法</span>
            <textarea
              v-model="newIdea"
              data-testid="setting-session-idea"
              class="setting-input min-h-[96px]"
              placeholder="输入你希望 AI 扩展的设定方向"
            />
          </label>
          <p class="text-xs leading-5 text-gray-500 dark:text-gray-400">
            会话名称会从初始想法中自动提炼，不需要手动填写。
          </p>
          <div class="flex justify-end gap-2">
            <button type="button" class="setting-secondary" @click="showCreateForm = false">取消</button>
            <button
              type="button"
              class="setting-primary"
              data-testid="setting-create-session"
              :disabled="store.settingWorkbench.creatingSession || !canCreateSession"
              @click="createSession"
            >
              {{ store.settingWorkbench.creatingSession ? '创建中...' : '创建会话' }}
            </button>
          </div>
        </div>

        <div v-if="store.settingWorkbench.consolidationJob" class="setting-job mt-4 rounded-xl border px-4 py-3 text-sm">
          <span class="font-semibold">整合任务</span>
          <span class="ml-2 text-gray-500 dark:text-gray-400">
            {{ store.settingWorkbench.consolidationJob.job_id || store.settingWorkbench.consolidationJob.id }}
            · {{ statusLabel(store.settingWorkbench.consolidationJob.status) }}
          </span>
        </div>

        <div class="setting-ai-grid mt-4">
        <aside class="setting-sub-card p-4">
          <div class="flex items-center justify-between gap-3">
            <div class="font-semibold text-gray-900 dark:text-gray-100">会话列表</div>
            <button type="button" class="setting-secondary" @click="store.fetchSettingSessions()">刷新</button>
          </div>
          <div v-if="store.settingWorkbench.state === 'loading'" class="mt-4 text-sm text-gray-500">加载中...</div>
          <div v-else-if="!store.settingWorkbench.sessions.length" class="mt-4 rounded-xl border border-dashed px-4 py-6 text-sm text-gray-500">
            暂无 AI 设定会话。
          </div>
          <div v-else class="mt-4 space-y-2">
            <button
              v-for="session in store.settingWorkbench.sessions"
              :key="session.id"
              type="button"
              class="setting-session-item"
              :class="{ 'setting-session-item--active': session.id === store.settingWorkbench.selectedSessionId }"
              @click="store.loadSettingSession(session.id)"
            >
              <span>{{ session.title }}</span>
              <small>{{ statusLabel(session.status) }}</small>
            </button>
          </div>
        </aside>

        <section class="setting-sub-card p-4">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div class="text-xs font-medium uppercase tracking-[0.2em] text-gray-400">Session</div>
              <h2 class="mt-2 text-xl font-semibold text-gray-900 dark:text-gray-100">
                {{ selectedSession?.title || '选择或新建会话' }}
              </h2>
            </div>
            <button
              type="button"
              class="setting-secondary"
              data-testid="setting-generate-review"
              :disabled="!selectedSession || store.settingWorkbench.generating"
              @click="generateReviewBatch"
            >
              {{ store.settingWorkbench.generating ? '生成中...' : '生成到审核记录' }}
            </button>
          </div>

          <div class="setting-message-log mt-4 max-h-80 space-y-3 overflow-auto rounded-xl border p-4">
            <div v-if="!messages.length" class="text-sm text-gray-500">
              创建会话后，这里会显示初始想法和后续对话。
            </div>
            <article v-for="message in messages" :key="message.id" class="setting-message rounded-xl px-3 py-2">
              <div class="text-xs font-semibold uppercase text-gray-400">{{ message.role === 'user' ? '你' : 'AI' }}</div>
              <div class="mt-1 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-200">{{ message.content }}</div>
              <ol v-if="messageQuestions(message).length" class="setting-message__questions">
                <li v-for="question in messageQuestions(message)" :key="question">{{ question }}</li>
              </ol>
            </article>
          </div>

          <div class="setting-reply-box mt-4 rounded-xl border p-3">
            <label class="setting-field">
              <span>继续调整设定</span>
              <textarea
                v-model="replyContent"
                data-testid="setting-session-reply"
                class="setting-input min-h-[86px]"
                :disabled="!selectedSession || store.settingWorkbench.replying"
                placeholder="补充回答、修正方向，或说明下一步希望 AI 继续扩展的内容"
              />
            </label>
            <div class="mt-3 flex justify-end">
              <button
                type="button"
                class="setting-primary"
                data-testid="setting-session-reply-submit"
                :disabled="!selectedSession || store.settingWorkbench.replying || !canReply"
                @click="submitReply"
              >
                {{ store.settingWorkbench.replying ? '发送中...' : '发送调整' }}
              </button>
            </div>
          </div>
        </section>
        </div>
      </section>

      <el-dialog v-model="showConsolidationDialog" title="一键整合设定" width="560px">
        <div class="space-y-3">
          <div class="text-sm text-gray-500">
            已通过审核并生效的设定会自动参与整合；待审核设定记录为可选项，只有勾选后才会参与。本次提交会创建一条设定审核记录。
          </div>
          <div v-if="!pendingSettingDocs.length" class="rounded-xl border border-dashed px-4 py-6 text-sm text-gray-500">
            当前没有待审核设定记录。
          </div>
          <label
            v-for="item in pendingSettingDocs"
            :key="item.id"
            class="setting-pending-option"
          >
            <input
              v-model="selectedPendingIds"
              type="checkbox"
              :value="item.id"
              :data-testid="`setting-consolidation-pending-${item.id}`"
            />
            <span>
              <strong>{{ item.title || item.filename || item.id }}</strong>
              <small>{{ item.doc_type || item.type || 'setting' }}</small>
            </span>
          </label>
        </div>
        <template #footer>
          <button type="button" class="setting-secondary" @click="showConsolidationDialog = false">取消</button>
          <button
            type="button"
            class="setting-primary"
            data-testid="setting-consolidation-submit"
            :disabled="store.settingWorkbench.consolidationSubmitting"
            @click="submitConsolidation"
          >
            {{ store.settingWorkbench.consolidationSubmitting ? '提交中...' : '开始整合' }}
          </button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'

defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})

const store = useNovelStore()
const showCreateForm = ref(false)
const showConsolidationDialog = ref(false)
const newIdea = ref('')
const replyContent = ref('')
const selectedPendingIds = ref([])

const selectedSession = computed(() => store.settingWorkbench.selectedSession)
const messages = computed(() => store.settingWorkbench.selectedMessages || [])
const pendingSettingDocs = computed(() => (store.pendingDocs || []).filter(isSettingPendingDoc))
const canCreateSession = computed(() => Boolean(newIdea.value.trim()))
const canReply = computed(() => Boolean(replyContent.value.trim()))

watch(() => store.novelId, (novelId) => {
  if (novelId) {
    store.fetchSettingSessions()
    store.fetchSettingReviewBatches()
    store.fetchDocuments()
  }
}, { immediate: true })

function statusLabel(status) {
  return {
    clarifying: '澄清中',
    ready_to_generate: '可生成',
    generating: '生成中',
    generated: '已生成',
    pending: '待审核',
    approved: '已通过',
    archived: '已归档',
    queued: '排队中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
  }[status] || status || '未知'
}

function isSettingPendingDoc(item) {
  if (item?.status !== 'pending') return false
  const type = String(item.extraction_type || item.doc_type || item.type || '').toLowerCase()
  return type === 'setting' || type === 'settings'
}

function openConsolidationDialog() {
  selectedPendingIds.value = []
  showConsolidationDialog.value = true
}

async function submitConsolidation() {
  const job = await store.startSettingConsolidation([...selectedPendingIds.value])
  if (job) {
    selectedPendingIds.value = []
    showConsolidationDialog.value = false
  }
}

async function createSession() {
  const idea = newIdea.value.trim()
  if (!idea) return
  const session = await store.createSettingSession({
    title: deriveSessionTitle(idea),
    initial_idea: idea,
    target_categories: [],
  })
  if (session?.id) {
    await store.loadSettingSession(session.id)
    newIdea.value = ''
    showCreateForm.value = false
  }
}

async function submitReply() {
  const content = replyContent.value.trim()
  if (!content || !selectedSession.value) return
  const result = await store.replySettingSession(content)
  if (result) {
    replyContent.value = ''
  }
}

async function generateReviewBatch() {
  if (!selectedSession.value) return
  const batch = await store.generateSettingReviewBatch()
  if (batch) {
    await store.fetchSettingReviewBatches()
  }
}

function deriveSessionTitle(content) {
  const firstLine = String(content || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || '未命名设定会话'
  return firstLine
    .replace(/[，。！？；：,.!?;:]+$/g, '')
    .slice(0, 24) || '未命名设定会话'
}

function messageQuestions(message) {
  const questions = message?.meta?.questions
  if (!Array.isArray(questions)) return []
  return questions
    .map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        return item.question || item.content || item.text || ''
      }
      return ''
    })
    .map((item) => String(item).trim())
    .filter(Boolean)
}
</script>

<style scoped>
.setting-primary,
.setting-secondary,
.setting-session-item {
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 700;
  transition: border-color 0.16s ease, background 0.16s ease, color 0.16s ease;
}

.setting-primary {
  border: 1px solid color-mix(in srgb, var(--app-accent, #14b8a6) 44%, var(--app-border));
  background: color-mix(in srgb, var(--app-accent, #14b8a6) 78%, white 10%);
  color: #fff;
  padding: 0.55rem 0.9rem;
}

.setting-primary:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.setting-secondary {
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
  padding: 0.45rem 0.75rem;
}

.setting-create-box,
.setting-message-log,
.setting-job,
.setting-reply-box,
.setting-sub-card,
.setting-session-item {
  border-color: var(--app-border);
  background: var(--app-surface-soft);
}

.setting-ai-grid {
  display: grid;
  gap: 1rem;
}

.setting-sub-card {
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: 12px;
}

@media (min-width: 1280px) {
  .setting-ai-grid {
    grid-template-columns: 320px minmax(0, 1fr);
  }
}

.setting-field {
  display: grid;
  gap: 0.35rem;
  color: var(--app-text);
  font-size: 0.875rem;
  font-weight: 700;
}

.setting-input {
  width: 100%;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  color: var(--app-text);
  padding: 0.65rem 0.75rem;
  font-size: 0.875rem;
  font-weight: 500;
  outline: none;
}

.setting-input:focus {
  border-color: var(--app-border-strong);
}

.setting-session-item {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border: 1px solid var(--app-border);
  padding: 0.75rem;
  text-align: left;
  color: var(--app-text);
}

.setting-session-item small {
  color: var(--app-text-muted);
}

.setting-session-item--active {
  border-color: color-mix(in srgb, var(--app-accent, #14b8a6) 46%, var(--app-border));
  background: color-mix(in srgb, var(--app-accent, #14b8a6) 10%, var(--app-surface));
}

.setting-message {
  background: var(--app-surface);
}

.setting-message__questions {
  margin-top: 0.65rem;
  display: grid;
  gap: 0.45rem;
  list-style: decimal;
  padding-left: 1.25rem;
  color: var(--app-text);
  font-size: 0.875rem;
  line-height: 1.6;
}

.setting-message__questions li::marker {
  color: var(--app-text-soft);
  font-weight: 700;
}

.setting-pending-option {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface-soft);
  padding: 0.75rem;
  color: var(--app-text);
  cursor: pointer;
}

.setting-pending-option input {
  margin-top: 0.2rem;
}

.setting-pending-option span {
  display: grid;
  gap: 0.2rem;
}

.setting-pending-option small {
  color: var(--app-text-muted);
}
</style>
