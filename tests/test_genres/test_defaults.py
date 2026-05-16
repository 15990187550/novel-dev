import pytest

from novel_dev.genres.defaults import BUILTIN_CATEGORIES, BUILTIN_TEMPLATES, default_genre
from novel_dev.genres.models import GenreCategory, GenreTemplate, NovelGenre, validate_template_is_generic


def test_builtin_categories_include_required_core_tree():
    tree = {(item.slug, item.parent_slug): item for item in BUILTIN_CATEGORIES}
    assert ("general", None) in tree
    assert ("uncategorized", "general") in tree
    assert ("xuanhuan", None) in tree
    assert ("zhutian", "xuanhuan") in tree
    assert ("dushi", None) in tree
    assert ("workplace_business", "dushi") in tree


def test_default_genre_is_general_uncategorized():
    genre = default_genre()
    assert genre.primary_slug == "general"
    assert genre.primary_name == "通用"
    assert genre.secondary_slug == "uncategorized"
    assert genre.secondary_name == "未分类"


def test_builtin_templates_have_global_and_genre_layers():
    keys = {(tpl.scope, tpl.category_slug, tpl.agent_name, tpl.task_name) for tpl in BUILTIN_TEMPLATES}
    assert ("global", None, "*", "*") in keys
    assert ("primary", "xuanhuan", "*", "*") in keys
    assert ("secondary", "zhutian", "*", "*") in keys
    assert ("secondary", "workplace_business", "*", "*") in keys


def test_genre_template_rejects_invalid_category_slug():
    with pytest.raises(ValueError):
        GenreTemplate(scope="primary", category_slug="Bad-Slug")


def test_genre_category_rejects_invalid_parent_slug():
    with pytest.raises(ValueError):
        GenreCategory(slug="child", name="子类", level=2, parent_slug="Bad-Slug")


def test_genre_template_rejects_invalid_parent_slug():
    with pytest.raises(ValueError):
        GenreTemplate(scope="secondary", category_slug="zhutian", parent_slug="Bad-Slug")


def test_genre_template_rejects_unknown_prompt_block_name():
    with pytest.raises(ValueError):
        GenreTemplate(scope="global", prompt_blocks={"bad_block": ["x"]})


def test_genre_template_requires_category_for_primary_scope():
    with pytest.raises(ValueError):
        GenreTemplate(scope="primary")


def test_genre_template_rejects_category_for_global_scope():
    with pytest.raises(ValueError):
        GenreTemplate(scope="global", category_slug="xuanhuan")


def test_genre_template_requires_parent_for_secondary_scope():
    with pytest.raises(ValueError):
        GenreTemplate(scope="secondary", category_slug="zhutian")


def test_genre_template_allows_none_parent_slug():
    template = GenreTemplate(scope="global", category_slug=None, parent_slug=None)
    assert template.category_slug is None
    assert template.parent_slug is None


def test_novel_genre_rejects_invalid_primary_slug():
    with pytest.raises(ValueError):
        NovelGenre(
            primary_slug="Bad",
            primary_name="坏",
            secondary_slug="uncategorized",
            secondary_name="未分类",
        )


def test_novel_genre_rejects_invalid_secondary_slug():
    with pytest.raises(ValueError):
        NovelGenre(
            primary_slug="general",
            primary_name="通用",
            secondary_slug="Bad-Slug",
            secondary_name="坏",
        )


def test_validate_template_is_generic_exported_from_package():
    from novel_dev.genres import validate_template_is_generic as exported

    assert exported is validate_template_is_generic


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES)
def test_builtin_templates_do_not_contain_concrete_story_content(template):
    validate_template_is_generic(template)


@pytest.mark.parametrize(
    "prompt_line",
    [
        "第三章安排主角进入新地图并揭开隐藏身份。",
        "角色说道:\"这里的规则由我来定。\"",
        "模板默认地点是风雷宗，默认道具是九转丹。",
        "参考《某某名著》的世界观和主角关系。",
    ],
)
def test_validate_template_is_generic_rejects_story_specific_prompt_lines(prompt_line):
    template = GenreTemplate(scope="global", prompt_blocks={"setting_rules": [prompt_line]})

    with pytest.raises(ValueError, match="genre template must stay generic"):
        validate_template_is_generic(template)
