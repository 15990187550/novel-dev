<template>
  <div class="setting-workbench" :class="{ 'setting-workbench--embedded': embedded }">
    <section v-if="!embedded" class="page-header setting-workbench__header">
      <div class="min-w-0">
        <p class="page-header__eyebrow">Settings Workbench</p>
        <h1 class="page-header__title">AI 生成设定</h1>
        <p class="page-header__description">通过持久 AI 会话生成待审核设定、实体和关系。</p>
      </div>
    </section>

    <el-alert v-if="!store.novelId" title="请先选择小说" type="info" show-icon />

    <template v-else>
      <p v-if="store.settingWorkbench.error" class="setting-error">{{ store.settingWorkbench.error }}</p>

      <section class="setting-panel setting-conversation" data-testid="setting-ai-panel">
        <div class="setting-panel__title-row">
          <div class="min-w-0">
            <h2 class="setting-panel__title">{{ selectedSession?.title || 'AI 生成设定' }}</h2>
            <p class="setting-panel__desc">
              当前状态：<span data-testid="setting-session-status">{{ statusLabel(selectedSession?.status) }}</span>
            </p>
          </div>
          <div class="setting-panel__actions">
            <button
              v-if="canGenerate"
              type="button"
              class="setting-primary"
              data-testid="setting-generate-batch"
              :disabled="store.settingWorkbench.generating"
              @click="store.generateSettingReviewBatch()"
            >
              {{ store.settingWorkbench.generating ? '生成中...' : '生成审核记录' }}
            </button>
            <button type="button" class="setting-refresh" :disabled="store.settingWorkbench.state === 'loading'" @click="store.fetchSettingWorkbench()">
              {{ store.settingWorkbench.state === 'loading' ? '刷新中...' : '刷新' }}
            </button>
          </div>
        </div>

        <div v-if="store.settingWorkbench.sessions.length" class="setting-session-strip" aria-label="AI 会话列表">
          <button
            v-for="session in store.settingWorkbench.sessions"
            :key="session.id"
            type="button"
            class="setting-session-chip"
            :class="{ 'setting-session-chip--active': session.id === store.settingWorkbench.selectedSessionId }"
            @click="selectSession(session.id)"
          >
            <span>{{ session.title || '未命名会话' }}</span>
            <small>{{ statusLabel(session.status) }}</small>
          </button>
        </div>

        <div class="setting-message-list">
          <article v-for="(message, index) in messages" :key="message.id || index" class="setting-message">
            <div class="setting-message__role">{{ message.role === 'user' ? '你' : 'AI' }}</div>
            <p class="setting-message__content">{{ message.content }}</p>
          </article>
          <p v-if="!messages.length" class="setting-empty">
            输入初始想法并发送后会自动创建 AI 会话；AI 会基于当前资料库继续澄清。
          </p>
        </div>

        <form class="setting-reply-form" @submit.prevent="sendReply">
          <textarea
            v-model="replyDraft"
            data-testid="setting-reply-input"
            class="setting-input setting-input--reply"
            :placeholder="selectedSession ? '回答澄清问题，或继续补充设定方向' : '输入初始想法，例如：补一个与陆照相关的宗门势力'"
          />
          <button
            class="setting-primary"
            data-testid="setting-send-reply"
            type="button"
            :disabled="!replyDraft.trim() || sending"
            @click="sendReply"
          >
            {{ sending ? '发送中...' : selectedSession ? '发送回答' : '创建并发送' }}
          </button>
        </form>
      </section>

      <section v-if="!embedded" class="setting-panel">
        <div class="setting-panel__title-row">
          <div>
            <h2 class="setting-panel__title">审核记录</h2>
            <p class="setting-panel__desc">AI 会话和后续优化产生的待审核变更。</p>
          </div>
        </div>

        <div class="setting-review-list">
          <article v-for="batch in reviewBatches" :key="batch.id" class="setting-review-row">
            <div class="setting-review-row__main">
              <span class="setting-review-row__source">{{ sourceLabel(batch.source_type) }}</span>
              <h3 class="setting-review-row__summary">{{ batch.summary || '未命名审核记录' }}</h3>
              <p class="setting-review-row__counts">{{ countsLabel(batch.counts) }}</p>
            </div>
            <span class="setting-review-row__status">{{ statusLabel(batch.status) }}</span>
          </article>
          <p v-if="!reviewBatches.length" class="setting-empty">暂无 AI 审核记录。</p>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNovelStore } from '@/stores/novel.js'

const props = defineProps({
  embedded: { type: Boolean, default: false },
})

const store = useNovelStore()
const route = useRoute()
const router = useRouter()

const replyDraft = ref('')

const selectedSession = computed(() => store.settingWorkbench.selectedSession)
const messages = computed(() => store.settingWorkbench.selectedMessages || [])
const reviewBatches = computed(() => store.settingWorkbench.reviewBatches || [])
const canGenerate = computed(() => selectedSession.value?.status === 'ready_to_generate')
const sending = computed(() => store.settingWorkbench.creatingSession || store.settingWorkbench.replying)
const routePath = computed(() => (props.embedded ? '/documents' : '/settings'))

watch(
  () => [store.novelId, route.query?.session],
  async ([novelId, querySession]) => {
    if (!novelId) return
    await store.fetchSettingWorkbench()
    const sessionId = String(querySession || '')
    if (sessionId) {
      await store.loadSettingSession(sessionId)
    }
  },
  { immediate: true }
)

function statusLabel(status) {
  return {
    clarifying: '澄清中',
    ready_to_generate: '可生成',
    generating: '生成中',
    generated: '已生成',
    pending: '待审核',
    approved: '已通过',
    partially_approved: '部分通过',
    rejected: '已拒绝',
    failed: '失败',
  }[status] || status || '未知'
}

function sourceLabel(sourceType) {
  return sourceType === 'ai_session' ? 'AI 会话' : '导入资料'
}

function countsLabel(counts = {}) {
  const settingCards = counts.setting_card ?? counts.setting_cards ?? counts.cards ?? 0
  const entities = counts.entity ?? counts.entities ?? 0
  const relationships = counts.relationship ?? counts.relationships ?? 0
  return `设定卡片 ${settingCards} · 实体 ${entities} · 关系 ${relationships}`
}

function deriveSessionTitle(content) {
  const firstLine = String(content || '').split(/\n/).map(item => item.trim()).find(Boolean) || 'AI 设定会话'
  const compact = firstLine.replace(/[。！？!?；;，,、：:]+$/g, '')
  return compact.length > 18 ? `${compact.slice(0, 18)}...` : compact
}

function sessionQuery(id) {
  return { ...route.query, tab: 'ai', session: id }
}

async function selectSession(id) {
  router.replace({ path: routePath.value, query: sessionQuery(id) })
  await store.loadSettingSession(id)
}

async function sendReply() {
  const content = replyDraft.value.trim()
  if (!content) return
  let sessionId = store.settingWorkbench.selectedSessionId
  try {
    if (!sessionId) {
      const session = await store.createSettingSession({
        title: deriveSessionTitle(content),
        initial_idea: '',
        target_categories: [],
      })
      sessionId = session?.id || ''
      if (sessionId) {
        router.replace({ path: routePath.value, query: sessionQuery(sessionId) })
      }
    }
    if (!sessionId) return
    await store.replySettingSession(content)
    if (store.settingWorkbench.selectedSessionId === sessionId && replyDraft.value.trim() === content) {
      replyDraft.value = ''
    }
  } catch {
    if (store.settingWorkbench.selectedSessionId === sessionId) {
      replyDraft.value = content
    }
  }
}
</script>

<style scoped>
.setting-workbench {
  display: grid;
  gap: 1rem;
}

.setting-workbench__header,
.setting-panel {
  padding: 1rem;
}

.setting-workbench__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.setting-refresh,
.setting-primary {
  border: 1px solid rgba(15, 118, 110, 0.26);
  border-radius: 0.75rem;
  background: var(--app-accent);
  color: white;
  font-size: 0.875rem;
  font-weight: 700;
  line-height: 1.2;
  padding: 0.68rem 0.95rem;
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.setting-refresh {
  background: var(--app-surface-strong);
  color: var(--app-text);
}

.setting-refresh:hover,
.setting-primary:hover {
  transform: translateY(-1px);
}

.setting-refresh:disabled,
.setting-primary:disabled {
  cursor: not-allowed;
  opacity: 0.55;
  transform: none;
}

.setting-error {
  border: 1px solid rgba(220, 38, 38, 0.24);
  border-radius: 0.75rem;
  background: rgba(254, 242, 242, 0.86);
  color: #991b1b;
  margin: 0;
  padding: 0.75rem 0.9rem;
}

.setting-panel {
  border: 1px solid var(--app-border);
  border-radius: 0.5rem;
  background: var(--app-surface);
}

.setting-panel__title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.setting-panel__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
}

.setting-panel__title {
  color: var(--app-text);
  font-size: 1.1rem;
  font-weight: 800;
  line-height: 1.25;
  margin: 0;
}

.setting-panel__desc,
.setting-empty {
  color: var(--app-text-muted);
  font-size: 0.875rem;
  line-height: 1.55;
}

.setting-panel__desc {
  margin: 0.3rem 0 0;
}

.setting-session-strip {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.9rem;
  overflow-x: auto;
  padding-bottom: 0.2rem;
}

.setting-session-chip {
  display: grid;
  gap: 0.18rem;
  min-width: 8.5rem;
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface-soft);
  color: var(--app-text);
  padding: 0.58rem 0.68rem;
  text-align: left;
}

.setting-session-chip--active {
  border-color: rgba(15, 118, 110, 0.38);
  background: var(--app-surface-strong);
}

.setting-session-chip span {
  font-weight: 800;
  overflow-wrap: anywhere;
}

.setting-session-chip small {
  color: var(--app-text-muted);
  font-size: 0.74rem;
}

.setting-input {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface-strong);
  color: var(--app-text);
  font: inherit;
  padding: 0.68rem 0.78rem;
}

.setting-input--reply {
  min-height: 5rem;
  resize: vertical;
}

.setting-message-list,
.setting-review-list {
  display: grid;
  gap: 0.65rem;
  margin-top: 0.9rem;
}

.setting-message-list {
  max-height: 20rem;
  overflow: auto;
}

.setting-message {
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface-soft);
  padding: 0.75rem;
}

.setting-message__role {
  color: var(--app-text-soft);
  font-size: 0.72rem;
  font-weight: 800;
}

.setting-message__content {
  color: var(--app-text);
  font-size: 0.9rem;
  line-height: 1.6;
  margin: 0.2rem 0 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.setting-reply-form {
  display: grid;
  gap: 0.7rem;
  grid-template-columns: minmax(0, 1fr) auto;
  margin-top: 0.9rem;
}

.setting-reply-form .setting-primary {
  align-self: end;
}

.setting-review-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface-soft);
  padding: 0.85rem;
}

.setting-review-row__main {
  min-width: 0;
}

.setting-review-row__source,
.setting-review-row__status {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  color: var(--app-text-muted);
  display: inline-flex;
  font-size: 0.74rem;
  font-weight: 800;
  line-height: 1;
  padding: 0.32rem 0.52rem;
  white-space: nowrap;
}

.setting-review-row__summary {
  color: var(--app-text);
  font-size: 0.98rem;
  font-weight: 800;
  line-height: 1.4;
  margin: 0.45rem 0 0;
  overflow-wrap: anywhere;
}

.setting-review-row__counts {
  color: var(--app-text-muted);
  font-size: 0.85rem;
  margin: 0.28rem 0 0;
}

@media (max-width: 900px) {
  .setting-reply-form {
    grid-template-columns: 1fr;
  }

  .setting-review-row,
  .setting-workbench__header,
  .setting-panel__title-row {
    align-items: stretch;
    flex-direction: column;
  }

  .setting-refresh,
  .setting-reply-form .setting-primary {
    width: 100%;
  }
}
</style>
