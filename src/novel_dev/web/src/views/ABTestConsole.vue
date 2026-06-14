<template>
  <div class="ab-test-console" data-testid="ab-test-console">
    <header class="header">
      <h2>A/B Test 控制台</h2>
      <button @click="showCreate = true" data-testid="create-ab-btn" class="primary">
        新建 A/B
      </button>
    </header>

    <section>
      <h3>运行中</h3>
      <div v-if="!runningTests.length" data-testid="running-empty" class="empty">
        当前没有运行中的 A/B 测试
      </div>
      <div
        v-for="t in runningTests"
        :key="t.id"
        data-testid="ab-test-card"
        class="card"
      >
        <div class="card-header">
          <strong>{{ t.agent_name }}</strong>
          <span class="versions">{{ t.baseline_version }} vs {{ t.challenger_version }}</span>
          <span class="status running">running</span>
        </div>
        <div v-if="t.results" class="results">
          baseline mean: {{ formatNum(t.results.baseline_mean) }},
          challenger mean: {{ formatNum(t.results.challenger_mean) }},
          p = {{ formatNum(t.results.p_value) }}
          <span v-if="t.results.winner" class="winner-badge">
            赢家: {{ t.results.winner }}
          </span>
        </div>
        <div class="card-actions">
          <button data-testid="view-results-btn" @click="viewResults(t)">查看详细</button>
          <button data-testid="stop-btn" @click="stop(t)">停止</button>
          <button
            v-if="t.results?.winner"
            data-testid="declare-winner-btn"
            @click="declareWinner(t)"
          >
            采纳 {{ t.results.winner }}
          </button>
        </div>
      </div>
    </section>

    <section>
      <h3>历史</h3>
      <div v-if="!completedTests.length" data-testid="history-empty" class="empty">
        暂无历史
      </div>
      <div
        v-for="t in completedTests"
        :key="t.id"
        data-testid="ab-test-history"
        class="history-row"
      >
        <span>{{ t.agent_name }}</span>
        <span>{{ t.baseline_version }} vs {{ t.challenger_version }}</span>
        <span>赢家: {{ t.winner || '无' }}</span>
        <span class="status">{{ t.status }}</span>
      </div>
    </section>

    <!-- 新建 A/B 弹窗 -->
    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal">
        <h3>新建 A/B 测试</h3>
        <label>Agent
          <select v-model="newTest.agent_name">
            <option v-for="a in AGENT_NAMES" :key="a" :value="a">{{ a }}</option>
          </select>
        </label>
        <label>Baseline 版本 <input v-model="newTest.baseline_version" placeholder="v1.0" /></label>
        <label>Challenger 版本 <input v-model="newTest.challenger_version" placeholder="v2.0" /></label>
        <label>Max samples <input type="number" v-model.number="newTest.max_samples" /></label>
        <label>Min samples <input type="number" v-model.number="newTest.min_samples" /></label>
        <div class="modal-actions">
          <button @click="showCreate = false">取消</button>
          <button @click="createTest" data-testid="create-confirm" class="primary">创建</button>
        </div>
      </div>
    </div>

    <!-- 详细结果弹窗 -->
    <div v-if="showResults" class="modal-backdrop" @click.self="showResults = false">
      <div class="modal">
        <h3>详细结果</h3>
        <pre v-if="resultsTarget" data-testid="results-detail">{{ JSON.stringify(resultsTarget, null, 2) }}</pre>
        <div class="modal-actions">
          <button @click="showResults = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const AGENT_NAMES = [
  'brainstorm', 'volume_planner', 'context_agent',
  'writer', 'critic', 'editor',
  'fast_review', 'librarian', 'root_cause_analyzer'
]

const tests = ref([])
const showCreate = ref(false)
const showResults = ref(false)
const resultsTarget = ref(null)
const newTest = ref({
  agent_name: 'writer',
  baseline_version: '',
  challenger_version: '',
  max_samples: 10,
  min_samples: 3,
})

const runningTests = computed(() => tests.value.filter(t => t.status === 'running'))
const completedTests = computed(() => tests.value.filter(t => t.status !== 'running'))

const fetchTests = async () => {
  try {
    const resp = await axios.get('/api/ab-tests')
    tests.value = resp.data?.tests || []
  } catch (e) {
    console.error('fetchTests failed', e)
    tests.value = []
  }
}

const stop = async (t) => {
  if (!confirm(`确认停止测试 ${t.id}?`)) return
  try {
    await axios.post(`/api/ab-tests/${t.id}/stop`)
    await fetchTests()
  } catch (e) {
    console.error('stop failed', e)
  }
}

const declareWinner = async (t) => {
  try {
    await axios.post(`/api/ab-tests/${t.id}/declare-winner`, { winner: t.results.winner })
    await fetchTests()
  } catch (e) {
    console.error('declareWinner failed', e)
  }
}

const viewResults = async (t) => {
  try {
    const resp = await axios.get(`/api/ab-tests/${t.id}`)
    resultsTarget.value = resp.data
    showResults.value = true
  } catch (e) {
    console.error('viewResults failed', e)
  }
}

const createTest = async () => {
  try {
    await axios.post('/api/ab-tests', { ...newTest.value })
    showCreate.value = false
    newTest.value = { agent_name: 'writer', baseline_version: '', challenger_version: '', max_samples: 10, min_samples: 3 }
    await fetchTests()
  } catch (e) {
    console.error('createTest failed', e)
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

const formatNum = (n) => {
  if (n == null) return '-'
  return typeof n === 'number' ? n.toFixed(3) : n
}

onMounted(fetchTests)
</script>

<style scoped>
.ab-test-console { padding: 1rem; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.empty { padding: 1rem; text-align: center; color: #666; }
.card { padding: 1rem; margin-bottom: 0.5rem; border: 1px solid #e5e7eb; border-radius: 0.375rem; }
.card-header { display: flex; gap: 1rem; align-items: center; }
.versions { color: #6b7280; }
.status { padding: 0.125rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; }
.status.running { background: #dbeafe; color: #1e40af; }
.results { margin: 0.5rem 0; color: #6b7280; }
.winner-badge { background: #dcfce7; color: #166534; padding: 0.125rem 0.5rem; border-radius: 0.25rem; margin-left: 0.5rem; }
.card-actions { display: flex; gap: 0.5rem; }
.history-row { display: flex; gap: 1rem; padding: 0.5rem; border-bottom: 1px solid #f3f4f6; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; padding: 1.5rem; border-radius: 0.5rem; max-width: 600px; width: 90%; }
.modal label { display: block; margin-bottom: 0.5rem; }
.modal input, .modal select { width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 0.25rem; }
.modal-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
button { padding: 0.375rem 0.75rem; border: 1px solid #ddd; background: white; border-radius: 0.25rem; cursor: pointer; }
button.primary { background: #2563eb; color: white; border-color: #2563eb; }
</style>
