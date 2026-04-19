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

const props = defineProps({ chapters: { type: Array, default: () => [] } })

const statusColor = { pending: '#94a3b8', drafted: '#3b82f6', edited: '#22c55e', archived: '#a855f7' }

const option = computed(() => {
  const cats = props.chapters.map(c => `第${c.chapter_number}章`)
  const data = props.chapters.map(ch => ({
    value: ch.word_count || 0,
    itemStyle: { color: statusColor[ch.status] || '#94a3b8' },
  }))

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (p) => {
        const ch = props.chapters[p[0].dataIndex]
        return `${ch?.title || ''}<br/>状态: ${ch?.status}<br/>字数: ${ch?.word_count || 0}/${ch?.target_word_count || 3000}`
      },
    },
    grid: { top: 10, bottom: 30, left: 50, right: 20 },
    xAxis: { type: 'category', data: cats },
    yAxis: { type: 'value', name: '字数' },
    series: [{ type: 'bar', data, barMaxWidth: 30 }],
  }
})
</script>
