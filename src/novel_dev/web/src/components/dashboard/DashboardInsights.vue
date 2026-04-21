<template>
  <section class="dashboard-insights">
    <header class="dashboard-section-header">
      <div>
        <p class="dashboard-section-header__eyebrow">Insights</p>
        <h2 class="dashboard-section-header__title">{{ title }}</h2>
      </div>
      <p class="dashboard-section-header__meta">
        <span class="dashboard-insights__connected" :class="{ 'is-connected': connected }">
          {{ connected ? '实时连接中' : '连接已断开' }}
        </span>
      </p>
    </header>

    <div class="dashboard-insights__grid">
      <section class="dashboard-insights__panel">
        <h3 class="dashboard-insights__panel-title">最近更新</h3>
        <ul class="dashboard-insights__list">
          <li v-for="(item, index) in recentUpdates" :key="`${item.label}-${index}`" class="dashboard-insights__item">
            <span class="dashboard-insights__item-label">{{ item.label }}</span>
            <span class="dashboard-insights__item-detail">{{ item.detail }}</span>
          </li>
        </ul>
      </section>

      <section class="dashboard-insights__panel">
        <h3 class="dashboard-insights__panel-title">风险提醒</h3>
        <ul class="dashboard-insights__list">
          <li v-for="(item, index) in risks" :key="`${item.type || item.label}-${index}`" class="dashboard-insights__item">
            <span class="dashboard-insights__item-label">{{ item.label }}</span>
            <span class="dashboard-insights__item-detail">{{ item.detail }}</span>
          </li>
        </ul>
      </section>

      <section class="dashboard-insights__panel">
        <h3 class="dashboard-insights__panel-title">最近日志</h3>
        <ul class="dashboard-insights__list dashboard-insights__list--logs">
          <li v-for="(log, index) in recentLogs" :key="`${log.timestamp || log.message || index}`" class="dashboard-insights__item">
            <span class="dashboard-insights__item-label">{{ log.agent || log.level || '日志' }}</span>
            <span class="dashboard-insights__item-detail">{{ log.message }}</span>
          </li>
        </ul>
      </section>

      <section class="dashboard-insights__panel">
        <h3 class="dashboard-insights__panel-title">快捷链接</h3>
        <div class="dashboard-insights__links">
          <RouterLink
            v-for="(link, index) in links"
            :key="`${link.label || index}`"
            class="dashboard-insights__link"
            :to="link.route || link.to || '/dashboard'"
          >
            <span class="dashboard-insights__link-label">{{ link.label }}</span>
            <span class="dashboard-insights__link-detail">{{ link.detail || link.description || '' }}</span>
          </RouterLink>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, default: '洞察面板' },
  recentUpdates: { type: Array, default: () => [] },
  risks: { type: Array, default: () => [] },
  recentLogs: { type: Array, default: () => [] },
  connected: { type: Boolean, default: false },
  links: { type: Array, default: () => [] },
})
</script>

