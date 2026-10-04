from fastapi import APIRouter

from app.api import admin, admin_documents, auth, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(admin_documents.router)
