import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockDelete, mockGet, mockPatch, mockPost } = vi.hoisted(() => ({
  mockDelete: vi.fn(),
  mockGet: vi.fn(),
  mockPatch: vi.fn(),
  mockPost: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
  },
}))

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => ({
      delete: mockDelete,
      get: mockGet,
      patch: mockPatch,
      post: mockPost,
      interceptors: {
        response: {
          use: vi.fn(),
        },
      },
    })),
  },
}))

import {
  brainstorm,
  advance,
  autoRunChapters,
  draftChapter,
  rewriteChapter,
  getGenerationJob,
  getChapterRewriteJobs,
  getSynopsis,
  getBrainstormWorkspace,
  getVolumePlan,
  getOutlineWorkbench,
  getOutlineWorkbenchMessages,
  planVolume,
  prepareContext,
  runLibrarian,
  startBrainstormWorkspace,
  stopCurrentFlow,
  deleteEntity,
  submitBrainstormWorkspace,
  submitOutlineFeedback,
  updateNovel,
  updateEntity,
  getKnowledgeDomains,
  confirmKnowledgeDomainScope,
  clearLogs,
  getLogs,
  disableKnowledgeDomain,
  deleteKnowledgeDomain,
  testLLMModel,
} from '@/api.js'

describe('outline workbench api', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDelete.mockResolvedValue({ data: { ok: true } })
    mockGet.mockResolvedValue({ data: { ok: true } })
    mockPatch.mockResolvedValue({ data: { ok: true } })
    mockPost.mockResolvedValue({ data: { ok: true } })
  })

  it('requests outline workbench payload with query params', async () => {
    await expect(getOutlineWorkbench('novel-1', {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    })).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/outline_workbench', {
      params: {
        outline_type: 'synopsis',
        outline_ref: 'synopsis',
      },
    })
  })

  it('requests outline workbench messages with query params', async () => {
    await expect(getOutlineWorkbenchMessages('novel-1', {
      outline_type: 'volume',
      outline_ref: 'vol_2',
    })).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/outline_workbench/messages', {
      params: {
        outline_type: 'volume',
        outline_ref: 'vol_2',
      },
    })
  })

  it('submits outline feedback payload', async () => {
    const payload = {
      outline_type: 'volume',
      outline_ref: 'vol_2',
      content: '需要补强主线冲突',
    }

    await expect(submitOutlineFeedback('novel-1', payload)).resolves.toEqual({ ok: true })

    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/outline_workbench/submit', payload, {
      timeout: 180000,
    })
  })

  it('requests brainstorm workspace lifecycle endpoints', async () => {
    await expect(startBrainstormWorkspace('novel-1')).resolves.toEqual({ ok: true })
    await expect(getBrainstormWorkspace('novel-1')).resolves.toEqual({ ok: true })
    await expect(submitBrainstormWorkspace('novel-1')).resolves.toEqual({ ok: true })

    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/brainstorm/workspace/start')
    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/brainstorm/workspace')
    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/brainstorm/workspace/submit')
  })

  it('requests volume plan with silent error handling for missing plans', async () => {
    await expect(getVolumePlan('novel-1')).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/volume_plan', {
      __skipGlobalErrorMessage: true,
    })
  })

  it('requests synopsis with silent error handling for empty novels', async () => {
    await expect(getSynopsis('novel-1')).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/synopsis', {
      __skipGlobalErrorMessage: true,
    })
  })

  it('updates novel title', async () => {
    await expect(updateNovel('novel-1', '新标题')).resolves.toEqual({ ok: true })

    expect(mockPatch).toHaveBeenCalledWith('/novels/novel-1', { title: '新标题' })
  })

  it('updates and deletes entities through dedicated endpoints', async () => {
    const payload = {
      name: '林风',
      type: 'character',
      aliases: ['Lin Feng'],
      state_fields: {
        identity: '主角',
      },
    }

    await expect(updateEntity('novel-1', 'e1', payload)).resolves.toEqual({ ok: true })
    await expect(deleteEntity('novel-1', 'e1')).resolves.toEqual({ ok: true })

    expect(mockPatch).toHaveBeenCalledWith('/novels/novel-1/entities/e1', payload)
    expect(mockDelete).toHaveBeenCalledWith('/novels/novel-1/entities/e1')
  })

  it('requests knowledge domain endpoints', async () => {
    await expect(getKnowledgeDomains('novel-1', true)).resolves.toEqual({ ok: true })
    await expect(confirmKnowledgeDomainScope('novel-1', 'domain-1', {
      scope_type: 'volume',
      scope_refs: ['vol_2'],
    })).resolves.toEqual({ ok: true })
    await expect(disableKnowledgeDomain('novel-1', 'domain-1')).resolves.toEqual({ ok: true })
    await expect(deleteKnowledgeDomain('novel-1', 'domain-1')).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/knowledge_domains', {
      params: { include_disabled: true },
    })
    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/knowledge_domains/domain-1/confirm_scope', {
      scope_type: 'volume',
      scope_refs: ['vol_2'],
    })
    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/knowledge_domains/domain-1/disable')
    expect(mockDelete).toHaveBeenCalledWith('/novels/novel-1/knowledge_domains/domain-1')
  })

  it('uses a long timeout for brainstorm and volume planning requests', async () => {
    await expect(brainstorm('novel-1')).resolves.toEqual({ ok: true })
    await expect(planVolume('novel-1', 3)).resolves.toEqual({ ok: true })

    expect(mockPost).toHaveBeenNthCalledWith(1, '/novels/novel-1/brainstorm', null, {
      timeout: 180000,
    })
    expect(mockPost).toHaveBeenNthCalledWith(2, '/novels/novel-1/volume_plan', {
      volume_number: 3,
    }, {
      timeout: 180000,
    })
  })

  it('uses a long timeout for chapter generation flow requests', async () => {
    await expect(prepareContext('novel-1', 'ch-1')).resolves.toEqual({ ok: true })
    await expect(draftChapter('novel-1', 'ch-1')).resolves.toEqual({ ok: true })
    await expect(rewriteChapter('novel-1', 'ch-1')).resolves.toEqual({ ok: true })
    await expect(advance('novel-1')).resolves.toEqual({ ok: true })
    await expect(runLibrarian('novel-1')).resolves.toEqual({ ok: true })
    await expect(autoRunChapters('novel-1')).resolves.toEqual({ ok: true })

    expect(mockPost).toHaveBeenNthCalledWith(1, '/novels/novel-1/chapters/ch-1/context', null, {
      timeout: 180000,
    })
    expect(mockPost).toHaveBeenNthCalledWith(2, '/novels/novel-1/chapters/ch-1/draft', null, {
      timeout: 180000,
    })
    expect(mockPost).toHaveBeenNthCalledWith(3, '/novels/novel-1/chapters/ch-1/rewrite', null, {
      timeout: 180000,
    })
    expect(mockPost).toHaveBeenNthCalledWith(4, '/novels/novel-1/advance', null, {
      timeout: 180000,
    })
    expect(mockPost).toHaveBeenNthCalledWith(5, '/novels/novel-1/librarian', null, {
      timeout: 180000,
    })
    expect(mockPost).toHaveBeenNthCalledWith(6, '/novels/novel-1/chapters/auto-run', {
      max_chapters: 1,
      stop_at_volume_end: true,
    }, {
      timeout: 180000,
    })
  })

  it('posts resume payload when continuing a failed chapter rewrite', async () => {
    await expect(rewriteChapter('novel-1', 'ch-1', {
      resume: true,
      failed_job_id: 'job-failed-1',
    })).resolves.toEqual({ ok: true })

    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/chapters/ch-1/rewrite', {
      resume: true,
      failed_job_id: 'job-failed-1',
    }, {
      timeout: 180000,
    })
  })

  it('requests generation job status', async () => {
    await expect(getGenerationJob('novel-1', 'job-1')).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/generation_jobs/job-1')
  })

  it('requests persisted chapter rewrite jobs for the current novel', async () => {
    await expect(getChapterRewriteJobs('novel-1')).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/chapters/rewrite_jobs')
  })

  it('clears persisted logs for the current novel', async () => {
    await expect(clearLogs('novel-1')).resolves.toEqual({ ok: true })

    expect(mockDelete).toHaveBeenCalledWith('/novels/novel-1/logs')
  })

  it('requests persisted logs for the current novel', async () => {
    await expect(getLogs('novel-1')).resolves.toEqual({ ok: true })

    expect(mockGet).toHaveBeenCalledWith('/novels/novel-1/logs')
  })

  it('requests current flow stop endpoint', async () => {
    await expect(stopCurrentFlow('novel-1')).resolves.toEqual({ ok: true })

    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/flow/stop')
  })

  it('tests an unsaved LLM model profile through the config endpoint', async () => {
    const profile = {
      provider: 'anthropic',
      model: 'claude-test',
      base_url: 'https://api.example.test',
      api_key: 'sk-test',
    }

    await expect(testLLMModel('main', profile)).resolves.toEqual({ ok: true })

    expect(mockPost).toHaveBeenCalledWith('/config/llm/test_model', {
      name: 'main',
      profile,
    }, {
      timeout: 60000,
    })
  })
})
