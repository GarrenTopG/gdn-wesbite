from fastapi import APIRouter

from app.routers.admin.auth import router as auth_router
from app.routers.admin.admindonations import router as donations_router
from app.routers.admin.adminneeds import router as needs_router
from app.routers.admin.adminnews import router as news_router
from app.routers.admin.adminexports import router as exports_router

# Admin API router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Include sub-routers for different admin functionalities
router.include_router(auth_router)
router.include_router(donations_router)
router.include_router(needs_router)
router.include_router(news_router)
router.include_router(exports_router)