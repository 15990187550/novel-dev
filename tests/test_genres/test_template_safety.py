import pytest
from pathlib import Path

from novel_dev.genres.defaults import BUILTIN_TEMPLATES
from novel_dev.genres.models import validate_template_is_generic


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES)
def test_production_genre_templates_are_generic(template):
    validate_template_is_generic(template)


def test_formal_workflow_production_paths_do_not_embed_story_specific_fragments():
    repo_root = Path(__file__).resolve().parents[2]
    paths = [
        repo_root / "src/novel_dev/genres",
        repo_root / "src/novel_dev/agents",
        repo_root / "src/novel_dev/services",
        repo_root / "src/novel_dev/testing/generation_runner.py",
        repo_root / "AGENTS.md",
    ]
    forbidden_fragments = (
        "_repair_known_quality_fragments",
        "陆照",
        "李大牛",
        "王明月",
        "青云宗",
        "玄火盟",
        "血海殿",
        "瓦片",
        "凝气草",
        "职场霸凌还不用负法律责任",
        "搁前世",
        "藏书阁",
        "宗门长老会",
        "传承之争",
        "古经",
        "飞剑",
        "雷劫",
        "玉佩",
        "玉简",
        "血书",
        "令牌",
        "抽象玄幻",
        "现代吐槽",
        "完美世界",
        "遮天",
        "一世之尊",
        "魔门圣子",
        "魔教圣子",
        "血煞盟少主",
        "妖族少主",
        "认识宗门环境",
        "必须在继续追查与保全自身之间做出选择",
        "追兵逼近",
        "秘密暴露",
    )

    matches = []
    for path in paths:
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for file_path in files:
            if "__pycache__" in file_path.parts:
                continue
            text = file_path.read_text(encoding="utf-8")
            for fragment in forbidden_fragments:
                if fragment in text:
                    matches.append(f"{file_path.relative_to(repo_root)}: {fragment}")

    assert matches == []
