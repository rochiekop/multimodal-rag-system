"""Import every ORM model so Base.metadata knows all tables (used by Alembic and tests)."""

from app.audit.models import AuditLog
from app.chat.models import Conversation, Message
from app.documents.models import (
    Collection,
    Document,
    DocumentVersion,
    collection_groups,
    document_groups,
)
from app.guardrails.models import GuardrailEvent, Notification, UsageRecord
from app.llm.models import RagConfigVersion
from app.users.models import Group, User, user_groups

__all__ = [
    "AuditLog",
    "Collection",
    "Conversation",
    "Document",
    "DocumentVersion",
    "GuardrailEvent",
    "Group",
    "Message",
    "Notification",
    "RagConfigVersion",
    "UsageRecord",
    "User",
    "collection_groups",
    "document_groups",
    "user_groups",
]
