<template>
  <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
    <h3 class="font-bold mb-2">关系图谱</h3>
    <v-chart class="w-full h-80" :option="option" autoresize @click="onClick" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, GraphChart, TooltipComponent])

const props = defineProps({
  entities: { type: Array, default: () => [] },
  relationships: { type: Array, default: () => [] },
})
const emit = defineEmits(['select'])

const typeColor = { character: '#f97316', item: '#3b82f6', location: '#22c55e', other: '#6b7280' }

const option = computed(() => {
  const nodes = props.entities.map(e => ({
    id: e.entity_id, name: e.name,
    symbolSize: 30 + (e.current_version || 1) * 5,
    itemStyle: { color: typeColor[e.type] || '#6b7280' },
  }))
  const links = props.relationships.map(r => ({
    source: r.source_id, target: r.target_id,
    label: { show: true, formatter: r.relation_type },
    lineStyle: { curveness: 0.2 },
  }))
  return {
    tooltip: {},
    series: [{ type: 'graph', layout: 'force', data: nodes, links, roam: true, label: { show: true }, force: { repulsion: 300, edgeLength: 100 } }],
  }
})

function onClick(params) {
  if (params.dataType === 'node') emit('select', params.data.id)
}
</script>
