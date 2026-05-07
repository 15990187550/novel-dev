import { expect, test } from '@playwright/test'
import { expectUsablePage, installPageErrorCollector } from '../helpers/visualChecks.js'

const routes = [
  { path: '/dashboard', pattern: /仪表盘|请从侧边栏选择或输入一个小说 ID|总览项目状态/ },
  { path: '/documents', pattern: /设定与文风|Knowledge Base|请先选择或新建小说/ },
  { path: '/volume-plan', pattern: /大纲规划|Outline Workbench|请先选择小说/ },
  { path: '/chapters', pattern: /章节列表|持续写作|CONTINUOUS WRITING/ },
  { path: '/entities', pattern: /实体百科|实体数|请先选择或新建小说/ },
  { path: '/logs', pattern: /实时日志|Observability|日志/ },
  { path: '/config', pattern: /模型配置|配置项|全局默认配置/ },
]

test.describe('navigation smoke', () => {
  for (const route of routes) {
    test(`renders ${route.path}`, async ({ page }) => {
      const errors = installPageErrorCollector(page)

      await page.goto(route.path)

      await expectUsablePage(page, errors)
      await expect(page.locator('body')).toContainText(route.pattern)
    })
  }
})
