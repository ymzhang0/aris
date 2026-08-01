from fastapi import APIRouter

from .routers.frontend import router as frontend_router
from .routers.submission import router as submission_router
from .routers.process import router as process_router
from .routers.data import router as data_router
from .routers.management import router as management_router

router = APIRouter()
router.include_router(frontend_router)
router.include_router(submission_router)
router.include_router(process_router)
router.include_router(data_router)
router.include_router(management_router)
