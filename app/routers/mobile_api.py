from fastapi import APIRouter

from app.routers.mobile_auth import router as auth_router
from app.routers.mobile_content import router as content_router
from app.routers.mobile_submissions import router as submissions_router

router = APIRouter(prefix="/api", tags=["Mobile API"])
router.include_router(auth_router)
router.include_router(content_router)
router.include_router(submissions_router)
