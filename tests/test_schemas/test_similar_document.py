from novel_dev.schemas.similar_document import SimilarDocument


def test_similar_document_creation():
    doc = SimilarDocument(
        doc_id="doc_123",
        doc_type="setting",
        title="星辰学院",
        content_preview="位于大陆中央的魔法学院...",
        similarity_score=0.92,
    )
    assert doc.doc_id == "doc_123"
    assert doc.similarity_score == 0.92


def test_similar_document_defaults():
    doc = SimilarDocument(
        doc_id="doc_456",
        doc_type="worldview",
        title="世界观",
        content_preview="",
        similarity_score=0.0,
    )
    assert doc.content_preview == ""
