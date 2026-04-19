<template>
  <v-chart class="w-full h-64" :option="option" autoresize />
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, RadarChart, TooltipComponent])

const props = defineProps({
  scores: { type: Object, default: () => ({}) },
})

const dimMap = {
  plot_tension: '情节张力',
  characterization: '人物塑造',
  readability: '可读性',
  consistency: '一致性',
  humanity: '人性刻画',
}

const option = computed(() => {
  const dims = Object.keys(dimMap)
  const indicator = dims.map(k => ({ name: dimMap[k], max: 100 }))
  const data = dims.map(k => props.scores[k]?.score ?? props.scores[k] ?? 0)

  return {
    radar: { indicator, radius: '65%', splitNumber: 4, axisName: { color: '#666', fontSize: 12 } },
    series: [{
      type: 'radar',
      data: [{ value: data, name: '评分', areaStyle: { color: 'rgba(59,130,246,0.2)' }, lineStyle: { color: '#3b82f6' }, itemStyle: { color: '#3b82f6' } }],
    }],
    tooltip: { trigger: 'item' },
  }
})
</script>
