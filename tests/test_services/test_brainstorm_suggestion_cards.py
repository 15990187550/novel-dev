import pytest

from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository
from novel_dev.schemas.brainstorm_workspace import (
    BrainstormWorkspacePayload,
    SettingSuggestionCardPayload,
)


@pytest.mark.asyncio
async def test_workspace_payload_exposes_suggestion_cards(async_session):
    repo = BrainstormWorkspaceRepository(async_session)
    workspace = await repo.get_or_create("novel_cards")
    workspace.setting_suggestion_cards = [
        {
            "card_id": "card_1",
            "card_type": "character",
            "merge_key": "character:lu-zhao",
            "title": "陆照",
            "summary": "补充主角目标",
            "status": "active",
            "source_outline_refs": ["synopsis"],
            "payload": {"canonical_name": "陆照", "goal": "改命"},
            "display_order": 10,
        }
    ]
    await async_session.flush()

    payload = BrainstormWorkspacePayload.model_validate(
        {
            "workspace_id": workspace.id,
            "novel_id": workspace.novel_id,
            "status": workspace.status,
            "outline_drafts": workspace.outline_drafts,
            "setting_docs_draft": workspace.setting_docs_draft,
            "setting_suggestion_cards": workspace.setting_suggestion_cards,
        }
    )

    assert payload.setting_suggestion_cards[0].merge_key == "character:lu-zhao"


def test_setting_suggestion_card_requires_structured_fields():
    card = SettingSuggestionCardPayload.model_validate(
        {
            "card_id": "card_rel",
            "card_type": "relationship",
            "merge_key": "relationship:lu-zhao:su-qinghan",
            "title": "陆照 / 苏清寒",
            "summary": "互疑转合作",
            "status": "unresolved",
            "source_outline_refs": ["vol_1"],
            "payload": {
                "source_entity_ref": "陆照",
                "target_entity_ref": "苏清寒",
                "relation_type": "亦敌亦友",
                "unresolved_references": ["target_entity_card_key"],
            },
            "display_order": 20,
        }
    )

    assert card.status == "unresolved"
    assert card.payload["relation_type"] == "亦敌亦友"
