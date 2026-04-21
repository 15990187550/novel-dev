import { describe, expect, it } from 'vitest'
import { buildOutlineWorkbenchItems } from './outlineWorkbench.js'

describe('outline workbench helpers', () => {
  it('normalizes synopsis and volume items with current item and status labels', () => {
    const items = buildOutlineWorkbenchItems({
      items: [
        {
          outline_type: 'synopsis',
          outline_ref: 'synopsis',
          title: '总纲',
          status: 'ready',
        },
        {
          outline_type: 'volume',
          outline_ref: 'vol_1',
          title: '第一卷',
          status: 'missing',
        },
      ],
      currentItem: {
        outline_type: 'volume',
        outline_ref: 'vol_1',
      },
    })

    expect(items).toMatchObject([
      {
        key: 'synopsis:synopsis',
        outlineType: 'synopsis',
        outlineRef: 'synopsis',
        itemId: 'synopsis:synopsis',
        isCurrent: false,
        statusLabel: '可编辑',
      },
      {
        key: 'volume:vol_1',
        outlineType: 'volume',
        outlineRef: 'vol_1',
        itemId: 'volume:vol_1',
        isCurrent: true,
        statusLabel: '待创建',
      },
    ])
  })

  it('uses an independent current item instead of selection to mark isCurrent', () => {
    const items = buildOutlineWorkbenchItems({
      items: [
        {
          outline_type: 'synopsis',
          outline_ref: 'synopsis',
          title: '总纲',
          status: 'ready',
        },
        {
          outline_type: 'volume',
          outline_ref: 'vol_2',
          title: '第二卷',
          status: 'ready',
        },
      ],
      currentItem: {
        outline_type: 'volume',
        outline_ref: 'vol_2',
      },
    })

    expect(items.find((item) => item.itemId === 'synopsis:synopsis')?.isCurrent).toBe(false)
    expect(items.find((item) => item.itemId === 'volume:vol_2')?.isCurrent).toBe(true)
  })
})
