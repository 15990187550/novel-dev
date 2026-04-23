import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BrainstormSuggestionCards from './BrainstormSuggestionCards.vue'

describe('BrainstormSuggestionCards', () => {
  it('renders active/unresolved cards, last-round summary, and warnings', () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              card_id: 'card-1',
              card_type: 'character',
              merge_key: 'character:lin-feng',
              title: '林风',
              summary: '青云宗外门弟子，身负机缘。',
              status: 'active',
              source_outline_refs: ['synopsis', 'vol_1'],
              display_order: 1,
            },
            {
              card_id: 'card-2',
              card_type: 'relationship',
              merge_key: 'relationship:a-b',
              title: '师徒关系',
              summary: '林风与师父之间的关键关系尚未明确。',
              status: 'unresolved',
              source_outline_refs: ['synopsis'],
              display_order: 2,
            },
            {
              card_id: 'card-3',
              card_type: 'item',
              merge_key: 'item:sword',
              title: '青锋剑',
              summary: '已被覆盖，不应显示。',
              status: 'superseded',
              source_outline_refs: ['vol_1'],
              display_order: 3,
            },
          ],
        },
        lastRoundSummary: { created: 1, updated: 2, superseded: 0, unresolved: 1 },
        submitWarnings: ['关系卡存在未解析项，最终确认时将跳过部分关系导入。'],
      },
    })

    expect(wrapper.text()).toContain('设定建议卡')
    expect(wrapper.text()).toContain('本轮设定更新')
    expect(wrapper.get('[data-testid="last-round-summary"]').text()).toContain('新增 1')
    expect(wrapper.get('[data-testid="unresolved-warning"]').text()).toContain('未解决')
    expect(wrapper.get('[data-testid="submit-warnings"]').text()).toContain('关系卡存在未解析项')

    expect(wrapper.text()).toContain('林风')
    expect(wrapper.text()).toContain('师徒关系')
    expect(wrapper.text()).not.toContain('青锋剑')

    const cards = wrapper.findAll('[data-testid="suggestion-card"]')
    expect(cards).toHaveLength(2)
  })

  it('renders empty state when there are no active cards', () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            { card_id: 'card-1', merge_key: 'x', title: '已覆盖', summary: '...', status: 'superseded' },
          ],
        },
      },
    })

    expect(wrapper.get('[data-testid="suggestion-empty"]').text()).toContain('当前还没有待处理的设定建议卡')
    expect(wrapper.findAll('[data-testid="suggestion-card"]')).toHaveLength(0)
  })
})

