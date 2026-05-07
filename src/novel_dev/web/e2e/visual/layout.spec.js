import { expect, test } from '@playwright/test'
import {
  expectNoCollectedErrors,
  expectUsablePage,
  installPageErrorCollector,
} from '../helpers/visualChecks.js'

const routes = [
  { path: '/dashboard', pattern: /请从侧边栏选择或输入一个小说 ID|Dashboard Overview|章节评分与总评/ },
  { path: '/documents', pattern: /Knowledge Base|资料管理|导入设定 \/ 文风/ },
  { path: '/volume-plan', pattern: /Outline Workbench|脑爆工作区|请先选择小说/ },
  { path: '/chapters', pattern: /CONTINUOUS WRITING|持续写作|开始持续写作/ },
  { path: '/entities', pattern: /左侧目录用于切换分类、分组和实体|当前未选择目录节点|关系图谱/ },
  { path: '/logs', pattern: /实时日志|清空|连接中|未连接/ },
  { path: '/config', pattern: /配置项|全局默认配置|模型 Profiles/ },
]

test.describe('visual layout smoke', () => {
  for (const route of routes) {
    test(`${route.path} renders usable routed layout`, async ({ page }) => {
      const errors = installPageErrorCollector(page)

      await page.goto(route.path)

      await expectUsablePage(page, errors)
      await expect(page.locator('.page-shell')).toContainText(route.pattern)
      expectNoCollectedErrors(errors)
    })
  }
})
