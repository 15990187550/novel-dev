import pytest

from novel_dev.agents.profile_merger import ProfileMerger, MergeResult
from novel_dev.agents.style_profiler import StyleProfile, StyleConfig


def test_merge_no_conflict():
    merger = ProfileMerger()
    old = StyleProfile(style_guide="Old guide", style_config=StyleConfig(perspective="limited", tone="neutral"))
    new = StyleProfile(style_guide="New guide", style_config=StyleConfig(perspective="limited", tone="intense"))
    result = merger.merge(old, new)
    assert result.merged_profile.style_config.perspective == "limited"
    assert any(c.field == "tone" for c in result.conflicts)


def test_merge_with_new_fields():
    merger = ProfileMerger()
    old = StyleProfile(style_guide="Old", style_config=StyleConfig(perspective="limited"))
    new = StyleProfile(style_guide="New", style_config=StyleConfig(pacing="fast"))
    result = merger.merge(old, new)
    assert result.merged_profile.style_config.perspective == "limited"
    assert result.merged_profile.style_config.pacing == "fast"
