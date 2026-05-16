import pytest

from novel_dev.genres.defaults import BUILTIN_TEMPLATES
from novel_dev.genres.models import validate_template_is_generic


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES)
def test_production_genre_templates_are_generic(template):
    validate_template_is_generic(template)
