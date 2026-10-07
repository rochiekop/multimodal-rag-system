from fastapi import APIRouter

from app.api import admin, admin_documents, admin_rag_config, auth, chat, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(admin_documents.router)
api_router.include_router(admin_rag_config.router)
api_router.include_router(chat.router)
