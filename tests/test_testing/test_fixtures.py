from importlib.resources import files

from novel_dev.testing.fixtures import load_generation_fixture


def test_load_builtin_minimal_fixture():
    fixture = load_generation_fixture("minimal_builtin")

    assert fixture.dataset == "minimal_builtin"
    assert fixture.title == "Codex 最小生成验收"
    assert "初始设定目标" in fixture.initial_setting_idea
    assert fixture.minimum_chapter_chars > 0


def test_builtin_minimal_fixture_is_packaged_resource():
    resource = files("novel_dev.testing").joinpath("fixtures/minimal_novel.yaml")

    assert resource.is_file()

    fixture = load_generation_fixture("minimal_builtin")
    assert fixture.watched_terms == ["青云宗", "林照", "玄火盟", "血海殿"]


def test_load_external_fixture_directory(tmp_path):
    source = tmp_path / "novel"
    source.mkdir()
    (source / "fixture.yaml").write_text(
        "\n".join(
            [
                "dataset: external_dir",
                "title: 外部验收小说",
                "initial_setting_idea: 外部设定输入",
                "minimum_chapter_chars: 50",
                "watched_terms:",
                "  - 玄火盟",
                "",
            ]
        ),
        encoding="utf-8",
    )

    fixture = load_generation_fixture(str(source))

    assert fixture.dataset == "external_dir"
    assert fixture.title == "外部验收小说"
    assert fixture.initial_setting_idea == "外部设定输入"
    assert fixture.minimum_chapter_chars == 50
    assert fixture.watched_terms == ["玄火盟"]


def test_load_external_fixture_file(tmp_path):
    source = tmp_path / "custom.yaml"
    source.write_text(
        "\n".join(
            [
                "dataset: external_file",
                "title: 文件验收小说",
                "initial_setting_idea: 文件设定输入",
                "minimum_chapter_chars: 60",
                "watched_terms:",
                "  - 青云宗",
                "",
            ]
        ),
        encoding="utf-8",
    )

    fixture = load_generation_fixture(str(source))

    assert fixture.dataset == "external_file"
    assert fixture.title == "文件验收小说"
    assert fixture.initial_setting_idea == "文件设定输入"
    assert fixture.minimum_chapter_chars == 60
    assert fixture.watched_terms == ["青云宗"]
