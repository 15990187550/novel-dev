import importlib
import py_compile


def test_brainstorm_module_compiles():
    py_compile.compile("src/novel_dev/export/brainstorm.py", doraise=True)


def test_render_brainstorm_prompt_includes_combined_text():
    module = importlib.import_module("novel_dev.export.brainstorm")

    prompt = module.render_brainstorm_prompt("世界观: 天玄大陆\n主角: 张三")

    assert "世界观: 天玄大陆" in prompt
    assert "主角: 张三" in prompt
    assert "=== SYNOPSIS COMPLETE ===" in prompt
