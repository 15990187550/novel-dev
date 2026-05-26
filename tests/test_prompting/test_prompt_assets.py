from novel_dev.prompting.assets import prompt_asset_registry


def test_core_prompt_assets_are_registered_with_versions_and_context_policy():
    writer = prompt_asset_registry.get("writer.whole_chapter.context")
    editor = prompt_asset_registry.get("editor.rewrite_beat")
    fast_review = prompt_asset_registry.get("fast_review.chapter")

    assert writer.version
    assert writer.task == "writer"
    assert "chapter_plan" in writer.context_policy.required
    assert "similar_chapters" in writer.context_policy.droppable

    assert editor.task == "editor"
    assert "style_contract" in editor.context_policy.preferred

    assert fast_review.task == "review"
    assert "polished_text" in fast_review.context_policy.required
