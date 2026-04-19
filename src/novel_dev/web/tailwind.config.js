/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{vue,js,ts}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      colors: {
        'nd-primary': '#3b82f6',
        'nd-success': '#22c55e',
        'nd-warning': '#f59e0b',
        'nd-danger': '#ef4444',
        'nd-purple': '#a855f7',
      },
    },
  },
  plugins: [],
}
