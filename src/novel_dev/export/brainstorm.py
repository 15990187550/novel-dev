from importlib import resources


_COMBINED_TEXT_PLACEHOLDER = "{combined_text}"


def render_brainstorm_prompt(combined_text: str) -> str:
    template = (
        resources.files("novel_dev.export")
        .joinpath("templates/brainstorm.md")
        .read_text(encoding="utf-8")
    )
    if template.count(_COMBINED_TEXT_PLACEHOLDER) != 1:
        raise ValueError("Brainstorm prompt template must contain one combined text placeholder")
    return template.replace(_COMBINED_TEXT_PLACEHOLDER, combined_text, 1)
