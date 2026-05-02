import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const appSource = readFileSync(join(process.cwd(), 'src/App.vue'), 'utf8')
const styleSource = readFileSync(join(process.cwd(), 'src/style.css'), 'utf8')

describe('App shell layout', () => {
  it('keeps the desktop workspace inside the viewport with independent scrolling panes', () => {
    expect(appSource).toContain('h-[calc(100vh-1.5rem)]')
    expect(appSource).toContain('app-sidebar w-full min-h-0 overflow-auto lg:w-[19rem] lg:shrink-0')
    expect(appSource).toContain('flex min-h-0 min-w-0 flex-1 flex-col gap-4')
    expect(appSource).not.toContain('min-h-[calc(100vh-1.5rem)]')
    expect(appSource).not.toContain('lg:items-start')
    expect(styleSource).toMatch(/\.page-shell\s*{[\s\S]*height:\s*100%;[\s\S]*min-height:\s*0;/)
  })

  it('keeps documents available and adds the setting workbench navigation entry', () => {
    expect(appSource).toContain("path: '/documents'")
    expect(appSource).toContain("path: '/settings'")
    expect(appSource).toContain("label: '设定工作台'")
  })
})
