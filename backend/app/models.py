"""Import every ORM model so Base.metadata knows all tables (used by Alembic and tests)."""

from app.audit.models import AuditLog
from app.users.models import Group, User, user_groups

__all__ = ["AuditLog", "Group", "User", "user_groups"]
