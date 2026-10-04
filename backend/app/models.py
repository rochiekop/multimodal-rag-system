"""Import every ORM model so Base.metadata knows all tables (used by Alembic and tests)."""

from app.audit.models import AuditLog
from app.documents.models import (
    Collection,
    Document,
    DocumentVersion,
    collection_groups,
    document_groups,
)
from app.users.models import Group, User, user_groups

__all__ = [
    "AuditLog",
    "Collection",
    "Document",
    "DocumentVersion",
    "Group",
    "User",
    "collection_groups",
    "document_groups",
    "user_groups",
]
