import pytest

from novel_dev.db.models import NovelGenreTemplate, NovelState
from novel_dev.services.genre_template_service import GenreTemplateService


@pytest.mark.asyncio
async def test_resolve_merges_global_primary_secondary_for_novel(async_session):
    async_session.add(
        NovelState(
            novel_id="n_genre",
            current_phase="brainstorming",
            checkpoint_data={
                "genre": {
                    "primary_slug": "xuanhuan",
                    "primary_name": "玄幻",
                    "secondary_slug": "zhutian",
                    "secondary_name": "诸天文",
                }
            },
        )
    )
    await async_session.commit()

    template = await GenreTemplateService(async_session).resolve("n_genre", "WriterAgent", "generate_beat")

    assert template.genre.primary_slug == "xuanhuan"
    assert any("力量体系" in item for item in template.prompt_blocks["setting_rules"])
    assert any("跨世界" in item for item in template.prompt_blocks["setting_rules"])
    assert template.quality_config["modern_terms_policy"] == "block"
    assert template.quality_config["blocking_rules"]["source_domain_conflict"] is True


@pytest.mark.asyncio
async def test_resolve_uses_database_override_after_builtin_layers(async_session):
    async_session.add_all(
        [
            NovelState(
                novel_id="n_override",
                current_phase="brainstorming",
                checkpoint_data={
                    "genre": {
                        "primary_slug": "xuanhuan",
                        "primary_name": "玄幻",
                        "secondary_slug": "zhutian",
                        "secondary_name": "诸天文",
                    }
                },
            ),
            NovelGenreTemplate(
                scope="secondary",
                category_slug="zhutian",
                parent_slug="xuanhuan",
                agent_name="WriterAgent",
                task_name="generate_beat",
                prompt_blocks={"prose_rules": ["数据库二级正文规则"]},
                quality_config={"dimension_weights": {"readability": 1.4}},
                merge_policy={},
                enabled=True,
                version=3,
                source="db",
            ),
        ]
    )
    await async_session.commit()

    template = await GenreTemplateService(async_session).resolve("n_override", "WriterAgent", "generate_beat")

    assert "数据库二级正文规则" in template.prompt_blocks["prose_rules"]
    assert template.quality_config["dimension_weights"]["readability"] == 1.4


@pytest.mark.asyncio
async def test_resolve_historical_novel_without_genre_uses_default(async_session):
    async_session.add(NovelState(novel_id="n_old", current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    template = await GenreTemplateService(async_session).resolve("n_old", "WriterAgent", "generate_beat")

    assert template.genre.primary_slug == "general"
    assert template.genre.secondary_slug == "uncategorized"
    assert "source_conflict" in template.quality_config["blocking_rules"]


def test_merge_replace_policy_replaces_block():
    service = GenreTemplateService(None)
    merged = service.merge_templates_for_test(
        [
            {"prompt_blocks": {"prose_rules": ["旧规则"]}, "merge_policy": {}},
            {"prompt_blocks": {"prose_rules": ["新规则"]}, "merge_policy": {"prose_rules": "replace"}},
        ]
    )
    assert merged.prompt_blocks["prose_rules"] == ["新规则"]
