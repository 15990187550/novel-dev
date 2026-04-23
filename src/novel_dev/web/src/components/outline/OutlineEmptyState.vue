<template>
  <section class="outline-empty-state px-6 py-10 text-center">
    <div class="outline-empty-state__title">{{ title }}</div>
    <p class="outline-empty-state__description mx-auto mt-2 max-w-2xl whitespace-pre-wrap text-sm leading-6">
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

<style scoped>
.outline-empty-state {
  border: 1px dashed var(--app-border);
  border-radius: 1rem;
  background: var(--app-surface-soft);
}

.outline-empty-state__title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--app-text);
}

.outline-empty-state__description {
  color: var(--app-text-muted);
}
</style>
