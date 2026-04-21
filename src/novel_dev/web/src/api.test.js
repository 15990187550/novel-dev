import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
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
      get: mockGet,
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
  getOutlineWorkbench,
  getOutlineWorkbenchMessages,
  submitOutlineFeedback,
} from '@/api.js'

describe('outline workbench api', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { ok: true } })
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

    expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/outline_workbench/submit', payload)
  })
})
