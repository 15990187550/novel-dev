import pytest

from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository
from novel_dev.schemas.brainstorm_workspace import SettingSuggestionCardPayload
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService


@pytest.mark.asyncio
async def test_get_workspace_payload_exposes_persisted_suggestion_cards(async_session):
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

    payload = await BrainstormWorkspaceService(async_session).get_workspace_payload("novel_cards")

    assert payload.setting_suggestion_cards[0].merge_key == "character:lu-zhao"


@pytest.mark.asyncio
async def test_workspace_repo_initializes_empty_suggestion_cards(async_session):
    workspace = await BrainstormWorkspaceRepository(async_session).get_or_create("novel_empty_cards")

    assert workspace.setting_suggestion_cards == []


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
