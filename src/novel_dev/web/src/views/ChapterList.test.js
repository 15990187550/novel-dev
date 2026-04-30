import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNovelStore } from '@/stores/novel.js'
import ChapterList from './ChapterList.vue'

const chapterListSource = readFileSync(join(process.cwd(), 'src/views/ChapterList.vue'), 'utf8')

function makeChapters(count) {
  return Array.from({ length: count }, (_, index) => ({
    chapter_id: `ch-${index + 1}`,
    chapter_number: index + 1,
    title: `第${index + 1}章`,
    status: 'archived',
    word_count: 1000,
    target_word_count: 3000,
  }))
}

describe('ChapterList pagination', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function mountChapterList() {
    return mount(ChapterList, {
      global: {
        stubs: {
          ChapterProgressGantt: true,
          ElButton: {
            emits: ['click'],
            template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
          },
          ElInputNumber: {
            inheritAttrs: false,
            props: ['modelValue'],
            emits: ['update:modelValue'],
            template: '<input :data-testid="$attrs[\'data-testid\']" :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
          },
          ElSwitch: {
            props: ['modelValue'],
            emits: ['update:modelValue'],
            template: '<button v-bind="$attrs" @click="$emit(\'update:modelValue\', !modelValue)">{{ modelValue ? \'on\' : \'off\' }}</button>',
          },
          ElTag: true,
          ElProgress: true,
          ElTable: {
            name: 'ElTable',
            props: ['data'],
            provide() {
              return { tableRows: this.data }
            },
            template: '<div class="el-table-stub"><slot /></div>',
          },
          ElTableColumn: {
            inject: ['tableRows'],
            template: '<div class="el-table-column-stub"><div v-for="row in tableRows" :key="row.chapter_id"><slot :row="row" /></div></div>',
          },
          ElPagination: {
            name: 'ElPagination',
            props: ['currentPage', 'pageSize', 'total'],
            emits: ['update:current-page'],
            template: '<button class="pagination-stub" @click="$emit(\'update:current-page\', 3)">page {{ currentPage }}</button>',
          },
        },
        mocks: {
          $router: { push: vi.fn() },
        },
      },
    })
  }

  it('shows 20 chapters per page and can page through remaining chapters', async () => {
    const store = useNovelStore()
    store.chapters = makeChapters(45)

    const wrapper = mountChapterList()
    const table = () => wrapper.findComponent({ name: 'ElTable' })
    const pagination = wrapper.findComponent({ name: 'ElPagination' })

    expect(table().props('data')).toHaveLength(20)
    expect(table().props('data')[0].chapter_id).toBe('ch-1')
    expect(pagination.props('pageSize')).toBe(20)
    expect(pagination.props('total')).toBe(45)

    await pagination.trigger('click')

    expect(table().props('data')).toHaveLength(5)
    expect(table().props('data')[0].chapter_id).toBe('ch-41')
  })

  it('can jump directly to first and last page', async () => {
    const store = useNovelStore()
    store.chapters = makeChapters(45)

    const wrapper = mountChapterList()
    const table = () => wrapper.findComponent({ name: 'ElTable' })

    await wrapper.find('[data-testid="chapter-last-page"]').trigger('click')

    expect(table().props('data')).toHaveLength(5)
    expect(table().props('data')[0].chapter_id).toBe('ch-41')

    await wrapper.find('[data-testid="chapter-first-page"]').trigger('click')

    expect(table().props('data')).toHaveLength(20)
    expect(table().props('data')[0].chapter_id).toBe('ch-1')
  })

  it('only shows fixed chapter count when not stopping at volume end', async () => {
    const store = useNovelStore()
    store.novelState = {
      current_phase: 'drafting',
      current_chapter_id: 'ch-11',
    }
    store.chapters = makeChapters(60)
    store.executeAction = vi.fn().mockResolvedValue()

    const wrapper = mountChapterList()

    expect(wrapper.find('[data-testid="auto-run-count"]').exists()).toBe(false)

    await wrapper.find('[data-testid="start-continuous-writing"]').trigger('click')

    expect(store.executeAction).toHaveBeenLastCalledWith('auto_chapter', {
      max_chapters: 50,
      stop_at_volume_end: true,
    })

    await wrapper.find('[data-testid="stop-at-volume-end"]').trigger('click')

    expect(wrapper.find('[data-testid="auto-run-count"]').exists()).toBe(true)

    await wrapper.find('[data-testid="start-continuous-writing"]').trigger('click')

    expect(store.executeAction).toHaveBeenLastCalledWith('auto_chapter', {
      max_chapters: 5,
      stop_at_volume_end: false,
    })
  })

  it('themes pagination text for dark chapter panels', () => {
    expect(chapterListSource).toContain('--el-pagination-button-color: var(--app-text);')
    expect(chapterListSource).toContain('--el-pagination-button-disabled-color: var(--app-text-soft);')
    expect(chapterListSource).toContain('.chapter-pagination :deep(.el-pagination.is-background .el-pager li:not(.is-active))')
    expect(chapterListSource).toContain('color: var(--app-text);')
  })

  it('keeps drafted chapters eligible for rewrite retry after mid-flow failure', () => {
    expect(chapterListSource).toContain("const rewriteableStatuses = ['drafted', 'edited', 'archived']")
  })

  it('renders a continue action for failed rewrite jobs', () => {
    expect(chapterListSource).toContain('resumeRewriteChapter')
    expect(chapterListSource).toContain('继续')
    expect(chapterListSource).toContain('failed_job_id')
  })

  it('allows continuing a failed first-step rewrite while the chapter is still pending', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.chapters = [{
      chapter_id: 'ch-pending-failed',
      chapter_number: 1,
      title: '道经初现',
      status: 'pending',
      word_count: 0,
      target_word_count: 3000,
    }]
    store.chapterRewriteJobs = {
      'ch-pending-failed': {
        job_id: 'job-failed-context',
        status: 'failed',
        result_payload: {
          chapter_id: 'ch-pending-failed',
          failed_stage: 'context',
          resume_from_stage: 'context',
          can_resume: true,
        },
      },
    }
    store.rewriteChapter = vi.fn().mockResolvedValue({ job_id: 'job-resume-context' })

    const wrapper = mountChapterList()
    const continueButton = wrapper.findAll('button').find(button => button.text() === '继续')

    expect(continueButton).toBeTruthy()
    await continueButton.trigger('click')

    expect(store.rewriteChapter).toHaveBeenCalledWith('ch-pending-failed', {
      resume: true,
      failed_job_id: 'job-failed-context',
    })
  })
})
