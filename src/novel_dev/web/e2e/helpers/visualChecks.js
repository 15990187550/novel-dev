import { expect } from '@playwright/test'

export function installPageErrorCollector(page) {
  const errors = []

  page.on('pageerror', (error) => {
    errors.push(`pageerror: ${error.message}`)
  })

  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(`console error: ${message.text()}`)
    }
  })

  return errors
}

export function expectNoCollectedErrors(errors) {
  expect(errors).toEqual([])
}

export async function expectUsablePage(page, errors, selector = '#app') {
  await page.waitForLoadState('networkidle')

  const app = page.locator(selector)
  await expect(app).toBeVisible()

  const bodyBox = await page.locator('body').boundingBox()
  expect(bodyBox, 'body should have a rendered box').not.toBeNull()
  expect(bodyBox.width, 'body should render with positive width').toBeGreaterThan(0)
  expect(bodyBox.height, 'body should render with positive height').toBeGreaterThan(0)

  const overflow = await page.evaluate(() => ({
    body: document.body.scrollWidth - document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }))
  expect(Math.max(overflow.body, overflow.document), 'page should not horizontally overflow').toBeLessThanOrEqual(1)

  expectNoCollectedErrors(errors)
}
