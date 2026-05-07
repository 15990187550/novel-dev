import { expect, test } from '@playwright/test'
import {
  expectNoCollectedErrors,
  expectUsablePage,
  installPageErrorCollector,
} from '../helpers/visualChecks.js'

test.describe('visual layout smoke', () => {
  test('dashboard renders usable routed layout', async ({ page }) => {
    const errors = installPageErrorCollector(page)

    await page.goto('/dashboard')

    await expectUsablePage(page, errors)
    await expect(page.locator('.page-shell')).toContainText(/请从侧边栏选择或输入一个小说 ID|Dashboard Overview|章节评分与总评/)
    expectNoCollectedErrors(errors)
  })
})
