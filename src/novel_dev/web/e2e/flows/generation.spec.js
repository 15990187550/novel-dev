import { expect, test } from '@playwright/test'
import { writeWebIssue } from '../helpers/reporting.js'
import {
  expectNoCollectedErrors,
  expectUsablePage,
  installPageErrorCollector,
} from '../helpers/visualChecks.js'

async function apiPost(request, url, data, issueId) {
  const response = await request.post(url, { data })
  if (!response.ok()) {
    const body = await response.text()
    writeWebIssue({
      id: issueId,
      type: 'SYSTEM_BUG',
      severity: 'high',
      stage: 'web_generation_flow',
      message: `POST ${url} returned ${response.status()}`,
      evidence: [body],
      reproduce: 'cd src/novel_dev/web && npm run test:e2e -- e2e/flows/generation.spec.js',
    })
  }
  expect(response.ok(), `POST ${url} should succeed`).toBeTruthy()
  return response.json()
}

async function loadNovelFromSidebar(page, novelId) {
  const selector = page.getByPlaceholder('选择或输入小说')
  await expect(selector).toBeVisible()
  await selector.fill(novelId)
  await page.getByRole('button', { name: '加载' }).click()
}

test.describe('web generation flow', () => {
  test('creates a novel and opens the AI setting generation workbench', async ({ page, request }) => {
    const title = `Codex Web Generation ${Date.now()}`
    const sessionTitle = `Codex AI Settings ${Date.now()}`
    const errors = installPageErrorCollector(page)

    const novel = await apiPost(request, '/api/novels', { title }, 'web-generation-create-novel')
    expect(novel.novel_id).toBeTruthy()
    expect(novel.title).toBe(title)

    await page.goto('/dashboard')
    await expectUsablePage(page, errors)
    await loadNovelFromSidebar(page, novel.novel_id)
    await expect(page.locator('#app')).toContainText(/仪表盘|Dashboard Overview|章节评分与总评/)
    await expect(page.locator('#app')).toContainText(new RegExp(`${title}|${novel.novel_id}`))

    const settingSession = await apiPost(
      request,
      `/api/novels/${novel.novel_id}/settings/sessions`,
      {
        title: sessionTitle,
        initial_idea: '用于端到端页面校验的设定生成会话。',
        target_categories: [],
      },
      'web-generation-create-setting-session'
    )
    expect(settingSession.id).toBeTruthy()
    expect(settingSession.title).toBe(sessionTitle)

    await page.goto('/documents?tab=ai')
    await expectUsablePage(page, errors)
    await expect(page.locator('.page-shell')).toContainText(/AI 生成设定|设定生成|Knowledge Base|资料管理/)
    await expect(page.locator('.page-shell')).toContainText(new RegExp(`${sessionTitle}|AI 生成设定|设定会话|创建新设定`))
    expectNoCollectedErrors(errors)
  })
})
