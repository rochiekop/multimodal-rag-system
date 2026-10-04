from app.documents.models import Document


def effective_access_groups(document: Document) -> list[str]:
    """Collection groups, narrowed by the document's own restriction when it has one."""
    allowed = {g.id for g in document.collection.groups}
    if document.restricted_groups:
        allowed &= {g.id for g in document.restricted_groups}
    return sorted(str(group_id) for group_id in allowed)
