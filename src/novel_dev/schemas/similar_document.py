from pydantic import BaseModel


class SimilarDocument(BaseModel):
    doc_id: str
    doc_type: str
    title: str
    content_preview: str
    similarity_score: float
