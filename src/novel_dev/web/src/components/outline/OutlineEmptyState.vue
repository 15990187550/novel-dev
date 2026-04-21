<template>
  <section class="rounded-2xl border border-dashed border-gray-300 bg-gray-50/70 px-6 py-10 text-center">
    <div class="text-base font-semibold text-gray-800">{{ title }}</div>
    <p class="mx-auto mt-2 max-w-2xl whitespace-pre-wrap text-sm leading-6 text-gray-500">
      {{ description }}
    </p>
  </section>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: '暂无数据',
  },
  description: {
    type: String,
    default: '当前还没有可以展示的内容。',
  },
})
</script>
