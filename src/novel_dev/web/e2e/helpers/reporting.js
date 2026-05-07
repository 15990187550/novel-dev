import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

export function writeWebIssue(issue) {
  const reportDir = process.env.TEST_RUN_REPORT_DIR
  if (!reportDir) return

  const issueDir = join(reportDir, 'artifacts', 'web-issues')
  mkdirSync(issueDir, { recursive: true })
  writeFileSync(
    join(issueDir, `${issue.id}.json`),
    `${JSON.stringify(issue, null, 2)}\n`,
    'utf8'
  )
}
