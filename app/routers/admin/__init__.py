from fastapi import APIRouter

from app.routers.admin.auth import router as auth_router
from app.routers.admin.admin_donations import router as donations_router
from app.routers.admin.admin_needs import router as needs_router
from app.routers.admin.admin_news import router as news_router
from app.routers.admin.admin_exports import router as exports_router

router = APIRouter(prefix="/admin", tags=["Admin"])

router.include_router(auth_router)
router.include_router(donations_router)
router.include_router(needs_router)
router.include_router(news_router)
router.include_router(exports_router)