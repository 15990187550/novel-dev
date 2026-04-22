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
  getSynopsis,
  getBrainstormWorkspace,
  getVolumePlan,
  getOutlineWorkbench,
  getOutlineWorkbenchMessages,
  planVolume,
  startBrainstormWorkspace,
  deleteEntity,
  submitBrainstormWorkspace,
  submitOutlineFeedback,
  updateEntity,
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
})
