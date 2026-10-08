from fastapi import APIRouter, Depends

from app.security import require_csrf
from app.routers.admin.auth import (
    protected_router as protected_auth_router,
    require_staff,
    router as auth_router,
)
from app.routers.admin.admindonations import router as donations_router
from app.routers.admin.adminneeds import router as needs_router
from app.routers.admin.adminnews import router as news_router
from app.routers.admin.adminexports import router as exports_router

# Admin API router
router = APIRouter(
    prefix="/admin", tags=["Admin"], dependencies=[Depends(require_csrf)]
)

# Include sub-routers for different admin functionalities
router.include_router(auth_router)
router.include_router(protected_auth_router, dependencies=[Depends(require_staff)])
router.include_router(donations_router, dependencies=[Depends(require_staff)])
router.include_router(needs_router, dependencies=[Depends(require_staff)])
router.include_router(news_router, dependencies=[Depends(require_staff)])
router.include_router(exports_router, dependencies=[Depends(require_staff)])