from sqlalchemy import inspect

from novel_dev.db.models import Entity, EntityVersion, Chapter, NovelState


def test_entity_table_name():
    assert Entity.__tablename__ == "entities"


def test_version_table_name():
    assert EntityVersion.__tablename__ == "entity_versions"


def test_chapter_table_name():
    assert Chapter.__tablename__ == "chapters"


def test_novel_state_table_name():
    assert NovelState.__tablename__ == "novel_state"
