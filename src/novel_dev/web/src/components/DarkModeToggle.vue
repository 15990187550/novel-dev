<template>
  <button
    @click="toggleDark()"
    class="app-icon-button app-icon-button--square"
    :title="isDark ? '切换亮色模式' : '切换暗黑模式'"
  >
    <el-icon v-if="isDark" :size="18"><Sunny /></el-icon>
    <el-icon v-else :size="18"><Moon /></el-icon>
  </button>
</template>

<script setup>
import { useDarkMode } from '@/composables/useDarkMode.js'
const { isDark, toggleDark } = useDarkMode()
</script>
