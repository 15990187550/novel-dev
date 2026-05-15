import pytest

from novel_dev.genres.defaults import BUILTIN_CATEGORIES, BUILTIN_TEMPLATES, default_genre
from novel_dev.genres.models import validate_template_is_generic


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


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES)
def test_builtin_templates_do_not_contain_concrete_story_content(template):
    validate_template_is_generic(template)
