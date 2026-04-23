<template>
  <section class="dashboard-hero">
    <div class="dashboard-hero__content">
      <p class="dashboard-hero__eyebrow">Dashboard Overview</p>
      <h1 class="dashboard-hero__title">{{ title }}</h1>
      <p class="dashboard-hero__phase">{{ phaseLabel }}</p>
      <p class="dashboard-hero__summary">
        把当前流程、章节推进和世界资料集中放在一个入口里，先看风险，再做下一步动作。
      </p>
      <div class="dashboard-hero__chips">
        <span class="dashboard-hero__chip">当前阶段：{{ phaseLabel || '待更新' }}</span>
        <span class="dashboard-hero__chip">当前卷章：{{ volumeChapter || '-' }}</span>
      </div>
    </div>

    <div class="dashboard-hero__actions">
      <button
        type="button"
        class="dashboard-hero__delete"
        @click="$emit('delete-novel')"
      >
        删除小说
      </button>
    </div>

    <div class="dashboard-hero__stats" aria-label="dashboard summary stats">
      <article class="dashboard-hero__stat dashboard-hero__stat--spotlight">
        <span class="dashboard-hero__stat-label">当前卷/章</span>
        <strong class="dashboard-hero__stat-value">{{ volumeChapter }}</strong>
        <span class="dashboard-hero__stat-note">作为当前工作焦点</span>
      </article>
      <article class="dashboard-hero__stat">
        <span class="dashboard-hero__stat-label">总字数</span>
        <strong class="dashboard-hero__stat-value">{{ formattedTotalWords }}</strong>
        <span class="dashboard-hero__stat-note">整体规模与积累</span>
      </article>
      <article class="dashboard-hero__stat">
        <span class="dashboard-hero__stat-label">已归档章节</span>
        <strong class="dashboard-hero__stat-value">{{ archivedCount }}</strong>
        <span class="dashboard-hero__stat-note">已完成沉淀的内容</span>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

defineEmits(['delete-novel'])

const props = defineProps({
  title: { type: String, default: '小说总览' },
  phaseLabel: { type: String, default: '当前阶段：待更新' },
  volumeChapter: { type: String, default: '-' },
  totalWords: { type: [Number, String], default: 0 },
  archivedCount: { type: [Number, String], default: 0 },
})

const formattedTotalWords = computed(() => {
  const value = Number(props.totalWords) || 0
  return value.toLocaleString('zh-CN')
})
</script>

<style scoped>
.dashboard-hero__actions {
  display: flex;
  justify-content: flex-end;
}

.dashboard-hero__delete {
  border: 1px solid #fecaca;
  border-radius: 999px;
  background: #fff1f2;
  color: #b91c1c;
  cursor: pointer;
  font-size: 0.875rem;
  font-weight: 600;
  padding: 0.65rem 1rem;
  transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.dashboard-hero__delete:hover {
  background: #ffe4e6;
  border-color: #fca5a5;
  color: #991b1b;
}
</style>
