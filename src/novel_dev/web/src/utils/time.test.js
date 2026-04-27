import { describe, expect, it } from 'vitest'
import { formatBeijingDateTime, formatBeijingTime, timestampMs } from './time.js'

describe('time utils', () => {
  it('formats UTC timestamps as Beijing time', () => {
    expect(formatBeijingTime('2026-04-25T08:36:43Z')).toBe('16:36:43')
  })

  it('treats backend naive ISO timestamps as UTC', () => {
    expect(formatBeijingDateTime('2026-04-25T08:36:43')).toContain('2026/4/25 16:36:43')
  })

  it('parses equivalent UTC timestamps consistently', () => {
    expect(timestampMs('2026-04-25T08:36:43')).toBe(timestampMs('2026-04-25T08:36:43Z'))
  })
})
