import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/views/Dashboard.vue') },
  { path: '/settings', redirect: (to) => ({ path: '/documents', query: { ...to.query, tab: 'ai' } }) },
  { path: '/documents', component: () => import('@/views/Documents.vue') },
  { path: '/settings', component: () => import('@/views/SettingWorkbench.vue') },
  { path: '/volume-plan', component: () => import('@/views/VolumePlan.vue') },
  { path: '/chapters', component: () => import('@/views/ChapterList.vue') },
  { path: '/chapters/:chapterId', component: () => import('@/views/ChapterDetail.vue') },
  { path: '/entities', component: () => import('@/views/Entities.vue') },
  { path: '/timeline', component: () => import('@/views/Timeline.vue') },
  { path: '/locations', component: () => import('@/views/Locations.vue') },
  { path: '/foreshadowings', component: () => import('@/views/Foreshadowings.vue') },
  { path: '/config', component: () => import('@/views/Config.vue') },
  { path: '/logs', component: () => import('@/views/RealtimeLog.vue') },
]

export default createRouter({ history: createWebHistory(), routes })
