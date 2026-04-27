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
          status: 'needs_revision',
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
        statusLabel: '需人工处理',
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

  it('ignores invalid items when resolving current item fallback', () => {
    const items = buildOutlineWorkbenchItems({
      items: [
        {
          title: '损坏数据',
          status: 'ready',
        },
        {
          outline_type: 'volume',
          outline_ref: 'vol_4',
          title: '第四卷',
          status: 'ready',
        },
      ],
      currentItem: {
        outline_type: 'missing',
        outline_ref: 'missing',
      },
    })

    expect(items[0].isCurrent).toBe(false)
    expect(items[1].isCurrent).toBe(true)
  })

  it('does not mark invalid first item as current when every fallback candidate is malformed', () => {
    const items = buildOutlineWorkbenchItems({
      items: [
        {
          title: '损坏数据',
          status: 'ready',
        },
      ],
      currentItem: {
        outline_type: 'missing',
        outline_ref: 'missing',
      },
    })

    expect(items[0].isCurrent).toBe(false)
  })
})
