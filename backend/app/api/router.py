from fastapi import APIRouter

from app.api import (
    admin,
    admin_dashboard,
    admin_documents,
    admin_evaluation,
    admin_notifications,
    admin_rag_config,
    admin_review,
    auth,
    chat,
    health,
)
from app.api import settings as settings_api

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(admin_dashboard.router)
api_router.include_router(admin_documents.router)
api_router.include_router(admin_evaluation.router)
api_router.include_router(admin_notifications.router)
api_router.include_router(admin_rag_config.router)
api_router.include_router(admin_review.router)
api_router.include_router(chat.router)
api_router.include_router(settings_api.public_router)
api_router.include_router(settings_api.router)
