<template>
  <div class="entity-graph rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <div class="mb-3 flex items-center justify-between gap-3">
      <h3 class="font-bold">关系图谱</h3>
      <el-button v-if="showFullscreenAction" size="small" @click="emit('fullscreen')">全屏查看</el-button>
    </div>
    <div v-if="!entities.length || !relationships.length" :style="chartStyle" class="flex w-full items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-400">
      暂无关系图谱数据
    </div>
    <v-chart
      v-else
      :style="chartStyle"
      class="entity-graph__canvas w-full rounded-xl"
      :option="option"
      autoresize
      @click="onClick"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([SVGRenderer, GraphChart, TooltipComponent, LegendComponent])

const props = defineProps({
  entities: { type: Array, default: () => [] },
  relationships: { type: Array, default: () => [] },
  height: { type: String, default: '26rem' },
  showFullscreenAction: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'fullscreen'])

const visualCategoryConfig = {
  人物: { color: '#ea580c', label: '人物' },
  势力: { color: '#0f766e', label: '势力' },
  功法: { color: '#7c3aed', label: '功法' },
  法宝神兵: { color: '#2563eb', label: '法宝神兵' },
  天材地宝: { color: '#ca8a04', label: '天材地宝' },
  地点: { color: '#059669', label: '地点' },
  其他: { color: '#475569', label: '其他' },
}
const typeToCategory = {
  character: '人物',
  item: '法宝神兵',
  location: '地点',
  other: '其他',
}
const chartStyle = computed(() => ({ height: props.height }))

function getVisualCategory(entity) {
  return (
    entity.effective_category ||
    entity.manual_category ||
    entity.system_category ||
    typeToCategory[entity.type] ||
    '其他'
  )
}

const option = computed(() => {
  const activeCategories = [...new Set(props.entities.map((entity) => getVisualCategory(entity)))]
  const entityNameById = new Map(props.entities.map((entity) => [entity.entity_id, entity.name]))
  const nodes = props.entities.map(e => ({
    id: e.entity_id,
    name: e.entity_id,
    displayName: e.name,
    category: getVisualCategory(e),
    symbolSize: 38 + Math.min((e.current_version || 1) * 4, 12),
    draggable: true,
    itemStyle: {
      color: (visualCategoryConfig[getVisualCategory(e)] || visualCategoryConfig.其他).color,
      borderColor: '#ffffff',
      borderWidth: 3,
      shadowBlur: 18,
      shadowColor: 'rgba(15, 23, 42, 0.18)',
    },
    label: {
      color: '#0f172a',
      fontSize: 13,
      fontWeight: 700,
      backgroundColor: 'rgba(255,255,255,0.88)',
      borderRadius: 8,
      padding: [4, 8],
    },
  }))
  const links = props.relationships.map(r => ({
    source: r.source_id,
    target: r.target_id,
    sourceName: entityNameById.get(r.source_id) || r.source_id,
    targetName: entityNameById.get(r.target_id) || r.target_id,
    value: r.relation_type,
  }))
  return {
    animationDuration: 250,
    animationDurationUpdate: 250,
    legend: [{
      top: 0,
      left: 'center',
      itemWidth: 12,
      itemHeight: 12,
      icon: 'circle',
      textStyle: {
        color: '#334155',
        fontSize: 12,
        fontWeight: 600,
      },
      data: activeCategories.map((category) => (visualCategoryConfig[category] || visualCategoryConfig.其他).label),
    }],
    tooltip: {
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderWidth: 0,
      textStyle: { color: '#f8fafc' },
      formatter(params) {
        if (params.dataType === 'edge') {
          return `${params.data.sourceName || params.data.source} → ${params.data.targetName || params.data.target}<br/>关系：${params.data.value || '-'}`
        }
        return `${params.data.displayName || params.data.name}<br/>类型：${params.data.category || '其他'}`
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      data: nodes,
      links,
      categories: activeCategories.map((category) => ({
        name: (visualCategoryConfig[category] || visualCategoryConfig.其他).label,
        itemStyle: {
          color: (visualCategoryConfig[category] || visualCategoryConfig.其他).color,
        },
      })),
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [0, 9],
      label: {
        show: true,
        position: 'bottom',
        distance: 10,
        fontWeight: 700,
        formatter: ({ data }) => data.displayName || data.name,
      },
      lineStyle: {
        color: 'rgba(59, 130, 246, 0.55)',
        width: 2,
        curveness: 0.22,
        opacity: 0.9,
      },
      edgeLabel: {
        show: true,
        formatter: ({ data }) => data.value || '',
        color: '#1e293b',
        fontSize: 11,
        fontWeight: 700,
        backgroundColor: 'rgba(255,255,255,0.92)',
        borderColor: 'rgba(148, 163, 184, 0.55)',
        borderWidth: 1,
        borderRadius: 6,
        padding: [3, 6],
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: {
          width: 3,
          color: 'rgba(37, 99, 235, 0.95)',
        },
      },
      blur: {
        itemStyle: { opacity: 0.2 },
        lineStyle: { opacity: 0.15 },
        label: { opacity: 0.2 },
        edgeLabel: { opacity: 0.2 },
      },
      force: {
        repulsion: 480,
        edgeLength: [120, 190],
        friction: 0.08,
        gravity: 0.04,
      },
    }],
  }
})

function onClick(params) {
  if (params.dataType === 'node') emit('select', params.data.id)
}
</script>

<style scoped>
.entity-graph {
  background:
    radial-gradient(circle at top right, rgba(191, 219, 254, 0.45), transparent 32%),
    linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.entity-graph__canvas {
  background:
    linear-gradient(rgba(148, 163, 184, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.08) 1px, transparent 1px),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(241, 245, 249, 0.96) 100%);
  background-position: 0 0, 0 0, 0 0;
  background-size: 28px 28px, 28px 28px, auto;
}
</style>
