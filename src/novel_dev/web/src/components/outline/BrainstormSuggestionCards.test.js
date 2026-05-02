import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BrainstormSuggestionCards from './BrainstormSuggestionCards.vue'

const baseCard = {
  card_id: 'card-1',
  card_type: 'character',
  merge_key: 'character:lin-feng',
  title: '林风',
  summary: '青云宗外门弟子，身负机缘。',
  status: 'active',
  source_outline_refs: ['synopsis', 'vol_1'],
  payload: { canonical_name: '林风', goal: '逆天改命' },
  display_order: 1,
}

describe('BrainstormSuggestionCards', () => {
  it('renders smart primary actions and opens the detail drawer', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              action_hint: {
                recommended_action: 'submit_to_pending',
                primary_label: '转设定',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss', 'submit_to_pending'],
                reason: '这张卡包含可识别名称，可转为待审批设定。',
              },
            },
            {
              ...baseCard,
              card_id: 'card-2',
              card_type: 'revision',
              merge_key: 'revision:hook',
              title: '结尾钩子新颖度提升',
              summary: '开放钩子需要更独特。',
              payload: { focus: '结尾钩子' },
              action_hint: {
                recommended_action: 'continue_outline_feedback',
                primary_label: '继续优化',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '这张卡是大纲结构或主题表达建议，不是可落库的实体设定。',
              },
            },
            {
              ...baseCard,
              card_id: 'card-3',
              card_type: 'character',
              merge_key: 'character:unknown',
              title: '角色动机不足',
              payload: {},
              action_hint: {
                recommended_action: 'request_more_info',
                primary_label: '补充信息',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '这张设定类建议缺少可识别名称，需要先补充信息。',
              },
            },
          ],
        },
      },
    })

    expect(wrapper.text()).toContain('转设定')
    expect(wrapper.text()).toContain('继续优化')
    expect(wrapper.text()).toContain('补充信息')

    await wrapper.findAll('[data-testid="suggestion-process"]')[0].trigger('click')

    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('林风')
    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('可转为待审批设定')
  })

  it('emits fill-conversation for outline optimization cards without submitting', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              card_type: 'revision',
              action_hint: {
                recommended_action: 'continue_outline_feedback',
                primary_label: '继续优化',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '适合继续优化大纲。',
              },
            },
          ],
        },
      },
    })

    await wrapper.get('[data-testid="suggestion-primary-action"]').trigger('click')

    expect(wrapper.emitted('fill-conversation')).toHaveLength(1)
    expect(wrapper.emitted('fill-conversation')[0][0].card_id).toBe('card-1')
    expect(wrapper.emitted('update-card')).toBeUndefined()
  })

  it('emits submit_to_pending for cards whose primary action is transfer to setting', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              action_hint: {
                recommended_action: 'submit_to_pending',
                primary_label: '转设定',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss', 'submit_to_pending'],
                reason: '可转为待审批设定。',
              },
            },
          ],
        },
      },
    })

    await wrapper.get('[data-testid="suggestion-primary-action"]').trigger('click')

    expect(wrapper.emitted('update-card')[0][0]).toEqual({
      card: expect.objectContaining({ card_id: 'card-1' }),
      action: 'submit_to_pending',
    })
  })

  it('shows historical cards collapsed and disables relationship submit', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              card_id: 'card-history',
              status: 'resolved',
              title: '已解决卡片',
              action_hint: {
                recommended_action: 'open_detail',
                primary_label: '查看处理',
                available_actions: ['open_detail', 'reactivate'],
                reason: '这张卡已标记解决。',
              },
            },
            {
              ...baseCard,
              card_id: 'card-rel',
              card_type: 'relationship',
              merge_key: 'relationship:a-b',
              title: '关系建议',
              action_hint: {
                recommended_action: 'continue_outline_feedback',
                primary_label: '继续优化',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '关系建议将在最终确认时解析处理。',
              },
            },
          ],
        },
      },
    })

    expect(wrapper.text()).not.toContain('已解决卡片')
    await wrapper.get('[data-testid="toggle-suggestion-history"]').trigger('click')
    expect(wrapper.text()).toContain('已解决卡片')

    await wrapper.find('[data-testid="suggestion-process"]').trigger('click')
    expect(wrapper.get('[data-testid="submit-to-pending-action"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('关系建议将在最终确认时解析处理')
  })

  it('shows update errors inside the open detail drawer', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        actionError: 'Request timed out',
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              action_hint: {
                recommended_action: 'submit_to_pending',
                primary_label: '转设定',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss', 'submit_to_pending'],
                reason: '可转为待审批设定。',
              },
            },
          ],
        },
      },
    })

    await wrapper.get('[data-testid="suggestion-process"]').trigger('click')

    expect(wrapper.get('[data-testid="suggestion-action-error"]').text()).toContain('Request timed out')
    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('请检查后重试')
  })

  it('keeps the drawer bound to the latest card after workspace updates', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              action_hint: {
                recommended_action: 'submit_to_pending',
                primary_label: '转设定',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss', 'submit_to_pending'],
                reason: '可转为待审批设定。',
              },
            },
          ],
        },
      },
    })

    await wrapper.get('[data-testid="suggestion-process"]').trigger('click')
    await wrapper.setProps({
      workspace: {
        setting_suggestion_cards: [
          {
            ...baseCard,
            status: 'submitted',
            action_hint: {
              recommended_action: 'open_detail',
              primary_label: '查看处理',
              available_actions: ['open_detail'],
              reason: '这张卡已转为待审批设定，请在设定审批入口继续处理。',
            },
          },
        ],
      },
    })

    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('已转为待审批设定')
    expect(wrapper.get('[data-testid="submit-to-pending-action"]').attributes('disabled')).toBeDefined()
  })
})
