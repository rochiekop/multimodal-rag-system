import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.users.models import Group


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    SCANNING = "scanning"
    PARSING = "parsing"
    ENRICHING = "enriching"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    REJECTED = "rejected"


collection_groups = Table(
    "collection_groups",
    Base.metadata,
    Column(
        "collection_id", Uuid, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("group_id", Uuid, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

document_groups = Table(
    "document_groups",
    Base.metadata,
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Uuid, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class Collection(Base):
    __tablename__ = "collections"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    sensitive: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    groups: Mapped[list[Group]] = relationship(secondary=collection_groups, lazy="selectin")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("collection_id", "filename"),)
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="RESTRICT")
    )
    filename: Mapped[str] = mapped_column(String(255))
    # The version search uses. Only set once a version is fully indexed.
    current_version_id: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    collection: Mapped[Collection] = relationship(lazy="selectin")
    restricted_groups: Mapped[list[Group]] = relationship(
        secondary=document_groups, lazy="selectin"
    )
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        order_by="DocumentVersion.version_no",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    version_no: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.QUEUED.value, index=True)
    failed_stage: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(String(1000))
    chunk_count: Mapped[int] = mapped_column(default=0)
    page_count: Mapped[int | None]
    uploaded_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="versions", lazy="selectin")
