import { describe, expect, it } from 'vitest'

describe('test harness smoke', () => {
  it('exposes browser globals used by the app', () => {
    expect(window).toBeDefined()
    expect(window.matchMedia).toBeDefined()
    expect(ResizeObserver).toBeDefined()
    expect(EventSource).toBeDefined()
  })
})
