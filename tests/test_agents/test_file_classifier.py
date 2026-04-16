import pytest

from novel_dev.agents.file_classifier import FileClassifier, FileClassificationResult


def test_rule_based_setting():
    classifier = FileClassifier()
    result = classifier.classify(filename="world_setting.txt", content_preview="The cultivation world...")
    assert result.file_type == "setting"
    assert result.confidence == 0.95


def test_rule_based_style_sample():
    classifier = FileClassifier()
    result = classifier.classify(filename="style_sample.txt", content_preview="He walked into the room...")
    assert result.file_type == "style_sample"
    assert result.confidence == 0.95


def test_content_heuristic_setting():
    classifier = FileClassifier()
    result = classifier.classify(filename="notes.txt", content_preview="修炼体系与world构建")
    assert result.file_type == "setting"
    assert result.confidence == 0.7


def test_fallback_unknown():
    classifier = FileClassifier()
    result = classifier.classify(filename="notes.txt", content_preview="random notes")
    assert result.file_type in ("setting", "style_sample")
    assert result.confidence == 0.6
