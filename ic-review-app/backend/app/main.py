from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app import db as db_module
from app.config import ROOT_DIR, get_settings
from app.seed import seed_demo
from app.services.standard_control_library import seed_builtin_standard_controls
from app.services.upload_utils import parse_api_error_detail


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(ROOT_DIR / "data").mkdir(parents=True, exist_ok=True)
    db_module.init_db()
    db = db_module.SessionLocal()
    try:
        seed_builtin_standard_controls(db)
    finally:
        db.close()
    if settings.auto_seed:
        db = db_module.SessionLocal()
        try:
            from app.models import ReviewTask

            if db.query(ReviewTask).count() == 0:
                seed_demo(db)
        finally:
            db.close()
    yield


app = FastAPI(
    title="内控制度智能审查平台 Demo",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": parse_api_error_detail(exc.detail)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "ERR_INTERNAL: 系统暂时无法完成请求，诊断信息已记录，请稍后重试"},
    )
