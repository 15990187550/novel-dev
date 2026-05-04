import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import fs from 'node:fs'
import path from 'node:path'
import LogConsole from './LogConsole.vue'

describe('LogConsole', () => {
  function installAnimationFrameMock() {
    const original = globalThis.requestAnimationFrame
    globalThis.requestAnimationFrame = (callback) => {
      callback()
      return 1
    }
    return () => {
      if (original) globalThis.requestAnimationFrame = original
      else delete globalThis.requestAnimationFrame
    }
  }

  it('renders structured status, level and node labels when present', () => {
    const wrapper = mount(LogConsole, {
      props: {
        connected: true,
        logs: [
          {
            timestamp: '2026-04-25T01:00:00Z',
            agent: 'WriterAgent',
            level: 'warning',
            status: 'failed',
            node: 'generate_beat',
            message: '生成失败',
          },
        ],
      },
      global: {
        stubs: {
          ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
          ElButton: { template: '<button><slot /></button>' },
        },
      },
    })

    expect(wrapper.text()).toContain('warning')
    expect(wrapper.text()).toContain('failed')
    expect(wrapper.text()).toContain('generate_beat')
    expect(wrapper.text()).toContain('生成失败')
  })

  it('shows and toggles formatted metadata details only when metadata exists', async () => {
    const wrapper = mount(LogConsole, {
      props: {
        connected: true,
        logs: [
          {
            timestamp: '2026-04-25T01:00:00Z',
            agent: 'ContextAgent',
            level: 'info',
            status: 'succeeded',
            node: 'context_sources',
            message: '章节上下文来源已准备',
            metadata: {
              query: '山门 夜战',
              active_entities: [{ name: '陆照', preview: '负伤但清醒' }],
            },
          },
          {
            timestamp: '2026-04-25T01:00:01Z',
            agent: 'WriterAgent',
            level: 'info',
            message: '普通日志',
          },
        ],
      },
      global: {
        stubs: {
          ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
          ElButton: { template: '<button><slot /></button>' },
        },
      },
    })

    expect(wrapper.find('[data-testid="log-details-toggle-0"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="log-details-toggle-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="log-details-0"]').exists()).toBe(false)

    await wrapper.get('[data-testid="log-details-toggle-0"]').trigger('click')

    expect(wrapper.get('[data-testid="log-details-0"]').text()).toContain('"query": "山门 夜战"')
    expect(wrapper.get('[data-testid="log-details-0"]').text()).toContain('"name": "陆照"')

    await wrapper.get('[data-testid="log-details-toggle-0"]').trigger('click')

    expect(wrapper.find('[data-testid="log-details-0"]').exists()).toBe(false)
  })

  it('renders full prompt metadata as readable text in details', async () => {
    const prompt = '第一行 prompt\n第二行 prompt'
    const wrapper = mount(LogConsole, {
      props: {
        connected: true,
        logs: [
          {
            timestamp: '2026-04-25T01:00:00Z',
            agent: 'BrainstormAgent',
            level: 'info',
            status: 'started',
            node: 'llm_call',
            task: 'score_synopsis',
            message: 'score_synopsis 调用模型',
            metadata: {
              prompt_chars: prompt.length,
              prompt,
              prompt_preview: '第一行 prompt 第二行 prompt',
            },
          },
        ],
      },
      global: {
        stubs: {
          ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
          ElButton: { template: '<button><slot /></button>' },
        },
      },
    })

    await wrapper.get('[data-testid="log-details-toggle-0"]').trigger('click')

    const details = wrapper.get('[data-testid="log-details-0"]').text()
    expect(details).toContain('--- Prompt ---')
    expect(details).toContain(prompt)
    expect(details).not.toContain('"prompt": "第一行 prompt\\n第二行 prompt"')
  })

  it('scrolls to the bottom when opened with existing logs', async () => {
    const restoreAnimationFrame = installAnimationFrameMock()
    const scrollTo = vi.fn()
    const scrollHeightSpy = vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(2400)
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollTo,
    })

    try {
      const wrapper = mount(LogConsole, {
        props: {
          connected: true,
          logs: Array.from({ length: 30 }, (_, index) => ({
            timestamp: '2026-04-25T01:00:00Z',
            agent: 'WriterAgent',
            level: 'info',
            message: `日志 ${index + 1}`,
          })),
        },
        global: {
          stubs: {
            ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
            ElButton: { template: '<button><slot /></button>' },
          },
        },
      })

      await nextTick()
      await nextTick()

      expect(scrollTo).toHaveBeenCalledWith({ top: 2400, behavior: 'auto' })
      wrapper.unmount()
    } finally {
      restoreAnimationFrame()
      delete HTMLElement.prototype.scrollTo
      scrollHeightSpy.mockRestore()
    }
  })

  it('keeps log scrolling inside a viewport-height constrained panel', () => {
    const wrapper = mount(LogConsole, {
      props: { connected: true, logs: [] },
      global: {
        stubs: {
          ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
          ElButton: { template: '<button><slot /></button>' },
        },
      },
    })

    expect(wrapper.classes()).toContain('log-console')
    expect(wrapper.get('[data-testid="log-scroll-container"]').classes()).toContain('log-console__scroll')
  })

  it('anchors short log output to the bottom of the console', () => {
    const wrapper = mount(LogConsole, {
      props: {
        connected: true,
        logs: [
          { timestamp: '2026-04-25T01:00:00Z', agent: 'WriterAgent', level: 'info', message: '短日志' },
        ],
      },
      global: {
        stubs: {
          ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
          ElButton: { template: '<button><slot /></button>' },
        },
      },
    })

    expect(wrapper.get('[data-testid="log-entry-list"]').classes()).toEqual(expect.arrayContaining([
      'min-h-full',
    ]))
    expect(wrapper.get('[data-testid="log-line-0"]').exists()).toBe(true)
  })

  it('uses explicit CSS to bottom-align short logs', () => {
    const source = fs.readFileSync(path.resolve(__dirname, './LogConsole.vue'), 'utf8')

    expect(source).toMatch(/\.log-console__entries\s*{[\s\S]*justify-content:\s*flex-end;/)
  })

  it('inherits the page height instead of using its own viewport floor', () => {
    const source = fs.readFileSync(path.resolve(__dirname, './LogConsole.vue'), 'utf8')

    expect(source).not.toMatch(/\.log-console\s*{[\s\S]*min-height:\s*calc\(100vh/)
  })

  it('keeps the bottom pinned when the log content height changes after render', async () => {
    const restoreAnimationFrame = installAnimationFrameMock()
    const scrollTo = vi.fn()
    let resizeCallback
    const originalResizeObserver = globalThis.ResizeObserver
    globalThis.ResizeObserver = vi.fn().mockImplementation((callback) => {
      resizeCallback = callback
      return {
        observe: vi.fn(),
        disconnect: vi.fn(),
      }
    })

    try {
      const wrapper = mount(LogConsole, {
        props: {
          connected: true,
          logs: [
            { timestamp: '2026-04-25T01:00:00Z', agent: 'WriterAgent', level: 'info', message: '旧日志' },
          ],
        },
        global: {
          stubs: {
            ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
            ElButton: { template: '<button><slot /></button>' },
          },
        },
      })
      const scroller = wrapper.get('[data-testid="log-scroll-container"]').element
      Object.defineProperties(scroller, {
        scrollTop: { configurable: true, writable: true, value: 800 },
        clientHeight: { configurable: true, value: 200 },
        scrollHeight: { configurable: true, value: 1000 },
      })
      scroller.scrollTo = scrollTo
      await nextTick()
      await nextTick()
      scrollTo.mockClear()

      resizeCallback?.()
      await nextTick()
      await Promise.resolve()
      await Promise.resolve()

      expect(scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: 'auto' })
      wrapper.unmount()
    } finally {
      restoreAnimationFrame()
      if (originalResizeObserver) globalThis.ResizeObserver = originalResizeObserver
      else delete globalThis.ResizeObserver
    }
  })

  it('shows a new-log prompt instead of auto-scrolling when the user is reading history', async () => {
    const restoreAnimationFrame = installAnimationFrameMock()
    const scrollTo = vi.fn()
    const wrapper = mount(LogConsole, {
      props: {
        connected: true,
        logs: [
          { timestamp: '2026-04-25T01:00:00Z', agent: 'WriterAgent', level: 'info', message: '旧日志' },
        ],
      },
      global: {
        stubs: {
          ElTag: { props: ['type'], template: '<span class="el-tag-stub"><slot /></span>' },
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        },
      },
    })
    const scroller = wrapper.get('[data-testid="log-scroll-container"]').element
    Object.defineProperties(scroller, {
      scrollTop: { configurable: true, writable: true, value: 0 },
      clientHeight: { configurable: true, value: 200 },
      scrollHeight: { configurable: true, value: 1000 },
    })
    scroller.scrollTo = scrollTo
    await nextTick()
    await nextTick()
    scrollTo.mockClear()

    await wrapper.get('[data-testid="log-scroll-container"]').trigger('scroll')
    await wrapper.setProps({
      logs: [
        { timestamp: '2026-04-25T01:00:00Z', agent: 'WriterAgent', level: 'info', message: '旧日志' },
        { timestamp: '2026-04-25T01:00:01Z', agent: 'WriterAgent', level: 'info', message: '新日志' },
      ],
    })
    await nextTick()

    expect(scrollTo).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="new-log-prompt"]').text()).toContain('1 条新日志')

    await wrapper.get('[data-testid="new-log-prompt"]').trigger('click')

    expect(scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: 'smooth' })
    restoreAnimationFrame()
  })
})
