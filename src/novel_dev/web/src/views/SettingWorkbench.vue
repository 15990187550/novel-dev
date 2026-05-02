<template>
  <div class="setting-workbench">
    <section class="page-header setting-workbench__header">
      <div class="min-w-0">
        <p class="page-header__eyebrow">Settings Workbench</p>
        <h1 class="page-header__title">设定工作台</h1>
        <p class="page-header__description">导入已有资料，或从一个初始想法生成待审核设定。</p>
      </div>
      <button type="button" class="setting-refresh" :disabled="store.settingWorkbench.state === 'loading'" @click="store.fetchSettingWorkbench()">
        {{ store.settingWorkbench.state === 'loading' ? '刷新中...' : '刷新' }}
      </button>
    </section>

    <el-alert v-if="!store.novelId" title="请先选择小说" type="info" show-icon />

    <template v-else>
      <p v-if="store.settingWorkbench.error" class="setting-error">{{ store.settingWorkbench.error }}</p>

      <section class="setting-entry-grid" aria-label="设定工作台入口">
        <button type="button" class="setting-panel setting-entry" data-testid="setting-import-entry" @click="router.push('/documents')">
          <span class="setting-entry__label">导入已有资料</span>
          <span class="setting-entry__desc">上传世界观、人物表、文风样本和设定文档，进入现有资料审核流程。</span>
        </button>
        <button
          type="button"
          class="setting-panel setting-entry"
          :class="{ 'setting-entry--active': mode === 'ai' }"
          data-testid="setting-ai-entry"
          @click="mode = 'ai'"
        >
          <span class="setting-entry__label">从想法生成设定</span>
          <span class="setting-entry__desc">创建持久 AI 会话，通过澄清回答生成待审核设定批次。</span>
        </button>
      </section>

      <section v-if="mode === 'ai'" class="setting-ai-layout" aria-label="AI 设定会话">
        <aside class="setting-panel setting-session-panel">
          <div class="setting-panel__title-row">
            <div>
              <h2 class="setting-panel__title">AI 会话</h2>
              <p class="setting-panel__desc">会话会保留澄清上下文。</p>
            </div>
          </div>

          <div class="setting-session-list">
            <button
              v-for="session in store.settingWorkbench.sessions"
              :key="session.id"
              type="button"
              class="setting-session-item"
              :class="{ 'setting-session-item--active': session.id === store.settingWorkbench.selectedSessionId }"
              @click="selectSession(session.id)"
            >
              <span class="setting-session-item__title">{{ session.title || '未命名设定会话' }}</span>
              <span class="setting-session-item__status">{{ statusLabel(session.status) }}</span>
            </button>
            <p v-if="!store.settingWorkbench.sessions.length" class="setting-empty">暂无会话，先从一个想法开始。</p>
          </div>

          <form class="setting-create-form" @submit.prevent="createSession">
            <label class="setting-field">
              <span>会话标题</span>
              <input
                v-model="newTitle"
                data-testid="setting-session-title"
                class="setting-input"
                placeholder="例如：主角阵营设定"
              />
            </label>
            <label class="setting-field">
              <span>初始想法</span>
              <textarea
                v-model="newIdea"
                data-testid="setting-session-idea"
                class="setting-input setting-input--textarea"
                placeholder="输入世界观、人物、势力或体系的初步设想"
              />
            </label>
            <button
              data-testid="setting-create-session"
              class="setting-primary"
              type="button"
              :disabled="store.settingWorkbench.creatingSession || !newIdea.trim()"
              @click="createSession"
            >
              {{ store.settingWorkbench.creatingSession ? '创建中...' : '创建会话' }}
            </button>
          </form>
        </aside>

        <section class="setting-panel setting-conversation">
          <div class="setting-panel__title-row">
            <div class="min-w-0">
              <h2 class="setting-panel__title">{{ selectedSession?.title || '选择或创建会话' }}</h2>
              <p class="setting-panel__desc">
                当前状态：<span data-testid="setting-session-status">{{ statusLabel(selectedSession?.status) }}</span>
              </p>
            </div>
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
          </div>

          <div class="setting-message-list">
            <article v-for="(message, index) in messages" :key="message.id || index" class="setting-message">
              <div class="setting-message__role">{{ message.role === 'user' ? '你' : 'AI' }}</div>
              <p class="setting-message__content">{{ message.content }}</p>
            </article>
            <p v-if="!messages.length" class="setting-empty">暂无消息。创建会话后，AI 会在这里继续澄清问题。</p>
          </div>

          <form class="setting-reply-form" @submit.prevent="sendReply">
            <textarea
              v-model="replyDraft"
              data-testid="setting-reply-input"
              class="setting-input setting-input--reply"
              placeholder="回答澄清问题，或继续补充设定方向"
            />
            <button
              class="setting-primary"
              data-testid="setting-send-reply"
              type="button"
              :disabled="!store.settingWorkbench.selectedSessionId || !replyDraft.trim() || store.settingWorkbench.replying"
              @click="sendReply"
            >
              {{ store.settingWorkbench.replying ? '发送中...' : '发送回答' }}
            </button>
          </form>
        </section>
      </section>

      <section class="setting-panel">
        <div class="setting-panel__title-row">
          <div>
            <h2 class="setting-panel__title">审核记录</h2>
            <p class="setting-panel__desc">详情审核和统一处理入口由后续任务接入。</p>
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
          <p v-if="!reviewBatches.length" class="setting-empty">暂无审核记录。可以先导入资料，或创建 AI 会话生成。</p>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const route = useRoute()
const router = useRouter()

const mode = ref('ai')
const newTitle = ref('')
const newIdea = ref('')
const replyDraft = ref('')

const selectedSession = computed(() => store.settingWorkbench.selectedSession)
const messages = computed(() => store.settingWorkbench.selectedMessages || [])
const reviewBatches = computed(() => store.settingWorkbench.reviewBatches || [])
const canGenerate = computed(() => selectedSession.value?.status === 'ready_to_generate')

watch(
  () => [store.novelId, route.query?.session],
  async ([novelId, querySession]) => {
    if (!novelId) return
    await store.fetchSettingWorkbench()
    const sessionId = String(querySession || '')
    if (sessionId) {
      mode.value = 'ai'
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

async function createSession() {
  const idea = newIdea.value.trim()
  if (!idea) return
  const session = await store.createSettingSession({
    title: newTitle.value.trim() || '未命名设定会话',
    initial_idea: idea,
    target_categories: [],
  })
  if (session?.id) {
    newTitle.value = ''
    newIdea.value = ''
    router.replace({ path: '/settings', query: { ...route.query, session: session.id } })
    await store.loadSettingSession(session.id)
  }
}

async function selectSession(id) {
  router.replace({ path: '/settings', query: { ...route.query, session: id } })
  await store.loadSettingSession(id)
}

async function sendReply() {
  const content = replyDraft.value.trim()
  if (!content) return
  try {
    await store.replySettingSession(content)
    replyDraft.value = ''
  } catch {
    replyDraft.value = content
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

.setting-entry-grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.setting-entry {
  display: grid;
  gap: 0.35rem;
  min-width: 0;
  padding: 1rem;
  text-align: left;
}

.setting-entry--active {
  border-color: rgba(15, 118, 110, 0.34);
  background: var(--app-surface-strong);
}

.setting-entry__label {
  color: var(--app-text);
  font-weight: 800;
}

.setting-entry__desc,
.setting-panel__desc,
.setting-empty {
  color: var(--app-text-muted);
  font-size: 0.875rem;
  line-height: 1.55;
}

.setting-ai-layout {
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(17rem, 20rem) minmax(0, 1fr);
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

.setting-panel__title {
  color: var(--app-text);
  font-size: 1.1rem;
  font-weight: 800;
  line-height: 1.25;
  margin: 0;
}

.setting-panel__desc {
  margin: 0.3rem 0 0;
}

.setting-session-list,
.setting-create-form,
.setting-message-list,
.setting-review-list {
  display: grid;
  gap: 0.65rem;
  margin-top: 0.9rem;
}

.setting-session-list {
  max-height: 17rem;
  overflow: auto;
}

.setting-session-item {
  display: grid;
  gap: 0.2rem;
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface-soft);
  color: var(--app-text);
  min-width: 0;
  padding: 0.7rem;
  text-align: left;
}

.setting-session-item--active {
  border-color: rgba(15, 118, 110, 0.38);
  background: var(--app-surface-strong);
}

.setting-session-item__title,
.setting-review-row__summary {
  overflow-wrap: anywhere;
}

.setting-session-item__status {
  color: var(--app-text-muted);
  font-size: 0.78rem;
}

.setting-field {
  display: grid;
  gap: 0.35rem;
  color: var(--app-text-muted);
  font-size: 0.82rem;
  font-weight: 700;
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

.setting-input--textarea {
  min-height: 6rem;
  resize: vertical;
}

.setting-input--reply {
  min-height: 5rem;
  resize: vertical;
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
}

.setting-review-row__counts {
  color: var(--app-text-muted);
  font-size: 0.85rem;
  margin: 0.28rem 0 0;
}

@media (max-width: 900px) {
  .setting-entry-grid,
  .setting-ai-layout,
  .setting-reply-form {
    grid-template-columns: 1fr;
  }

  .setting-review-row,
  .setting-workbench__header {
    align-items: stretch;
    flex-direction: column;
  }

  .setting-refresh,
  .setting-reply-form .setting-primary {
    width: 100%;
  }
}
</style>
