<template>
  <v-chart class="w-full h-48" :option="option" autoresize />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { ElMessage } from 'element-plus'
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

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]))
}

function scoreBreakdownLines(chapter) {
  const breakdown = chapter?.score_breakdown || {}
  return Object.entries(breakdown)
    .map(([key, value]) => {
      const score = typeof value === 'object' && value !== null ? value.score : value
      if (score == null || score === '') return null
      const comment = typeof value === 'object' && value !== null && value.comment ? `：${value.comment}` : ''
      return `${scoreDimensionLabels[key] || key}: ${score}${comment}`
    })
    .filter(Boolean)
}

function scoreTooltipText(chapter) {
  return [
    chapter?.title || '',
    `状态: ${chapter?.statusLabel || chapter?.status || '-'}`,
    `评分: ${chartScore(chapter) ?? '-'}`,
    chapter?.scoreDetail ? `评语: ${chapter.scoreDetail}` : '',
    ...scoreBreakdownLines(chapter),
  ].filter(Boolean).join('\n')
}

function scoreTooltip(chapter) {
  const text = scoreTooltipText(chapter)
  const lines = text.split('\n').map(line => `<div>${escapeHtml(line)}</div>`).join('')
  return `
    <div class="chapter-score-tooltip">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px;">
        <strong style="font-size:13px;color:#111827;">章节评分</strong>
        <button
          type="button"
          data-score-tooltip-copy="${encodeURIComponent(text)}"
          style="border:1px solid #d1d5db;border-radius:6px;background:#ffffff;color:#374151;cursor:pointer;font-size:12px;line-height:1;padding:5px 8px;"
        >复制</button>
      </div>
      <div style="white-space:normal;word-break:break-word;line-height:1.55;">${lines}</div>
    </div>
  `
}

function tooltipPosition(point, _params, _dom, _rect, size) {
  const margin = 12
  const gap = 16
  const contentHeight = size?.contentSize?.[1] || 0
  const viewHeight = size?.viewSize?.[1] || 0
  const left = Math.max(margin, point[0] + gap)
  const maxTop = Math.max(margin, viewHeight - contentHeight - margin)
  const top = Math.min(Math.max(margin, point[1] - contentHeight / 2), maxTop)
  return [left, top]
}

async function copyTooltipText(event) {
  const button = event.target?.closest?.('[data-score-tooltip-copy]')
  if (!button) return
  const text = decodeURIComponent(button.dataset.scoreTooltipCopy || '')
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('章节评分已复制')
  } catch (error) {
    ElMessage.error('复制失败')
  }
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
      renderMode: 'html',
      enterable: true,
      appendToBody: true,
      confine: false,
      position: tooltipPosition,
      extraCssText: 'max-width: 280px; white-space: normal; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.18); border-radius: 8px;',
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

onMounted(() => {
  document.addEventListener('click', copyTooltipText)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', copyTooltipText)
})
</script>
