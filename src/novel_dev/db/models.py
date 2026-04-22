from typing import List, Optional
from datetime import datetime

from sqlalchemy import (
    ForeignKey, Text, Integer, Boolean, Float, JSON, TIMESTAMP, UniqueConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

try:
    from pgvector.sqlalchemy import Vector as PgVector
except ImportError:
    PgVector = None


class VectorCompat(TypeDecorator):
    """Compatibility type that uses pgvector.Vector on PostgreSQL and JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int = 1024):
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if PgVector is not None and dialect.name == "postgresql":
            return dialect.type_descriptor(PgVector(self.dimensions))
        return dialect.type_descriptor(JSON)


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    vector_embedding: Mapped[Optional[list[float]]] = mapped_column(VectorCompat(1536), nullable=True)
    system_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_group_id: Mapped[Optional[str]] = mapped_column(ForeignKey("entity_groups.id"), nullable=True)
    manual_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manual_group_id: Mapped[Optional[str]] = mapped_column(ForeignKey("entity_groups.id"), nullable=True)
    classification_reason: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    classification_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    system_needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    search_document: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    search_vector_embedding: Mapped[Optional[list[float]]] = mapped_column(VectorCompat(1024), nullable=True)

    versions: Mapped[List["EntityVersion"]] = relationship(back_populates="entity", order_by="EntityVersion.version")


class EntityGroup(Base):
    __tablename__ = "entity_groups"
    __table_args__ = (
        UniqueConstraint("novel_id", "category", "group_slug", name="uix_entity_group_scope"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    group_name: Mapped[str] = mapped_column(Text, nullable=False)
    group_slug: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="system")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EntityVersion(Base):
    __tablename__ = "entity_versions"
    __table_args__ = (UniqueConstraint("entity_id", "version", name="uix_entity_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    diff_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    entity: Mapped["Entity"] = relationship(back_populates="versions")


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)


class Timeline(Base):
    __tablename__ = "timeline"
    __table_args__ = (UniqueConstraint("novel_id", "tick", name="uix_timeline_novel_tick"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tick: Mapped[int] = mapped_column(Integer, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    anchor_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Spaceline(Base):
    __tablename__ = "spaceline"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("spaceline.id"), nullable=True)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Foreshadowing(Base):
    __tablename__ = "foreshadowings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    埋下_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    埋下_time_tick: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    埋下_location_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    相关人物_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    回收条件: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    回收状态: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    recovered_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recovered_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    回收影响: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class NovelState(Base):
    __tablename__ = "novel_state"

    novel_id: Mapped[str] = mapped_column(Text, primary_key=True)
    current_phase: Mapped[str] = mapped_column(Text, nullable=False)
    current_volume_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checkpoint_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("volume_id", "chapter_number", name="uix_volume_chapter"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    volume_id: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    raw_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    polished_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score_overall: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_breakdown: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    review_feedback: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fast_review_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fast_review_feedback: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    vector_embedding: Mapped[Optional[list[float]]] = mapped_column(VectorCompat(1024), nullable=True)


class NovelDocument(Base):
    __tablename__ = "novel_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector_embedding: Mapped[Optional[List[float]]] = mapped_column(VectorCompat(1024), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class OutlineSession(Base):
    __tablename__ = "outline_sessions"
    __table_args__ = (
        UniqueConstraint("novel_id", "outline_type", "outline_ref", name="uix_outline_session_scope"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    outline_type: Mapped[str] = mapped_column(Text, nullable=False)
    outline_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    conversation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_result_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages: Mapped[List["OutlineMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class BrainstormWorkspace(Base):
    __tablename__ = "brainstorm_workspaces"
    __table_args__ = (
        UniqueConstraint("novel_id", "status", name="uix_brainstorm_workspace_novel_status"),
        Index("ix_brainstorm_workspaces_novel_status", "novel_id", "status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outline_drafts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    setting_docs_draft: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_saved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)


class OutlineMessage(Base):
    __tablename__ = "outline_messages"
    __table_args__ = (
        Index("ix_outline_messages_session_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("outline_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    session: Mapped["OutlineSession"] = relationship(back_populates="messages")


class PendingExtraction(Base):
    __tablename__ = "pending_extractions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    raw_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    proposed_entities: Mapped[Optional[List[dict]]] = mapped_column(JSON, nullable=True)
    diff_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    resolution_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
