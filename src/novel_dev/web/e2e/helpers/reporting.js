import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

function safeIssueFileStem(id) {
  const stem = String(id || '')
    .replace(/\.\./g, '')
    .replace(/[\\/]/g, '-')
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^[.-]+|[.-]+$/g, '')

  return stem || 'web-issue'
}

export function writeWebIssue(issue) {
  const reportDir = process.env.TEST_RUN_REPORT_DIR
  if (!reportDir) return

  const issueDir = join(reportDir, 'artifacts', 'web-issues')
  mkdirSync(issueDir, { recursive: true })
  writeFileSync(
    join(issueDir, `${safeIssueFileStem(issue.id)}.json`),
    `${JSON.stringify(issue, null, 2)}\n`,
    'utf8'
  )
}
