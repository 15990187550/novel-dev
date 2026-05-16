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

    const novel = await apiPost(
      request,
      '/api/novels',
      {
        title,
        primary_category_slug: 'general',
        secondary_category_slug: 'uncategorized',
      },
      'web-generation-create-novel',
    )
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
    await loadNovelFromSidebar(page, novel.novel_id)
    await expect(page.locator('.page-shell')).toContainText(/AI 生成设定|设定生成|Knowledge Base|资料管理/)
    await expect(page.locator('.page-shell')).toContainText(new RegExp(`${sessionTitle}|AI 生成设定|设定会话|创建新设定`))

    let replyRequested = false
    let generateRequested = false
    await page.route(
      `**/api/novels/${novel.novel_id}/settings/sessions/${settingSession.id}/reply`,
      async (route) => {
        replyRequested = true
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            session: {
              ...settingSession,
              status: 'ready_to_generate',
            },
            assistant_message: '设定目标已明确，可以生成审核记录。',
            questions: [],
          }),
        })
      }
    )
    await page.route(
      `**/api/novels/${novel.novel_id}/settings/sessions/${settingSession.id}/generate`,
      async (route) => {
        generateRequested = true
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: `batch-${Date.now()}`,
            source_session_id: settingSession.id,
            source_session_title: sessionTitle,
            status: 'pending',
            summary: 'UI 生成审核批次',
            counts: { create: 1, update: 0, conflict: 0 },
          }),
        })
      }
    )

    await page.getByRole('button', { name: sessionTitle }).click()
    await page.getByTestId('setting-session-reply').fill('目标明确，请继续生成审核记录。')
    await page.getByTestId('setting-session-reply-submit').click()
    await expect.poll(() => replyRequested).toBe(true)
    await expect(page.locator('.setting-ai-panel')).toContainText('设定目标已明确')

    await page.getByTestId('setting-generate-review').click()
    await expect.poll(() => generateRequested).toBe(true)
    await expect(page.locator('.page-shell')).toContainText(/UI 生成审核批次|审核记录/)
    expectNoCollectedErrors(errors)
  })
})
