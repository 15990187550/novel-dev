<template>
  <section class="dashboard-volume-summary">
    <header class="dashboard-section-header">
      <div>
        <p class="dashboard-section-header__eyebrow">Volume Summary</p>
        <h2 class="dashboard-section-header__title">{{ title }}</h2>
      </div>
      <p class="dashboard-section-header__meta">{{ subtitle }}</p>
    </header>

    <div class="dashboard-volume-summary__grid">
      <div class="dashboard-volume-summary__panel">
        <h3 class="dashboard-volume-summary__panel-title">章节评分</h3>
        <ChapterProgressGantt :chapters="chapters" mode="score" />
      </div>

      <div class="dashboard-volume-summary__panel">
        <h3 class="dashboard-volume-summary__panel-title">总评分雷达</h3>
        <ScoreRadar :scores="scores" />
      </div>
    </div>
  </section>
</template>

<script setup>
import ChapterProgressGantt from '@/components/ChapterProgressGantt.vue'
import ScoreRadar from '@/components/ScoreRadar.vue'

defineProps({
  title: { type: String, default: '卷进度与评分' },
  subtitle: { type: String, default: '当前章节与卷内评分概览' },
  chapters: { type: Array, default: () => [] },
  scores: { type: Object, default: () => ({}) },
})
</script>
