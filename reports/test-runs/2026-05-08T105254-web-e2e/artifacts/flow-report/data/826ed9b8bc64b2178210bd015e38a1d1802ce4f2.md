# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: flows/generation.spec.js >> web generation flow >> creates a novel and opens the AI setting generation workbench
- Location: e2e/flows/generation.spec.js:35:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByPlaceholder('选择或输入小说')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for getByPlaceholder('选择或输入小说')

```

# Page snapshot

```yaml
- generic [ref=e5]:
  - complementary [ref=e6]:
    - generic [ref=e7]:
      - paragraph [ref=e8]: Story Engine
      - heading "Novel Dev" [level=1] [ref=e9]
      - paragraph [ref=e10]: 把设定、卷纲、正文和知识库统一收敛在一个工作台里。
    - generic [ref=e12]:
      - generic [ref=e13]:
        - generic [ref=e14]:
          - generic [ref=e15]: Workspace
          - generic [ref=e16]: 小说工作区
        - generic [ref=e17]: 4 部
      - generic [ref=e19]:
        - generic:
          - combobox [ref=e21]
          - generic [ref=e22]: 选择或输入小说
        - img [ref=e25] [cursor=pointer]
      - generic [ref=e27]:
        - button "加载" [disabled] [ref=e28]:
          - generic [ref=e29]: 加载
        - button "新建" [ref=e30] [cursor=pointer]:
          - generic [ref=e31]: 新建
      - generic [ref=e32]: 先选定小说，再进入资料、卷纲和正文模块，避免不同项目上下文串线。
    - navigation [ref=e33]:
      - link "仪表盘 总览项目状态、风险、建议动作与实时更新。" [ref=e34] [cursor=pointer]:
        - /url: /dashboard
        - generic [ref=e35]: 仪表盘
        - generic [ref=e36]: 总览项目状态、风险、建议动作与实时更新。
      - link "设定与文风 管理资料导入、审核和已生效的设定与文风档案。" [ref=e37] [cursor=pointer]:
        - /url: /documents
        - generic [ref=e38]: 设定与文风
        - generic [ref=e39]: 管理资料导入、审核和已生效的设定与文风档案。
      - link "大纲规划 围绕总纲和卷纲持续迭代，沉淀工作区草稿。" [ref=e40] [cursor=pointer]:
        - /url: /volume-plan
        - generic [ref=e41]: 大纲规划
        - generic [ref=e42]: 围绕总纲和卷纲持续迭代，沉淀工作区草稿。
      - link "章节列表 查看章节状态、推进节奏和当前创作进度。" [ref=e43] [cursor=pointer]:
        - /url: /chapters
        - generic [ref=e44]: 章节列表
        - generic [ref=e45]: 查看章节状态、推进节奏和当前创作进度。
      - link "实体百科 统一管理角色、组织、地点与实体关系。" [ref=e46] [cursor=pointer]:
        - /url: /entities
        - generic [ref=e47]: 实体百科
        - generic [ref=e48]: 统一管理角色、组织、地点与实体关系。
      - link "时间线 检查世界事件与章节推进是否保持一致。" [ref=e49] [cursor=pointer]:
        - /url: /timeline
        - generic [ref=e50]: 时间线
        - generic [ref=e51]: 检查世界事件与章节推进是否保持一致。
      - link "地点 按地点维度审查空间设定与出场信息。" [ref=e52] [cursor=pointer]:
        - /url: /locations
        - generic [ref=e53]: 地点
        - generic [ref=e54]: 按地点维度审查空间设定与出场信息。
      - link "伏笔 追踪伏笔布置、兑现进度和遗漏风险。" [ref=e55] [cursor=pointer]:
        - /url: /foreshadowings
        - generic [ref=e56]: 伏笔
        - generic [ref=e57]: 追踪伏笔布置、兑现进度和遗漏风险。
      - link "模型配置 调整模型、驱动与运行时参数。" [ref=e58] [cursor=pointer]:
        - /url: /config
        - generic [ref=e59]: 模型配置
        - generic [ref=e60]: 调整模型、驱动与运行时参数。
      - link "实时日志 查看系统实时输出与任务执行状态。" [ref=e61] [cursor=pointer]:
        - /url: /logs
        - generic [ref=e62]: 实时日志
        - generic [ref=e63]: 查看系统实时输出与任务执行状态。
    - generic [ref=e64]: 当前界面重点是让信息优先级更清楚，减少“所有模块都一样重”的视觉噪音。
  - main [ref=e65]:
    - generic [ref=e66]:
      - generic [ref=e67]:
        - paragraph [ref=e68]: Overview
        - heading "仪表盘" [level=2] [ref=e69]
        - paragraph [ref=e70]: 总览项目状态、风险、建议动作与实时更新。
      - generic [ref=e71]:
        - generic [ref=e72]: 未选择小说
        - generic [ref=e73]: "-"
        - button "切换暗黑模式" [ref=e74] [cursor=pointer]:
          - img [ref=e76]
    - generic [ref=e81]:
      - paragraph [ref=e82]: 请从侧边栏选择或输入一个小说 ID
      - paragraph [ref=e83]: 选中小说后，这里会展示总览、状态卡、实时日志和推荐动作。
```

# Test source

```ts
  1   | import { expect, test } from '@playwright/test'
  2   | import { writeWebIssue } from '../helpers/reporting.js'
  3   | import {
  4   |   expectNoCollectedErrors,
  5   |   expectUsablePage,
  6   |   installPageErrorCollector,
  7   | } from '../helpers/visualChecks.js'
  8   | 
  9   | async function apiPost(request, url, data, issueId) {
  10  |   const response = await request.post(url, { data })
  11  |   if (!response.ok()) {
  12  |     const body = await response.text()
  13  |     writeWebIssue({
  14  |       id: issueId,
  15  |       type: 'SYSTEM_BUG',
  16  |       severity: 'high',
  17  |       stage: 'web_generation_flow',
  18  |       message: `POST ${url} returned ${response.status()}`,
  19  |       evidence: [body],
  20  |       reproduce: 'cd src/novel_dev/web && npm run test:e2e -- e2e/flows/generation.spec.js',
  21  |     })
  22  |   }
  23  |   expect(response.ok(), `POST ${url} should succeed`).toBeTruthy()
  24  |   return response.json()
  25  | }
  26  | 
  27  | async function loadNovelFromSidebar(page, novelId) {
  28  |   const selector = page.getByPlaceholder('选择或输入小说')
> 29  |   await expect(selector).toBeVisible()
      |                          ^ Error: expect(locator).toBeVisible() failed
  30  |   await selector.fill(novelId)
  31  |   await page.getByRole('button', { name: '加载' }).click()
  32  | }
  33  | 
  34  | test.describe('web generation flow', () => {
  35  |   test('creates a novel and opens the AI setting generation workbench', async ({ page, request }) => {
  36  |     const title = `Codex Web Generation ${Date.now()}`
  37  |     const sessionTitle = `Codex AI Settings ${Date.now()}`
  38  |     const errors = installPageErrorCollector(page)
  39  | 
  40  |     const novel = await apiPost(request, '/api/novels', { title }, 'web-generation-create-novel')
  41  |     expect(novel.novel_id).toBeTruthy()
  42  |     expect(novel.title).toBe(title)
  43  | 
  44  |     await page.goto('/dashboard')
  45  |     await expectUsablePage(page, errors)
  46  |     await loadNovelFromSidebar(page, novel.novel_id)
  47  |     await expect(page.locator('#app')).toContainText(/仪表盘|Dashboard Overview|章节评分与总评/)
  48  |     await expect(page.locator('#app')).toContainText(new RegExp(`${title}|${novel.novel_id}`))
  49  | 
  50  |     const settingSession = await apiPost(
  51  |       request,
  52  |       `/api/novels/${novel.novel_id}/settings/sessions`,
  53  |       {
  54  |         title: sessionTitle,
  55  |         initial_idea: '用于端到端页面校验的设定生成会话。',
  56  |         target_categories: [],
  57  |       },
  58  |       'web-generation-create-setting-session'
  59  |     )
  60  |     expect(settingSession.id).toBeTruthy()
  61  |     expect(settingSession.title).toBe(sessionTitle)
  62  | 
  63  |     await page.goto('/documents?tab=ai')
  64  |     await expectUsablePage(page, errors)
  65  |     await loadNovelFromSidebar(page, novel.novel_id)
  66  |     await expect(page.locator('.page-shell')).toContainText(/AI 生成设定|设定生成|Knowledge Base|资料管理/)
  67  |     await expect(page.locator('.page-shell')).toContainText(new RegExp(`${sessionTitle}|AI 生成设定|设定会话|创建新设定`))
  68  | 
  69  |     let replyRequested = false
  70  |     let generateRequested = false
  71  |     await page.route(
  72  |       `**/api/novels/${novel.novel_id}/settings/sessions/${settingSession.id}/reply`,
  73  |       async (route) => {
  74  |         replyRequested = true
  75  |         await route.fulfill({
  76  |           status: 200,
  77  |           contentType: 'application/json',
  78  |           body: JSON.stringify({
  79  |             session: {
  80  |               ...settingSession,
  81  |               status: 'ready_to_generate',
  82  |             },
  83  |             assistant_message: '设定目标已明确，可以生成审核记录。',
  84  |             questions: [],
  85  |           }),
  86  |         })
  87  |       }
  88  |     )
  89  |     await page.route(
  90  |       `**/api/novels/${novel.novel_id}/settings/sessions/${settingSession.id}/generate`,
  91  |       async (route) => {
  92  |         generateRequested = true
  93  |         await route.fulfill({
  94  |           status: 200,
  95  |           contentType: 'application/json',
  96  |           body: JSON.stringify({
  97  |             id: `batch-${Date.now()}`,
  98  |             source_session_id: settingSession.id,
  99  |             source_session_title: sessionTitle,
  100 |             status: 'pending',
  101 |             summary: 'UI 生成审核批次',
  102 |             counts: { create: 1, update: 0, conflict: 0 },
  103 |           }),
  104 |         })
  105 |       }
  106 |     )
  107 | 
  108 |     await page.getByRole('button', { name: sessionTitle }).click()
  109 |     await page.getByTestId('setting-session-reply').fill('目标明确，请继续生成审核记录。')
  110 |     await page.getByTestId('setting-session-reply-submit').click()
  111 |     await expect.poll(() => replyRequested).toBe(true)
  112 |     await expect(page.locator('.setting-ai-panel')).toContainText('设定目标已明确')
  113 | 
  114 |     await page.getByTestId('setting-generate-review').click()
  115 |     await expect.poll(() => generateRequested).toBe(true)
  116 |     await expect(page.locator('.page-shell')).toContainText(/UI 生成审核批次|审核记录/)
  117 |     expectNoCollectedErrors(errors)
  118 |   })
  119 | })
  120 | 
```