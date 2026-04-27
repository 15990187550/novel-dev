<template>
  <v-chart class="w-full h-48" :option="option" autoresize />
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const props = defineProps({
  chapters: { type: Array, default: () => [] },
  mode: { type: String, default: 'progress' },
})

const statusColor = { pending: '#94a3b8', drafted: '#3b82f6', edited: '#22c55e', archived: '#a855f7' }
const scoreDimensionLabels = {
  plot_tension: '情节张力',
  characterization: '人物塑造',
  readability: '可读性',
  consistency: '一致性',
  humanity: '沉浸感',
  hook_strength: '章末钩子',
}

function chartScore(chapter) {
  const score = Number(chapter?.displayScore ?? chapter?.score_overall)
  return Number.isFinite(score) ? score : null
}

function scoreTooltip(chapter) {
  const breakdown = chapter?.score_breakdown || {}
  const details = Object.entries(breakdown)
    .map(([key, value]) => {
      const score = typeof value === 'object' && value !== null ? value.score : value
      if (score == null || score === '') return ''
      const comment = typeof value === 'object' && value !== null && value.comment ? `：${value.comment}` : ''
      return `${scoreDimensionLabels[key] || key}: ${score}${comment}`
    })
    .filter(Boolean)
    .join('<br/>')
  return [
    chapter?.title || '',
    `状态: ${chapter?.statusLabel || chapter?.status || '-'}`,
    `评分: ${chartScore(chapter) ?? '-'}`,
    chapter?.scoreDetail ? `评语: ${chapter.scoreDetail}` : '',
    details,
  ].filter(Boolean).join('<br/>')
}

const option = computed(() => {
  const isScoreMode = props.mode === 'score'
  const visibleChapters = isScoreMode
    ? props.chapters.filter(ch => chartScore(ch) != null)
    : props.chapters
  const cats = visibleChapters.map(c => `第${c.chapter_number}章`)
  const data = visibleChapters.map(ch => ({
    value: isScoreMode ? chartScore(ch) : (ch.word_count || 0),
    itemStyle: { color: statusColor[ch.status] || '#94a3b8' },
  }))

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (p) => {
        const ch = visibleChapters[p[0].dataIndex]
        if (isScoreMode) return scoreTooltip(ch)
        return `${ch?.title || ''}<br/>状态: ${ch?.status}<br/>字数: ${ch?.word_count || 0}/${ch?.target_word_count || 3000}`
      },
    },
    grid: { top: 10, bottom: 30, left: 50, right: 20 },
    xAxis: { type: 'category', data: cats },
    yAxis: { type: 'value', name: isScoreMode ? '评分' : '字数', max: isScoreMode ? 100 : undefined },
    series: [{ type: 'bar', data, barMaxWidth: 30 }],
  }
})
</script>
